"""Operator-approved Markdown output from read-only project agents.

Model text never supplies paths or permissions. MCD creates one private file; agents
remain read-only. Directory descriptors prevent symlink traversal. This is a proposed
artifact, not an accepted handoff.

Writes are atomic and keyed: the content goes to a temp file, is fsynced and renamed over
the one path derived from (project, story, source run, node), then the directory is
fsynced. A crash leaves either no artifact or a complete one, and a retry of the same
grant writes the same path, never a second artifact. A committed artifact is never
overwritten; only the caller can say the existing file is an uncommitted attempt's.
"""
import contextlib
import fcntl
import json
import os
import re
import stat
from pathlib import Path
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

APPROVAL_ERROR = 'The agent returned a plan that needs output approval, not a completed artifact. Open Projects → Stories & runs → Approve output & continue. MCD can save one Markdown file while the agent stays read-only.'

class Output(BaseModel):
    model_config = ConfigDict(extra='forbid')
    markdown: str = Field(min_length=1, max_length=300000)
    handoff: str = Field(min_length=1, max_length=12000)

def needs_approval(card, run):
    text = run.result_text or ''
    return (card.agent == 'claude' and card.mode == 'read' and
        bool(re.search(r'plan mode|ExitPlanMode', text, re.I)) and
        bool(re.search(r'blocks? writing|not written yet|lift plan mode|approve the plan', text, re.I)))

def incomplete_error(run):
    text = (run.result_text or '').strip()
    if re.fullmatch(r'⚠️\s*🛠️\s*`[^`]+` failed', text):
        return ('The agent returned only a tool-failure warning, without a completed handoff or verification report. '
                'A normal process exit does not mean the story is complete. Review any saved artifacts, '
                'then retry this story to return the full report directly to MCD. No handoff was accepted.')
    # Only a direct admission at the start, not quoted history or a later
    # description of a recovered blocker. Agents commonly put a Markdown handoff
    # heading before a separate Status paragraph, so include one block after a
    # heading; otherwise inspect only the opening block.
    blocks = text.split('\n\n', 2)
    opening = '\n\n'.join(blocks[:2] if blocks and blocks[0].lstrip().startswith('#') else blocks[:1])[:3000]
    explicit = re.search(r"\b(?:none|not one) of (?:this|the) story.?s acceptance criteria (?:are|were) met\b|"
                         r"\b(?:story|task) is (?:[*_`~]+)?(?:only )?(?:partly done|not complete|unfinished|incomplete)\b|"
                         r"\bstatus\s*:\s*(?:not done|not complete)\b|"
                         r"\bverification (?:is|remains) incomplete\b|"
                         r"\b(?:not verified|not executed)\b|"
                         r"\b(?:acceptance criteria|definition of done) (?:remain|remains|is|are) unmet\b|"
                         r"\bnot release-ready\b|"
                         r"\bdo not mark (?:this )?(?:story|task) (?:as )?done\b", opening, re.I)
    explicit = explicit or re.search(r"\bthis (?:story|task) is (?:[*_`~]+)?(?:not done|not complete|unfinished|incomplete)\b|"
                                     r"\bnot fully verified\b|"
                                     r"\bthis handoff does not claim complete verification\b|"
                                     r"\bincomplete verification\b|"
                                     r"\b(?:checks?|verification)\b[^\n]{0,120}\b(?:incomplete|did not run successfully)\b|"
                                     r"\bkeep (?:this )?(?:story|task) incomplete\b|"
                                     r"\bnone of (?:the )?required checks (?:ran|were run|were executed)\b|"
                                     r"\bI did not (?:run|execute) (?:the )?(?:tests?|checks?|build|preview)\b", text, re.I)
    blocked_without_work = (re.search(r'\b(?:blocked|blocks?|cannot proceed)\b', opening, re.I) and
                            re.search(r'\bnothing (?:(?:was|has been) )?(?:created|changed|pushed|implemented|uploaded|published|executed|verified|tested|run)\b', opening, re.I))
    blocked_without_receipts = (re.search(r'\bis blocked\b', opening, re.I) and
                                re.search(r'\b(?:no|without)\b[^.\n]{0,120}\breceipts?\b', opening, re.I))
    unrun_live_checks = re.search(r'\b(?:benchmark|conformance)\b[^\n]*\bnot run\b[^\n]*\bno live results\b', opening, re.I)
    if explicit or blocked_without_work or blocked_without_receipts or unrun_live_checks:
        return ('The agent explicitly reported unfinished work or unmet story acceptance criteria. '
                'A normal process exit does not mean the story is complete. Open the task result, '
                'resolve the reported permissions or missing operator decisions, then retry this story. '
                'No completed handoff was accepted.')
    return None

