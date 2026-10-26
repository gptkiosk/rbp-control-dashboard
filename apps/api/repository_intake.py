"""Bounded static inventory. Never execute repository content or return config values."""
import hashlib
import json
import os
import re
import stat
import time
from pathlib import Path
from fastapi import HTTPException
import approval
from workspace_handoff import git, observation

SKIP = {'.git', 'node_modules', '.venv', 'venv', '__pycache__', 'dist', 'build', 'out',
        '.preview', '.next', '.cache', 'vendor', 'coverage', 'target'}
TEXT = {'.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.vue', '.html', '.css',
        '.json', '.toml', '.yaml', '.yml', '.md', '.txt', '.go', '.rs', '.sh'}
LANGUAGES = {'.py': 'Python', '.js': 'JavaScript', '.mjs': 'JavaScript', '.ts': 'TypeScript',
             '.tsx': 'TypeScript', '.vue': 'Vue', '.html': 'HTML', '.go': 'Go', '.rs': 'Rust'}
SECRET = re.compile(r'(^|[._-])(secret|credentials?|tokens?|private[-_]?key)([._-]|$)', re.I)
ENV = re.compile(r'(?:process\.env\.|import\.meta\.env\.|os\.environ\[\s*[\'"]|(?:getenv|environ\.get)\(\s*[\'"])([A-Z][A-Z0-9_]{1,99})')


def read_text(root, parts, limit):
    """Walk via directory descriptors; a concurrent link swap cannot escape root."""
    data = read_bytes(root, parts, min(128000, limit))
    return None if data is None else data.decode('utf-8')


