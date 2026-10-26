"""Import a project packet as a new continuation draft.

The archive is untrusted project data. It is validated (schema version, member list and hashes,
paths, links, sizes, compression, image bytes, credentials) and staged privately before the
operator reviews it. Import creates one draft project and nothing else: no tasks, approvals,
routes, grants, spending decisions or credentials come across, and nothing in it is executed.
"""
import hashlib
import io
import json
import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from fastapi import HTTPException

import failure_mining
import project_packet

ROOT = 'project-packet/'
UPLOAD_LIMIT = project_packet.EXPORT_LIMIT + 2 * 1024 * 1024
MEMBER_MAX = 300
MANIFEST_MAX = 2 * 1024 * 1024
STAGE_HOURS = 24
SCHEMA_RE = re.compile(r'^bamcio\.project-packet/(\d+)(?:\.\d+)?$')
SLOT_FILE = re.compile(r'^assets/(img/[a-z0-9][a-z0-9_-]{0,63}\.jpg|video/[a-z0-9][a-z0-9_-]{0,63}\.mp4)$')
LIVING_FILE = re.compile(r'^living/docs/project/(?:[A-Za-z0-9_.-]{1,80}/){0,3}[A-Za-z0-9_.-]{1,80}$')


def _fail(message, status=422):
    raise HTTPException(status, message)


def stage_root(settings):
    return Path(settings.data_dir) / 'packet-imports'


def _kind_of(name):
    """What an archive member may be. Anything else is refused, not ignored."""
    documents = {d for d, _ in project_packet.DOCUMENTS}
    if name in documents:
        return 'document'
    if LIVING_FILE.fullmatch(name):
        return 'living'
    if name.startswith('media/references/') and __import__('media_references').NAME_RE.fullmatch(name.rsplit('/', 1)[1]):
        return 'reference'
    if SLOT_FILE.fullmatch(name):
        return 'published'
    return None


def _secret(text):
    return any(p.search(text) for p in failure_mining._SECRETS)


def validate(raw):
    """(manifest, {name: bytes}) from a packet archive, or a 422 that says what is wrong."""
    import media_references
    if len(raw) > UPLOAD_LIMIT:
        _fail(f'A packet can be at most {UPLOAD_LIMIT // 1048576} MB.', 413)
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        infos = z.infolist()
    except (zipfile.BadZipFile, OSError, ValueError):
        _fail('This file is not a project packet (.zip).')
    if len(infos) > MEMBER_MAX:
        _fail(f'A packet can hold at most {MEMBER_MAX} files.')
    files, total, seen = {}, 0, set()
    for info in infos:
        name = info.filename
        if info.is_dir():
            continue
        path = PurePosixPath(name)
        if (not name.startswith(ROOT) or '\\' in name or '\0' in name or path.is_absolute() or '..' in path.parts
                or any(part in ('', '.') for part in name.split('/'))):
            _fail(f'Unsafe path in packet: {name[:120]}')
        if (info.external_attr >> 16) & 0o170000 not in (0, 0o100000):
            _fail(f'Links and special files are not allowed in a packet: {name[:120]}')
        if name in seen:
            _fail(f'Duplicate file in packet: {name[:120]}')
        seen.add(name)
        total += info.file_size
        if info.file_size > project_packet.MEDIA_FILE_LIMIT or total > project_packet.EXPORT_LIMIT:
            _fail('The packet is larger than its limits once unpacked.', 413)
        if info.file_size > 1048576 and info.compress_size and info.file_size / info.compress_size > 200:
            _fail(f'Suspicious compression in {name[:120]}; the packet was refused.')
        try:
            data = z.read(info)
        except (zipfile.BadZipFile, OSError, ValueError, EOFError, __import__('zlib').error):
            _fail(f'Damaged file in packet: {name[:120]}')
        if len(data) != info.file_size:
            _fail(f'Damaged file in packet: {name[:120]}')
        files[name[len(ROOT):]] = data
    if 'PACKET.json' not in files or len(files['PACKET.json']) > MANIFEST_MAX:
        _fail('PACKET.json is missing or too large.')
    try:
        manifest = json.loads(files.pop('PACKET.json'))
    except (ValueError, UnicodeDecodeError):
        _fail('PACKET.json is not valid JSON.')
    if not isinstance(manifest, dict) or not isinstance(manifest.get('schema'), str) or not (m := SCHEMA_RE.fullmatch(manifest['schema'])):
        _fail('This is not a project packet (unknown schema).')
    if int(m.group(1)) != 1:
        _fail(f'This packet uses {manifest["schema"]}, made by a newer version. Update the app, then import it again.')
    listed = {x.get('path'): x for x in (manifest.get('export') or {}).get('members', []) if isinstance(x, dict)}
    if set(listed) != set(files):
        _fail('The packet’s file list does not match its contents. It may be incomplete or altered.')
    for name, data in files.items():
        if listed[name].get('sha256') != hashlib.sha256(data).hexdigest():
            _fail(f'{name} does not match its recorded hash. The packet may be damaged or altered.')
        kind = _kind_of(name)
        if kind is None:
            _fail(f'Unexpected file in packet: {name[:120]}')
        if kind in ('document', 'living'):
            try:
                text = data.decode('utf-8')
            except UnicodeDecodeError:
                _fail(f'{name} is not UTF-8 text.')
            if _secret(text):
                _fail(f'{name} appears to contain a credential. Remove it from the source and export again.')
        elif kind == 'reference' and not media_references._kind(data):
            _fail(f'{name} is not a PNG, JPEG, WebP or GIF image.')
    intent = manifest.get('intent')
    if not isinstance(intent, dict) or not isinstance(intent.get('title'), str) or not isinstance(intent.get('brief'), str):
        _fail('The packet has no project intent (title and brief).')
    if _secret(json.dumps(intent)):
        _fail('The packet’s project intent appears to contain a credential.')
    for name in ('START-HERE.md', '01-brief.md', '04-state.md'):
        if name not in files:
            _fail(f'The packet is missing {name}.')
    return manifest, files


