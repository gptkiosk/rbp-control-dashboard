"""Operator edits of ungenerated media slots. No provider call and no asset/path contract change."""
import hashlib
import json
import os
import tempfile
from pathlib import Path

import media_generate as mg
import media_state

EDIT_FIELDS = {'prompt', 'purpose', 'world', 'width', 'height', 'resolution', 'seconds'}


def digest(root):
    path = mg.inside(root, 'media/slots.json')
    return hashlib.sha256(path.read_bytes()).hexdigest() if path else None


def update(root, name, expected, changes, jobs):
    raw_path = root / 'media/slots.json'
    path = mg.inside(root, 'media/slots.json')
    if not path or raw_path.is_symlink() or raw_path.parent.is_symlink():
        raise mg.MediaError('The media inventory must be a regular project file.')
    if not changes or not set(changes) <= EDIT_FIELDS:
        raise mg.MediaError('Edit only prompt, purpose, world, dimensions, resolution or duration. Asset names, types and references need a reviewed inventory amendment.')
    before = path.read_bytes()
    if hashlib.sha256(before).hexdigest() != expected:
        raise mg.MediaError('The media plan changed. Refresh and review its current values before saving.', 409)
    slots = mg.load_slots(root)
    slot = slots.get(name)
    if not slot: raise mg.MediaError('Unknown media slot.')
    candidates = root / 'media/candidates'
    waiting = candidates.is_dir() and any(mg.candidate_of(name, p.name) for p in candidates.iterdir())
    if mg.is_published(root, slot) or waiting or jobs.active_for(root, name):
        raise mg.MediaError('This slot has generated, published or running work. Review it first; editing a paid take requires an explicit new inventory/retry decision.', 409)
    proposed = {**slot, **changes}
    if 'resolution' in changes and changes['resolution'] is None: proposed.pop('resolution',None)
    if not str(proposed.get('prompt', '')).strip(): raise mg.MediaError('Write an asset prompt.')
    resolution = proposed.get('resolution')
    if resolution and resolution not in (mg.IMAGE_RESOLUTIONS if slot['kind']=='image' else mg.VIDEO_RESOLUTIONS):
        raise mg.MediaError('Choose a resolution supported by this media kind.')
    seconds = proposed.get('seconds')
    if seconds is not None and (slot['kind'] != 'video' or len(seconds) != 2 or seconds[0] > seconds[1]):
        raise mg.MediaError('Video duration needs a valid minimum and maximum.')
    data = json.loads(before)
    data['slots'] = [proposed if item['name'] == name else item for item in data['slots']]
    encoded = (json.dumps(data, indent=2, ensure_ascii=False) + '\n').encode()
    if len(encoded) > mg.MAX_SLOTS_FILE: raise mg.MediaError('The media inventory is too large.')
    # Preserve every unedited slot and metadata. Compare again before atomic replacement.
    if path.read_bytes() != before: raise mg.MediaError('The media plan changed. Refresh first.', 409)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            tmp = Path(stream.name); stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
        os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    finally:
        if tmp and tmp.exists(): tmp.unlink()
    media_state.record(root, name, 'plan_edited', 'Ungenerated prompt/sizing updated; no generation or spend approved.')
    return {'slot': name, 'plan_sha256': hashlib.sha256(encoded).hexdigest(), 'changed': sorted(changes)}


def require_evidence(root, stage):
    slots=mg.load_slots(root)
    required=[slot for slot in slots.values() if slot.get('required',True)]
    if not required: raise mg.MediaError('The media inventory has no required assets to verify. Review the illustrated scope before approval.')
    missing=[]
    for slot in required:
        if mg.is_published(root,slot): continue
        candidates=root/'media/candidates'
        made=candidates.is_dir() and any(mg.candidate_of(slot['name'],p.name) and p.is_file() and not p.is_symlink() and p.stat().st_size>0 for p in candidates.iterdir())
        if stage=='publish' or not made: missing.append(slot['name'])
    if missing: raise mg.MediaError('Finish dashboard media '+('generation' if stage=='generate' else 'publication')+' for required slots before accepting this story: '+', '.join(missing[:12]),409)