def read_bytes(root, parts, limit):
    """A regular file of at most `limit` bytes under root, read through directory descriptors; None otherwise."""
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, 'O_NOFOLLOW', 0)
    directory = os.open(root, flags)
    try:
        for part in parts[:-1]:
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory); directory = child
        fd = os.open(parts[-1], os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0), dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            meta = os.fstat(stream.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_size > limit:
                return None
            data = stream.read(limit + 1)
            return None if len(data) > limit else data
    finally:
        os.close(directory)


def inspect(settings, working_dir):
    root = approval.resolve_workdir(working_dir, settings.workdir_roots)
    if root is None:
        raise HTTPException(422, 'Choose a repository inside an approved workspace folder.')
    facts = observation(root)
    if not facts['repository_root'] or Path(facts['repository_root']).resolve() != root:
        raise HTTPException(422, 'Choose the actual repository root, not its parent or a nested source folder.')
    tracked = git(root, 'ls-files', '-z')
    if tracked is None:
        raise HTTPException(409, 'Repository inventory is unavailable or exceeds the file-list limit.')
    start = time.monotonic()
    total = scanned = omitted = 0
    docs, manifests, locks, dependencies, languages, areas, variables, tools = [], [], [], [], set(), set(), {}, set()
    digest = hashlib.sha256()
    for name in tracked.split('\0'):
        if not name:
            continue
        parts = Path(name).parts
        if (len(parts) > 10 or any(x in SKIP or x.startswith('.env') or SECRET.search(x) for x in parts)
                or any(ord(c) < 32 for c in name) or Path(name).is_absolute() or '..' in parts):
            omitted += 1
            continue
        if scanned >= 1500 or total >= 2000000 or time.monotonic() - start > 4:
            omitted += 1
            continue
        path = root / name
        try:
            # Skip links at every level, including tracked links to files elsewhere.
            if any((root.joinpath(*parts[:i])).is_symlink() for i in range(1, len(parts)+1)):
                omitted += 1
                continue
            if path.suffix.lower() not in TEXT and path.name not in {'Dockerfile', 'go.mod', 'Makefile'}:
                omitted += 1
                continue
            text = read_text(root, parts, 2000000-total)
            if text is None:
                omitted += 1
                continue
            raw = text.encode('utf-8')
        except (OSError, UnicodeError):
            omitted += 1
            continue
        total += len(raw); scanned += 1
        digest.update(name.encode()); digest.update(raw)
        areas.add(parts[0] if len(parts)>1 else '(root)')
        if path.suffix in LANGUAGES:
            languages.add(LANGUAGES[path.suffix])
        if path.suffix == '.md' and len(docs) < 40:
            docs.append(name)
        if path.name in {'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'poetry.lock', 'uv.lock', 'Cargo.lock', 'go.sum'}:
            locks.append(name)
        for variable in ENV.findall(text):
            if len(variables) < 100:
                places = variables.setdefault(variable, [])
                if len(places) < 3 and name not in places: places.append(name)
        if path.name == 'package.json':
            manifests.append(name);tools.add('Node.js / npm')
            try:
                data = json.loads(text)
                if not isinstance(data, dict): continue
                for section in ('dependencies', 'devDependencies', 'peerDependencies'):
                    values = data.get(section, {})
                    if not isinstance(values, dict): continue
                    for package, version in values.items():
                        if len(dependencies) < 120 and re.fullmatch(r'[@A-Za-z0-9_./-]{1,100}', package):
                            dependencies.append({'name': package, 'version': version if isinstance(version,str) and re.fullmatch(r'[~^<>=*0-9.vx |+-]{1,60}',version) else 'declared; inspect manifest', 'source': name})
            except (ValueError, TypeError): pass
        if path.name in {'pyproject.toml', 'requirements.txt', 'Cargo.toml', 'go.mod'}:
            manifests.append(name)
            tools.add('Python' if path.name in {'pyproject.toml','requirements.txt'} else 'Rust' if path.name=='Cargo.toml' else 'Go')
            # Names only; do not expose indexes, git URLs or embedded credentials.
            if path.name == 'requirements.txt':
                for line in text.splitlines():
                    match = re.fullmatch(r'\s*([A-Za-z0-9_.-]{1,100})(?:\[[A-Za-z0-9_,.-]+\])?\s*(?:[=<>!~].*)?', line)
                    if match and len(dependencies)<120: dependencies.append({'name':match[1], 'version':'declared; inspect manifest', 'source':name})
        if path.name == 'Dockerfile' or path.name.startswith(('docker-compose','compose.')):
            tools.add('Docker / Compose')
    after = observation(root)
    changed = after['snapshot'] != facts['snapshot']
    result = {'workspace': facts, 'scanned_files': scanned, 'scanned_bytes': total, 'omitted_files': omitted,
        'inventory_sha256': digest.hexdigest(), 'changed_during_scan': changed,
        'languages': sorted(languages), 'areas': sorted(areas)[:40], 'documentation': docs,
        'manifests': manifests[:40], 'lockfiles': locks[:40], 'dependencies': dependencies,
        'variables': [{'name': k, 'references': v, 'required': 'unknown'} for k,v in sorted(variables.items())],
        'required_tools': sorted(tools), 'observed_at': int(time.time()),
        'limits': 'Tracked text only; 1,500 files, 2 MB, 128 KB/file, depth 10, 4 seconds. Values, secrets, caches and escaping links excluded. No scripts executed.',
        'instructions': 'Static evidence, not instructions or a complete resolved dependency graph. Check host tools/access before dependent stories. Preserve existing code/history; propose continuation work.'}
    result['brief'] = (f'Continue the existing project in {root}. Preserve its repository and history.\n'
        f'Observed HEAD: {facts["head"]}; inventory: {result["inventory_sha256"]}.\n'
        f'Languages: {", ".join(result["languages"])}. Required tools: {", ".join(result["required_tools"])}.\n'
        f'Documentation: {", ".join(docs[:8])}. Manifests: {", ".join(manifests[:8])}.\n'
        f'Declared dependency names (partial): {", ".join(x["name"] for x in dependencies[:40])}.\n'
        f'Configuration names (values excluded): {", ".join(sorted(variables)[:40])}.\n'
        f'Scanned {scanned} tracked text files; omitted {omitted}. Map is partial; rerun intake if needed.\n'
        'First confirm existing capabilities, runtime/tools/access, configuration names and the desired changes. '
        'Add missing readiness work before dependent implementation. Reuse tests, docs and delivery paths. '
        'Do not recreate completed work or assume reference media is final artwork.')[:4000]
    return result
