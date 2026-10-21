"""Reference art: the operator uploads images to a project's media/references/, and the planner and every story are told where they are."""
from __future__ import annotations

import pytest

import media_references as refs
from tests.test_auth import begin, complete, secured  # noqa: F401
from tests.test_profiles import signed

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 64


@pytest.fixture
def env(tmp_path, secured):  # noqa: F811
    folder = tmp_path / 'ws' / 'site'
    folder.mkdir(parents=True)
    signed(secured)
    return secured, folder


def upload(c, folder, name, data, ctype='image/png'):
    return c.post('/api/media/references', params={'working_dir': str(folder), 'name': name}, content=data, headers={'Content-Type': ctype})


def test_upload_list_show_and_remove(env):
    c, folder = env
    first = upload(c, folder, 'Perfect World (light).PNG', PNG)
    assert first.status_code == 201, first.text
    assert first.json()['path'] == 'media/references/perfect-world-light.png'
    assert upload(c, folder, 'Perfect World (light).png', PNG).json()['name'] == 'perfect-world-light-2.png'   # never replaces another file
    assert upload(c, folder, 'stitches.jpeg', JPEG, 'image/jpeg').json()['name'] == 'stitches.jpg'
    listed = c.get('/api/media/references', params={'working_dir': str(folder)}).json()['references']
    assert [r['name'] for r in listed] == ['perfect-world-light.png', 'perfect-world-light-2.png', 'stitches.jpg']
    shown = c.get('/api/media/reference', params={'working_dir': str(folder), 'name': 'stitches.jpg'})
    assert shown.status_code == 200 and shown.headers['content-type'] == 'image/jpeg' and shown.content == JPEG
    left = c.post('/api/media/references/remove', json={'working_dir': str(folder), 'name': 'perfect-world-light-2.png'}).json()['references']
    assert len(left) == 2 and not (folder / 'media/references/perfect-world-light-2.png').exists()


def test_only_real_images_inside_allowed_folders_are_accepted(env, tmp_path, monkeypatch):
    c, folder = env
    assert upload(c, folder, 'evil.png', b'<?php echo 1; ?>').status_code == 422          # the bytes decide, not the name
    assert upload(c, folder, 'x.png', b'').status_code == 422
    monkeypatch.setattr(refs, 'REF_MAX', 32)
    assert upload(c, folder, 'big.png', PNG).status_code == 413
    outside = tmp_path / 'elsewhere'; outside.mkdir()
    assert upload(c, outside, 'a.png', PNG).status_code in (403, 422)
    assert c.get('/api/media/reference', params={'working_dir': str(folder), 'name': '../../etc/passwd'}).status_code == 404


def test_the_planner_and_stories_are_told_where_the_references_are(env):
    c, folder = env
    upload(c, folder, 'mood.png', PNG)
    note = refs.context_note(folder)
    assert note['files'] == ['media/references/mood.png'] and 'style' in note['use']
    import projects
    assert projects._reference_art({'working_dir': str(folder)})['files'] == ['media/references/mood.png']
    assert projects._reference_art({'working_dir': str(folder / 'none')}) is None


def test_space_use_is_reported_for_the_project_and_the_disk(env):
    c, folder = env
    upload(c, folder, 'mood.png', PNG)
    (folder / 'media' / 'candidates').mkdir(parents=True)
    (folder / 'media' / 'candidates' / 'hero-1.jpg').write_bytes(b'x' * 1000)
    use = c.get('/api/media/references', params={'working_dir': str(folder)}).json()['usage']
    assert use['references_bytes'] == len(PNG) and use['candidates_bytes'] == 1000 and use['media_bytes'] == len(PNG) + 1000
    assert use['disk_free_bytes'] > 0 and use['disk_total_bytes'] >= use['disk_free_bytes']
    store = c.get('/api/media/storage').json()
    assert store['disk']['free_bytes'] > 0 and isinstance(store['projects'], list)
