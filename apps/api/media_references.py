"""Reference art the operator uploads for a project: images agents look at for style, kept in <project>/media/references/.

Only images (PNG, JPEG, WebP, GIF) whose bytes match their type, at most REF_MAX bytes each and REF_COUNT per project. Names are
reduced to safe lowercase file names; a clash gets a number, so an upload never replaces another file. Nothing here runs project code."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif'}
REF_MAX = 10 * 1024 * 1024
REF_COUNT = 24
NAME_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,79}$')


class ReferenceError_(ValueError):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def folder(root: Path) -> Path:
    return root / 'media' / 'references'


def _kind(data: bytes) -> str | None:
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return '.png'
    if data[:3] == b'\xff\xd8\xff':
        return '.jpg'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return '.gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return '.webp'
    return None


def _safe_folder(root: Path) -> Path:
    """The references folder, created if needed, refused when any part of it is a link that could lead outside the project."""
    path = folder(root)
    for part in (root / 'media', path):
        if part.is_symlink():
            raise ReferenceError_('The media folder must not be a link.')
    path.mkdir(parents=True, exist_ok=True)
    resolved = path.resolve()
    if root.resolve() not in resolved.parents:
        raise ReferenceError_('The references folder is outside the project.')
    return resolved


def listing(root: Path) -> list[dict]:
    """[{name, size, path}] for the images in the references folder, oldest first. Empty when there is none."""
    path = folder(root)
    if not path.is_dir() or path.is_symlink():
        return []
    rows = [f for f in path.iterdir() if f.is_file() and not f.is_symlink() and f.suffix.lower() in TYPES and NAME_RE.fullmatch(f.name)]
    return [{'name': f.name, 'size': f.stat().st_size, 'path': f'media/references/{f.name}'} for f in sorted(rows, key=lambda f: (f.stat().st_mtime, f.name))]


def file_of(root: Path, name: str) -> Path | None:
    if not NAME_RE.fullmatch(name or '') or Path(name).suffix.lower() not in TYPES:
        return None
    path = folder(root) / name
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    return resolved if resolved.is_file() and not path.is_symlink() and root.resolve() in resolved.parents else None


def save(root: Path, original: str, data: bytes) -> dict:
    """Store one uploaded image under a safe, unused name. Returns its row."""
    if not data:
        raise ReferenceError_('The file is empty.')
    if len(data) > REF_MAX:
        raise ReferenceError_(f'Images can be at most {REF_MAX // (1024 * 1024)} MB.', 413)
    kind = _kind(data)
    if kind is None:
        raise ReferenceError_('Only PNG, JPEG, WebP or GIF images can be used as reference art.')
    if len(listing(root)) >= REF_COUNT:
        raise ReferenceError_(f'A project can hold {REF_COUNT} reference images. Remove one first.', 409)
    target = _safe_folder(root)
    stem = re.sub(r'[^a-z0-9_-]+', '-', Path(original or 'reference').stem.lower()).strip('-_')[:60] or 'reference'
    ext = '.jpg' if kind == '.jpg' else kind
    name, n = f'{stem}{ext}', 2
    while (target / name).exists():
        name, n = f'{stem}-{n}{ext}', n + 1
    with open(target / name, 'xb') as fh:
        fh.write(data)
    return {'name': name, 'size': len(data), 'path': f'media/references/{name}'}


def remove(root: Path, name: str) -> None:
    path = file_of(root, name)
    if path is None:
        raise ReferenceError_('No such reference image.', 404)
    path.unlink()


def context_note(root: Path) -> dict | None:
    """What a story or the planner is told: where the reference images are and what they are for. None without any."""
    rows = listing(root)
    if not rows:
        return None
    return {'folder': str(folder(root)), 'files': [r['path'] for r in rows],
            'use': 'Reference art the operator chose for this project. Look at these images for style: palette, type, mood and composition. '
                   'Treat them as direction, not as assets to copy into the site unless a story says so. A media slot in '
                   'media/slots.json can list them in its "refs" so generated images follow them.'}


def folder_bytes(path: Path, limit: int = 20000) -> int:
    """Bytes in the regular files under a folder (links are not followed; at most `limit` files are counted)."""
    total = 0
    if not path.is_dir() or path.is_symlink():
        return 0
    for n, (dirpath, dirnames, filenames) in enumerate(os.walk(path, followlinks=False)):
        for name in filenames:
            f = Path(dirpath) / name
            try:
                if not f.is_symlink():
                    total += f.stat().st_size
            except OSError:
                pass
            limit -= 1
            if limit <= 0:
                return total
    return total


def usage(root: Path) -> dict:
    """Space a project's media uses (references, generated takes, the whole media folder) and what is left on its disk."""
    media = root / 'media'
    try:
        disk = shutil.disk_usage(root)
        free, total = disk.free, disk.total
    except OSError:
        free = total = None
    return {'references_bytes': folder_bytes(folder(root)), 'candidates_bytes': folder_bytes(media / 'candidates'),
            'media_bytes': folder_bytes(media), 'disk_free_bytes': free, 'disk_total_bytes': total}

