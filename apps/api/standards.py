"""A project's repository standards, read as data and never as instructions.

A repository may carry ``docs/development/standards.md``. RCD reads the file from the project's working directory (nothing is
fetched and nothing outside that directory is opened), hashes it, and parses two tables by fixed code: "Definition of done"
(what to run for each kind of change) and "Risk by area" (each area's default risk and route). The text can later raise a
story's risk floor and add checks; it never lowers a floor and never grants a permission.

Every failure is a warning, never an error: a missing or unreadable file means planning goes ahead without it and the page says
so. The parser does not guess; a row it cannot understand is skipped and reported.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

FILE = 'docs/development/standards.md'
MAX_BYTES = 128 * 1024
RISKS = ('low', 'medium', 'high')
_SEPARATOR = re.compile(r'^[\s|:\-]+$')


def _clean(cell: str) -> str:
    return re.sub(r'\s+', ' ', cell.replace('`', '').replace('**', '')).strip()


def _sections(text: str) -> dict[str, list[str]]:
    """Lines under each heading, keyed by the lower-cased heading text."""
    out: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith('#'):
            current = line.lstrip('#').strip().lower()
            out.setdefault(current, [])
        elif current is not None:
            out[current].append(line)
    return out


def _find(sections: dict[str, list[str]], phrase: str):
    return next((lines for heading, lines in sections.items() if phrase in heading), None)


def _table(lines: list[str]):
    """Header cells and the rows of the first pipe table in ``lines``."""
    rows = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('|'):
            rows.append(stripped)
        elif rows:
            break
    if len(rows) < 2:
        return None, []
    cells = lambda r: [_clean(c) for c in r.strip().strip('|').split('|')]
    header = [h.lower() for h in cells(rows[0])]
    body = [cells(r) for r in rows[1:] if not _SEPARATOR.match(r)]
    return header, body


def _column(header: list[str], *words: str):
    return next((i for i, h in enumerate(header) if all(w in h for w in words)), None)


def _risk(value: str):
    """The highest risk named in a cell ("low to medium" is medium); None when it names none."""
    found = [r for r in RISKS if re.search(rf'\b{r}\b', value.lower())]
    return found[-1] if found else None


def _read(workdir):
    root = Path(workdir).resolve()
    target = root
    for part in FILE.split('/'):
        target = target / part
        if target.is_symlink():
            raise ValueError('The standards file path must not contain symlinks.')
    if not target.exists():
        return None
    if not target.is_file() or root not in target.resolve().parents:
        raise ValueError('The standards path is not a regular file inside the working directory.')
    if target.stat().st_size > MAX_BYTES:
        raise ValueError(f'The standards file is larger than {MAX_BYTES // 1024} KB.')
    raw = target.read_bytes()
    try:
        return raw.decode('utf-8'), hashlib.sha256(raw).hexdigest()
    except UnicodeError:
        raise ValueError('The standards file is not UTF-8.') from None


def inspect(workdir) -> dict:
    """Summary of the working directory's standards: state, property, hash, areas, checks and warnings."""
    base = {'state': 'no_workdir', 'path': FILE, 'property': None, 'sha256': None, 'areas': [], 'checks': [], 'warnings': [],
            'message': 'This project has no working directory, so no standards were read.'}
    if not workdir or not Path(workdir).is_dir():
        return base
    try:
        got = _read(workdir)
    except (ValueError, OSError) as error:
        return {**base, 'state': 'unreadable', 'message': f'{error} Planning continues without the standards.'}
    if got is None:
        return {**base, 'state': 'missing', 'message': f'No {FILE} in this project\'s working directory. Planning continues without standards.'}
    text, digest = got
    warnings: list[str] = []
    title = re.search(r'^#\s+(.+?)\s+engineering standards\s*$', text, re.I | re.M)
    sections = _sections(text)
    areas, checks = [], []
    lines = _find(sections, 'risk by area')
    header, rows = _table(lines) if lines else (None, [])
    if header is None:
        warnings.append('No "Risk by area" table was found.')
    else:
        a, r, t = _column(header, 'area'), _column(header, 'default', 'risk'), _column(header, 'route')
        if a is None or r is None:
            warnings.append('The "Risk by area" table needs "Area" and "Default risk" columns.')
        else:
            for row in rows:
                risk = _risk(row[r]) if r < len(row) else None
                if not risk or a >= len(row) or not row[a]:
                    warnings.append(f'Skipped a risk row it could not read: {" | ".join(row)[:80]}')
                    continue
                areas.append({'area': row[a], 'risk': risk, 'route': row[t] if t is not None and t < len(row) else ''})
    lines = _find(sections, 'definition of done')
    header, rows = _table(lines) if lines else (None, [])
    if header is None:
        warnings.append('No "Definition of done" table was found.')
    else:
        t, run = _column(header, 'touches'), _column(header, 'run')
        if t is None or run is None:
            warnings.append('The "Definition of done" table needs "touches" and "Run" columns.')
        else:
            for row in rows:
                if max(t, run) >= len(row) or not row[t] or not row[run]:
                    warnings.append(f'Skipped a check row it could not read: {" | ".join(row)[:80]}')
                    continue
                checks.append({'touches': row[t], 'run': row[run]})
    if not areas and not checks:
        return {**base, 'state': 'unreadable', 'sha256': digest, 'warnings': warnings,
                'message': 'The standards file was read, but its tables could not be understood. Planning continues without them.'}
    return {**base, 'state': 'ok', 'property': title.group(1).strip().lower() if title else None, 'sha256': digest,
            'areas': areas, 'checks': checks, 'warnings': warnings, 'message': ''}


def summary(workdir) -> dict:
    """What a plan revision records: enough to say which standards it was made under."""
    found = inspect(workdir)
    return {k: found[k] for k in ('state', 'property', 'sha256')} | {'areas': len(found['areas']), 'checks': len(found['checks'])}