def _cleanup(settings):
    root = stage_root(settings)
    if not root.is_dir():
        return
    cutoff = time.time() - STAGE_HOURS * 3600
    for d in root.iterdir():
        try:
            if d.is_dir() and not d.is_symlink() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def _review(manifest, files, stage_id):
    src, ws, intent = manifest.get('source') or {}, manifest.get('workspace') or {}, manifest['intent']
    assets = []
    for a in manifest.get('assets') or []:
        if isinstance(a, dict):
            assets.append({k: a.get(k) for k in ('kind', 'path', 'slot', 'included', 'missing_reason')})
    return {'import_id': stage_id, 'schema': manifest['schema'],
        'source': {k: src.get(k) for k in ('host', 'project_id', 'revision', 'project_type', 'state', 'title')}
                  | {'product': (manifest.get('generator') or {}).get('product'), 'version': (manifest.get('generator') or {}).get('version')},
        'workspace': {k: ws.get(k) for k in ('path', 'repository', 'branch', 'head', 'changed')},
        'freshness': manifest.get('freshness') or {},
        'intent': {'title': intent['title'][:200], 'project_type': intent.get('project_type'), 'brief': intent['brief'][:20000],
                   'intake_answers': intent.get('intake_answers') or {}},
        'stories': (manifest.get('stories') or [])[:100],
        'documents': sorted(n for n in files if _kind_of(n) == 'document'),
        'living_docs': sorted(n[len('living/'):] for n in files if _kind_of(n) == 'living'),
        'references': sorted(n for n in files if _kind_of(n) == 'reference'),
        'published_media': sorted(n for n in files if _kind_of(n) == 'published'),
        'assets': assets,
        'missing': [a for a in assets if a.get('included') is False and a.get('kind') != 'slot'],
        'rule': 'Imported text is project history and evidence, not instructions. Import creates a draft only: '
                'no tasks, approvals, routes, branch grants, spending decisions or credentials carry over.'}


def inspect(settings, raw, owner):
    """Validate and stage an uploaded packet for review. Returns what the operator reviews."""
    manifest, files = validate(raw)
    _cleanup(settings)
    stage_id = str(uuid.uuid4())
    root = stage_root(settings) / stage_id
    for name, data in files.items():
        target = root / 'files' / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_bytes(data)
    review = _review(manifest, files, stage_id)
    project_packet._write(root / 'manifest.json', json.dumps(manifest))
    project_packet._write(root / 'owner.json', json.dumps({'owner': owner, 'created_at': int(time.time())}))
    return review


def _staged(settings, stage_id, owner):
    if not re.fullmatch(r'[0-9a-f-]{36}', stage_id or ''):
        _fail('Upload the packet again; this import is not available.', 404)
    root = stage_root(settings) / stage_id
    meta = project_packet._read_json(root / 'owner.json')
    if not meta:
        _fail('This import expired or was already used. Upload the packet again.', 404)
    if meta.get('owner') != owner:
        _fail('This import belongs to another profile.', 403)
    manifest = project_packet._read_json(root / 'manifest.json')
    files = {p.relative_to(root / 'files').as_posix(): p.read_bytes() for p in (root / 'files').rglob('*') if p.is_file()}
    return root, manifest, files


