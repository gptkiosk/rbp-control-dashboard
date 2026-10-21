"""Pause the projects in progress so a dashboard update can run, and resume exactly those afterwards.

An update waits while any project is in progress (update_engine.drain_blockers). Instead of leaving the operator to find and pause
each one, the Updates panel offers one confirmed action. The ids it paused are remembered in the data folder, so the resume offer
survives the update's restart and works from any device. Only projects still paused are resumed; one the operator resumed or
closed in the meantime is left alone."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

FILE = 'paused-for-update.json'


def _path(settings) -> Path:
    return Path(settings.data_dir) / FILE


def _remembered(settings) -> list[int]:
    try:
        value = json.loads(_path(settings).read_text())
        return [int(i) for i in value.get('project_ids', [])]
    except (OSError, ValueError, TypeError, AttributeError):
        return []


def _remember(settings, ids: list[int]) -> None:
    path = _path(settings)
    if not ids:
        path.unlink(missing_ok=True)
        return
    path.write_text(json.dumps({'project_ids': ids}))


def _row(p):
    import projects
    return {'id': p.id, 'title': projects.document(p).get('title', f'Project {p.id}'), 'state': p.state}


def in_progress(s) -> list[dict]:
    """Projects an update waits for: dispatching or active."""
    from models import Project
    return [_row(p) for p in s.scalars(select(Project).where(Project.state.in_(['dispatching', 'active'])).order_by(Project.id))]


def paused_for_update(s, settings) -> list[dict]:
    """Projects this action paused that are still paused, so they can be resumed."""
    from models import Project
    ids = _remembered(settings)
    return [_row(p) for p in (s.get(Project, i) for i in ids) if p is not None and p.state == 'paused']


def pause_all(s, settings, actor) -> list[dict]:
    """Pause every active project (a dispatching one finishes starting first and is reported, not paused). Running stories may finish."""
    import projects
    from models import Project
    paused = []
    for p in s.scalars(select(Project).where(Project.state == 'active')):
        p.state = 'paused'
        projects.memory(s, p, 'decision', 'Dispatch paused for a dashboard update; running stories may finish in Review. No new story starts until it is resumed.', actor)
        paused.append(p.id)
    _remember(settings, sorted(set(_remembered(settings)) | set(paused)))
    s.commit()
    return [_row(s.get(Project, i)) for i in paused]


def resume_all(s, settings, actor) -> list[dict]:
    import projects
    from models import Project
    resumed = []
    for i in _remembered(settings):
        p = s.get(Project, i)
        if p is not None and p.state == 'paused':
            p.state = 'active'
            projects.memory(s, p, 'decision', 'Resumed after the dashboard update: the same approved project revision.', actor)
            resumed.append(p.id)
    _remember(settings, [])
    s.commit()
    return [_row(s.get(Project, i)) for i in resumed]
