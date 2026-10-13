from types import SimpleNamespace
from pathlib import Path
import pytest
from fastapi import HTTPException
import project_outputs

@pytest.fixture
def settings(tmp_path):
    root=tmp_path/'private';root.mkdir()
    return SimpleNamespace(data_dir=root)

def test_output_writer_never_follows_symlink_or_overwrites(settings,tmp_path):
    outside=tmp_path/'outside';outside.mkdir()
    link=settings.data_dir/'project-outputs';link.symlink_to(outside,target_is_directory=True)
    with pytest.raises(HTTPException): project_outputs.save(settings,1,5,7,'inventory','document')
    assert not list(outside.iterdir());link.unlink()
    path=project_outputs.save(settings,1,5,7,'inventory','document')
    assert project_outputs.save(settings,1,5,7,'inventory','document')==path
    with pytest.raises(HTTPException): project_outputs.save(settings,1,5,7,'inventory','changed')
    assert path.read_text()=='document'
    secret=tmp_path/'secret';secret.write_text('never read')
    path.unlink();path.symlink_to(secret)
    with pytest.raises(HTTPException): project_outputs.read(settings,1,5,7,'inventory')
    with pytest.raises(HTTPException): project_outputs.save(settings,1,5,7,'inventory','changed')
    assert secret.read_text()=='never read'

@pytest.mark.parametrize('key',['../escape','nested/file','', '/absolute'])
def test_output_names_cannot_be_paths(settings,key):
    with pytest.raises(HTTPException): project_outputs.save(settings,1,5,7,key,'document')
    assert not (settings.data_dir/'project-outputs').exists()

def test_non_markdown_blank_or_oversized_result_is_rejected(settings):
    for markdown in (' ', '💙'*100000):
        with pytest.raises(HTTPException): project_outputs.save(settings,1,5,7,'inventory',markdown)
    assert not (settings.data_dir/'project-outputs').exists()
    with pytest.raises(Exception): project_outputs.parse('{"markdown":"ok","handoff":"done","path":"untrusted"}')