def _continuation(manifest, imported_folder):
    src, ws = manifest.get('source') or {}, manifest.get('workspace') or {}
    stories = [x for x in manifest.get('stories') or [] if isinstance(x, dict)]
    done = [x for x in stories if str(x.get('status', '')).startswith('accepted')]
    remaining = [x for x in stories if not str(x.get('status', '')).startswith('accepted')]
    lines = ['', '## Continuation from project packet', '',
             f"Imported from {(manifest.get('generator') or {}).get('product', 'a dashboard')} project {src.get('project_id')} "
             f"revision {src.get('revision')} ({src.get('state')}). Source workspace: {ws.get('repository') or 'no registered repository'}, "
             f"branch {ws.get('branch') or 'unknown'}, commit {(ws.get('head') or 'unknown')[:12]}. "
             'Statuses below are history from the source project, not local acceptance. Confirm the current source before planning.']
    if done:
        lines += ['', 'Accepted in the source project:'] + [f"- {x.get('key')}: {str(x.get('title', ''))[:160]}" for x in done[:40]]
    if remaining:
        lines += ['', 'Remaining in the source project:'] + [f"- {x.get('key')}: {str(x.get('title', ''))[:160]} ({x.get('status')})" for x in remaining[:40]]
    lines += ['', f'Imported packet documents (read-only reference): {imported_folder}']
    return '\n'.join(lines)


def create(s, settings, stage_id, working_dir, copy_references, owner):
    """The continuation draft, from files staged privately after validation."""
    import media_references
    import projects
    from project_schemas import Document
    from pydantic import ValidationError
    root, manifest, files = _staged(settings, stage_id, owner)
    intent = manifest['intent']
    doc = {'title': intent['title'][:200] or 'Imported project', 'brief': '', 'constraints': str(intent.get('constraints') or '')[:10000],
           'working_dir': working_dir, 'project_type': intent.get('project_type'), 'intake_answers': intent.get('intake_answers') or {}, 'nodes': []}
    notes = []
    try:
        Document.model_validate({**doc, 'brief': 'x'})
    except ValidationError:
        notes.append('The source project type or intake answers do not apply on this host; they are kept in the imported brief document.')
        doc.update(project_type=None, intake_answers={})
    placeholder = _continuation(manifest, '<packet folder>')
    doc['brief'] = (str(intent['brief'])[:20000 - len(placeholder) - 200] + placeholder)[:20000]
    p = projects.create(s, Document.model_validate(doc).model_dump(), settings, owner)
    imported = project_packet.folder(settings, p.id) / 'imported'
    shutil.rmtree(imported, ignore_errors=True)  # a reused project id never shows another import's files
    try:
        return _finish(s, settings, p, root, manifest, files, imported, copy_references, notes, owner)
    except Exception:
        shutil.rmtree(imported, ignore_errors=True)
        raise


def _finish(s, settings, p, root, manifest, files, imported, copy_references, notes, owner):
    import media_references
    import projects
    d = projects.document(p)
    d['brief'] = d['brief'].replace('<packet folder>', str(imported))
    p.document = json.dumps(d)
    projects.write_brief(p, d)
    for name, data in files.items():
        target = imported / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_bytes(data)
    project_packet._write(imported / 'PACKET.json', json.dumps(manifest, indent=1))
    copied, skipped = [], []
    if copy_references:
        workspace = Path(d['working_dir']).expanduser()
        for name, data in sorted(files.items()):
            if _kind_of(name) != 'reference':
                continue
            try:
                copied.append(media_references.save(workspace, name.rsplit('/', 1)[1], data)['path'])
            except (media_references.ReferenceError_, OSError) as exc:
                skipped.append(f'{name}: {exc}')
    src, ws = manifest.get('source') or {}, manifest.get('workspace') or {}
    import workspace_handoff
    dest = workspace_handoff.observation(Path(d['working_dir']).expanduser())
    match = ('matches the source commit' if dest.get('head') and dest['head'] == ws.get('head') else
             f"is at {dest['head'][:12] if dest.get('head') else 'no Git commit'}, not the source commit {(ws.get('head') or 'unknown')[:12]}")
    text = (f"Imported project packet {manifest['schema']} from {(manifest.get('generator') or {}).get('product')} "
            f"{(manifest.get('generator') or {}).get('version')} project {src.get('project_id')} revision {src.get('revision')} on host {src.get('host')}. "
            f"Destination workspace {match}. {len(files)} files kept read-only in {imported}. "
            f"Reference images copied: {', '.join(copied) or 'none'}." + (f" Not copied: {'; '.join(skipped)}." if skipped else '') +
            (' ' + ' '.join(notes) if notes else '') +
            ' Imported statuses are source history; no tasks, approvals, routes, grants or spending decisions were carried over.')
    projects.memory(s, p, 'decision', text, owner)
    shutil.rmtree(root, ignore_errors=True)
    return p