def parts(project_id, card_id, source_run_id, node_key):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', node_key):
        raise HTTPException(422, 'Invalid project output name.')
    return ('project-outputs', f'project-{int(project_id)}', f'story-{int(card_id)}',
            f'after-run-{int(source_run_id)}', node_key+'.md')

def path(settings, project_id, card_id, source_run_id, node_key):
    return settings.data_dir.expanduser().resolve().joinpath(*parts(project_id,card_id,source_run_id,node_key))

def save(settings, project_id, card_id, source_run_id, node_key, markdown, replace_uncommitted=False):
    content=markdown.encode('utf-8')
    if not markdown.strip() or len(content)>300000:
        raise HTTPException(422, 'Output must contain Markdown and fit within 300 KB.')
    names=parts(project_id,card_id,source_run_id,node_key)
    temp='.'+names[-1]+'.tmp'
    root=settings.data_dir.expanduser().resolve()
    try: fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    except OSError: raise HTTPException(409, 'The private MCD output directory is unavailable.')
    try:
        for name in names[:-1]:
            try:
                os.mkdir(name,0o700,dir_fd=fd)
                os.fsync(fd)  # persist the directory entry before descending
            except FileExistsError: pass
            child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=child
        # Serialize writers of this keyed artifact, including retries in another API
        # process. Locks are released by the kernel on crash; no stale lockfile.
        fcntl.flock(fd,fcntl.LOCK_EX)
        try:
            existing=os.open(names[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        except FileNotFoundError:
            existing=None
        if existing is not None:
            with os.fdopen(existing,'rb') as stream:
                info=os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size>300000:
                    raise HTTPException(409, 'The approved output path is not a bounded Markdown file. Inspect it; MCD will not overwrite it.')
                if stream.read()==content:
                    # The same artifact was already written (e.g. before a DB commit was interrupted).
                    os.fsync(stream.fileno())
                    with contextlib.suppress(FileNotFoundError): os.unlink(temp,dir_fd=fd)
                    os.fsync(fd)
                    return path(settings,project_id,card_id,source_run_id,node_key)
            if not replace_uncommitted:
                raise HTTPException(409, 'The approved output file already exists with different content. Inspect it; MCD will not overwrite it.')
        with contextlib.suppress(FileNotFoundError): os.unlink(temp,dir_fd=fd)  # left by a crash
        out=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
        try:
            with os.fdopen(out,'wb') as stream: stream.write(content);stream.flush();os.fsync(stream.fileno())
            os.replace(temp,names[-1],src_dir_fd=fd,dst_dir_fd=fd)
        except Exception:
            with contextlib.suppress(FileNotFoundError): os.unlink(temp,dir_fd=fd)
            raise
        os.fsync(fd)
        return path(settings,project_id,card_id,source_run_id,node_key)
    except OSError:
        raise HTTPException(409, 'MCD could not safely save the approved output. Check the private output folder for permissions or symlinks; no other file was changed.')
    finally: os.close(fd)

def read(settings, project_id, card_id, source_run_id, node_key):
    fd=None
    try:
        fd=os.open(settings.data_dir.expanduser().resolve(),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        names=parts(project_id,card_id,source_run_id,node_key)
        for name in names[:-1]:
            child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=child
        out=os.open(names[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        with os.fdopen(out,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size>300000:
                raise HTTPException(409, 'The proposed output is no longer a bounded Markdown file.')
            return stream.read().decode('utf-8')
    except (OSError,UnicodeError):
        raise HTTPException(409, 'The proposed output is missing or unsafe to read. Inspect the private output folder before accepting it.')
    finally:
        if fd is not None: os.close(fd)

def parse(raw):
    text=(raw or '').strip()
    if text.startswith('```json\n') and text.endswith('```'): text=text[8:-3].strip()
    return Output.model_validate(json.loads(text))
