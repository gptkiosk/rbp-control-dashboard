"""Scheduling facts for a project plan: what can run at the same time, how long the longest chain is, and whether two stories that can overlap
touch the same files. Pure functions over the plan's nodes; nothing here reads a database, a repository or a clock.

Only parallel projects use the overlap rules, the critical-path order and the speed-up figures. A serial project (the default) is built one story
at a time in dependency order and none of this applies to it."""
from __future__ import annotations

import re
from functools import lru_cache

from job_envelope import SIZE_HINT_MINUTES

WILDCARD = re.compile(r"[*?\[]")
TOUCH_OK = re.compile(r"^[A-Za-z0-9._/*?\[\]-]{1,120}$")


def estimate(node: dict) -> int:
    """Minutes the plan gives the story, or the size class's hint, or 45."""
    value = node.get("estimate_minutes")
    if isinstance(value, int) and value > 0:
        return value
    return SIZE_HINT_MINUTES.get(node.get("size") or "", 45)


def stories(nodes: list[dict]) -> dict[str, dict]:
    return {n["key"]: n for n in nodes if n.get("kind", "story") == "story"}


def _ancestors(by_key: dict[str, dict]) -> dict[str, set[str]]:
    """For each story, every story it depends on, directly or not."""
    memo: dict[str, set[str]] = {}

    def walk(key: str, seen: frozenset[str]) -> set[str]:
        if key in memo:
            return memo[key]
        out: set[str] = set()
        for dep in by_key[key].get("depends_on") or []:
            if dep in by_key and dep not in seen:
                out |= {dep} | walk(dep, seen | {key})
        memo[key] = out
        return out
    return {k: walk(k, frozenset()) for k in by_key}


def can_overlap(nodes: list[dict]) -> list[tuple[str, str]]:
    """Pairs of stories that no chain of dependencies orders, so the scheduler is free to run them at the same time."""
    by_key = stories(nodes)
    ancestors = _ancestors(by_key)
    keys = sorted(by_key)
    return [(a, b) for i, a in enumerate(keys) for b in keys[i + 1:] if a not in ancestors[b] and b not in ancestors[a]]


def _rank(by_key: dict[str, dict]) -> dict[str, int]:
    """Minutes of the longest chain that starts at each story and runs to the end of the plan (its own time included)."""
    children: dict[str, list[str]] = {k: [] for k in by_key}
    for key, node in by_key.items():
        for dep in node.get("depends_on") or []:
            if dep in children:
                children[dep].append(key)
    memo: dict[str, int] = {}

    def walk(key: str, seen: frozenset[str]) -> int:
        if key in memo:
            return memo[key]
        tail = max((walk(c, seen | {key}) for c in children[key] if c not in seen), default=0)
        memo[key] = estimate(by_key[key]) + tail
        return memo[key]
    return {k: walk(k, frozenset()) for k in by_key}


def critical_order(nodes: list[dict]) -> list[str]:
    """A valid dependency order that starts the longest remaining chain first, so the stories that decide the finish time are never left waiting.
    Ties keep the plan's own order."""
    by_key = stories(nodes)
    rank = _rank(by_key)
    position = {n["key"]: i for i, n in enumerate(nodes)}
    order: list[str] = []
    remaining = set(by_key)
    while remaining:
        ready = [k for k in remaining if all(d in order or d not in by_key for d in by_key[k].get("depends_on") or [])]
        if not ready:
            raise ValueError("Story dependencies contain a cycle.")
        ready.sort(key=lambda k: (-rank[k], position[k]))
        order.append(ready[0])
        remaining.discard(ready[0])
    return order


def stats(nodes: list[dict]) -> dict:
    """The plan's best case: total minutes if one story ran at a time, the longest chain, the speed-up that gap allows, and how many stories
    could be running together at the widest point of an as-early-as-possible schedule."""
    by_key = stories(nodes)
    if not by_key:
        return {"stories": 0, "total_minutes": 0, "critical_minutes": 0, "speedup": 1.0, "width": 0, "critical_path": []}
    rank = _rank(by_key)
    start: dict[str, int] = {}
    for key in critical_order(nodes):
        start[key] = max((start[d] + estimate(by_key[d]) for d in by_key[key].get("depends_on") or [] if d in start), default=0)
    total = sum(estimate(n) for n in by_key.values())
    critical = max(start[k] + estimate(by_key[k]) for k in by_key)
    events = sorted([(start[k], 1) for k in by_key] + [(start[k] + estimate(by_key[k]), -1) for k in by_key], key=lambda e: (e[0], e[1]))
    width = running = 0
    for _, delta in events:
        running += delta
        width = max(width, running)
    # the chain itself: from the story with the largest rank, always step to the child with the largest rank
    path: list[str] = []
    children: dict[str, list[str]] = {k: [] for k in by_key}
    for key, node in by_key.items():
        for dep in node.get("depends_on") or []:
            if dep in children:
                children[dep].append(key)
    heads = [k for k in by_key if not any(d in by_key for d in by_key[k].get("depends_on") or [])]
    current = max(heads, key=lambda k: (rank[k], -sorted(by_key).index(k))) if heads else None
    while current:
        path.append(current)
        current = max(children[current], key=lambda k: (rank[k], -sorted(by_key).index(k)), default=None)
    return {"stories": len(by_key), "total_minutes": total, "critical_minutes": critical, "speedup": round(total / critical, 2) if critical else 1.0,
            "width": width, "critical_path": path}


# ----------------------------------------------------------------------------- touches (which files a story may change)
def _prefix(pattern: str) -> list[str]:
    """The folder segments a pattern is rooted in: everything before its first wildcard, without a trailing file name that carries one."""
    text = pattern.strip().lstrip("./").rstrip("/")
    segments = [s for s in text.split("/") if s]
    out: list[str] = []
    for segment in segments:
        if WILDCARD.search(segment):
            break
        out.append(segment)
    return out


def touches_overlap(a: str, b: str) -> bool:
    """Whether two patterns can name the same file: one is rooted at, or inside, the other (an empty root, such as `**`, covers everything)."""
    pa, pb = _prefix(a), _prefix(b)
    n = min(len(pa), len(pb))
    return pa[:n] == pb[:n]


@lru_cache(maxsize=256)
def _glob(pattern: str) -> re.Pattern[str]:
    """A glob as a regular expression: `*` and `?` stay inside one folder, `**` crosses folders, `[...]` is a character class."""
    out, i = "", 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"; i += 3; continue
        if c == "*" and pattern.startswith("**", i):
            out += ".*"; i += 2; continue
        if c == "*":
            out += "[^/]*"
        elif c == "?":
            out += "[^/]"
        elif c == "[":
            j = pattern.find("]", i + 1)
            if j == -1:
                out += re.escape(c)
            else:
                out += "[" + pattern[i + 1:j].replace("\\", "\\\\") + "]"; i = j
        else:
            out += re.escape(c)
        i += 1
    return re.compile(out)


def path_matches(path: str, pattern: str) -> bool:
    """Whether a changed file falls under a pattern: a folder or file prefix, or a glob."""
    path = path.lstrip("./")
    text = pattern.strip().lstrip("./")
    if WILDCARD.search(text):
        return _glob(text).fullmatch(path) is not None
    text = text.rstrip("/")
    return path == text or path.startswith(text + "/")


def inside_touches(files: list[str], touches: list[str]) -> bool:
    """Every changed file is under one of the story's declared patterns. A story with no declared patterns is never inside."""
    return bool(touches) and all(any(path_matches(f, t) for t in touches) for f in files)


def overlap_problems(nodes: list[dict], limit: int = 8) -> list[str]:
    """Sentences for pairs of stories that may run together and are not safely apart: an edit story that names no files, or two that name the
    same ones. Human stories and read-only stories change nothing, so they never conflict."""
    by_key = stories(nodes)
    editing = {k for k, n in by_key.items() if n.get("assignee") != "human" and n.get("mode") == "edit"}
    problems: list[str] = []
    missing = sorted(k for k in editing if not by_key[k].get("touches"))
    pairs = [(a, b) for a, b in can_overlap(nodes) if a in editing and b in editing]
    needs = {k for pair in pairs for k in pair}
    for key in missing:
        if key in needs:
            problems.append(f"{key}: can run alongside other editing stories, so it must list the files or folders it changes (touches)")
    for a, b in pairs:
        if a in missing or b in missing:
            continue
        clash = next(((x, y) for x in by_key[a]["touches"] for y in by_key[b]["touches"] if touches_overlap(x, y)), None)
        if clash:
            problems.append(f"{a} and {b} can run at the same time but both change {clash[0]} and {clash[1]}: make one depend on the other or split their files")
    return problems[:limit]
