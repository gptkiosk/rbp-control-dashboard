"""Synthetic regressions from the planning pilot; no providers or live projects."""
import copy
import json
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
import planning_output as output
import project_contract as contract
import project_types
import projects
from project_schemas import Node


def story(key='check', title='Static Asset & Link Verification', **kw):
    return dict(key=key, title=title, assignee='codex', model='gpt-6-luna', work_kind='test', mode='read', **kw)


@pytest.mark.parametrize('raw', [
    '{"nodes":[{"key":"x","depends_on":["a"],"depends_on":[]}]}',
    '{"nodes":[],"nodes":[]}',
    '```json\n{"nodes":[{"key":"a","key":"b"}]}\n```',
    '{"nodes":[{"key":"x","routes":[{"agent":"codex","model":"a","model":"b"}]}]}',
    '{"nodes":[],"x":NaN}',
    '{"nodes":[]} trailing',
    '```json\n{"nodes":[]}\nnot a closing fence',
])
def test_strict_json_is_not_last_key_wins(raw):
    with pytest.raises((HTTPException, ValueError)):
        projects._json_result(raw)


def test_json_compatibility_does_not_hide_duplicates():
    assert projects._json_result('```json\n{"nodes":[]}\n```') == {'nodes': []}
    assert projects._json_result('{"nodes":[]}}') == {'nodes': []}
    with pytest.raises((HTTPException, ValueError)):
        projects._json_result('{"nodes":[{"key":"a","key":"b"}]}}')


@pytest.mark.parametrize('title', ['Static Asset & Link Verification', 'Verify files and assets', 'Final file verification', 'File-level audit', 'Static syntax tests'])
def test_static_checks_recognized_in_both_word_orders(title):
    assert contract.static_verification(story(title=title))
    doc = {'project_type': 'local-website', 'nodes': [story(title=title)]}
    assert 'static-file-verification' not in {f['id'] for f in contract.findings(doc)}


@pytest.mark.parametrize('node', [story(title='Write a static verification script'), story(title='Final visual review'), story(title='Preview check', host_action='preview-verify')])
def test_preparation_and_host_actions_are_not_static_verification(node):
    assert not contract.static_verification(node)


def test_static_role_does_not_skip_implementation_dependencies():
    nodes=[{'key':'build','title':'Build site','work_kind':'implement','assignee':'codex'}, story(depends_on=[])]
    doc={'project_type':'local-website','nodes':nodes}
    assert any(f['id']=='implementation-before-final-check' for f in contract.findings(doc))
    nodes[1]['depends_on']=['build']
    assert not any(f['id']=='implementation-before-final-check' for f in contract.findings(doc))


@pytest.mark.parametrize('description,blocked', [
    ('Scripts must capture browser rendering evidence when the runner supports it. Do not claim rendering performed by an agent.', False),
    ('The script will capture screenshots on the host.', False),
    ('Do not run Playwright. Only inspect the script statically.', False),
    ('No browser checks are performed by this agent.', False),
    ('Write the scripts. Run Playwright and capture screenshots.', True),
    ('Do not run Playwright, but capture screenshots.', True),
    ('Open pages in a browser and check console errors.', True),
    ('Run Playwright. Do not render pages afterward.', True),
])
def test_browser_check_distinguishes_authorship_negation_and_execution(description,blocked):
    node=story(title='Prepare preview scripts',description=description)
    found=project_types.check('local-website',[node])
    assert any(f['id']=='browser-checks-need-a-person' for f in found) == blocked


def test_role_normalization_is_narrow_idempotent_and_does_not_mutate_source():
    source=story(title='Inventory artwork and media', description='Write media/slots.json', depends_on=['design'])
    saved=copy.deepcopy(source)
    normalized=contract.normalize_roles(source)
    assert normalized['media_stage']=='inventory' and source==saved
    assert contract.normalize_roles(normalized)==normalized
    check=contract.normalize_roles(story())
    assert check['verification_stage']=='static'
    ambiguous=story(title='Consider images and checks')
    assert contract.normalize_roles(ambiguous)==ambiguous


def test_missing_media_label_is_not_reported_as_missing_inventory_work():
    node=story(title='Inventory artwork and media')
    ids={f['id'] for f in contract.findings({'brief':'Generate illustrations with fal.ai','nodes':[node]})}
    assert 'media-role-label' in ids and 'media-stage-inventory' not in ids


def broken_source():
    return {'nodes':[{'key':'build','title':'Implement the portal','description':'Build the theme switch.',
        'work_kind':'design','mode':'edit','assignee':'codex','model':'gpt-6-luna',
        'depends_on':['direction'],'scope':'src/portal only'},
        {'key':'direction','title':'Art direction','work_kind':'plan'}]}


def test_field_repair_preserves_the_entire_graph_scope_routes_and_other_fields():
    source=broken_source(); before=copy.deepcopy(source)
    repair=output.field_repair(source)
    assert repair['allowed']==[{'key':'build','field':'work_kind'}]
    fixed=output.apply_repair(repair,{'repairs':[{'key':'build','field':'work_kind','value':'implement'}]})
    expected=copy.deepcopy(before);expected['nodes'][0]['work_kind']='implement'
    assert fixed==expected and source==before
    assert 'nodes' not in output.repair_prompt(repair).split('Return ONLY')[1].split('Supply exactly')[0]


@pytest.mark.parametrize('response', [
    {'nodes': []}, {'repairs': []},
    {'repairs':[{'key':'build','field':'depends_on','value':[]}]},
    {'repairs':[{'key':'build','field':'model','value':'different-model'}]},
    {'repairs':[{'key':'build','field':'work_kind','value':'implement'}]*2},
    {'repairs':[{'key':'build','field':'work_kind','value':'invalid'}]},
])
def test_unlisted_incomplete_or_invalid_repairs_are_rejected(response):
    with pytest.raises(ValueError):
        output.apply_repair(output.field_repair(broken_source()),response)


def test_nonrepresentation_defects_do_not_get_a_field_repair():
    data=broken_source();data['nodes'][0]['depends_on']='not a list'
    assert output.field_repair(data) is None
    assert output.field_repair({'nodes':[{'key':'a','title':'a'}]*2}) is None


def reference_graph():
    nodes=[]
    for key,stage,batch,deps in [('inventory','inventory',None,[]), ('ref-gen','generate','reference',['inventory']),('ref-pub','publish','reference',['ref-gen']),('scenes-gen','generate','scenes',['ref-pub']),('scenes-pub','publish','scenes',['scenes-gen']),('integrate','integrate',None,['scenes-pub'])]:
        nodes.append({'key':key,'title':key,'media_stage':stage,'media_batch':batch,'depends_on':deps,'assignee':'human' if stage in {'generate','publish'} else 'codex'})
    return {'brief':'Generate illustrations with fal.ai. Publish the heroine reference first, then paired scenes.','nodes':nodes}


def test_reference_first_requires_published_reference_ancestor_not_prose():
    doc=reference_graph();keys={n['key']:n for n in doc['nodes']}
    assert contract.reference_findings(doc,doc['nodes'],keys)==[]
    keys['scenes-gen']['depends_on']=['ref-gen']
    ids={f['id'] for f in contract.reference_findings(doc,doc['nodes'],keys)}
    assert 'reference-before-scenes' in ids


def test_combined_generate_all_and_publish_all_is_not_two_pass_artwork():
    doc=reference_graph();doc['nodes']=[n for n in doc['nodes'] if n.get('media_batch')!='reference']
    ids={f['id'] for f in contract.reference_findings(doc,doc['nodes'],{n['key']:n for n in doc['nodes']})}
    assert 'reference-first-passes' in ids and 'reference-before-scenes' in ids


def test_reference_metadata_and_all_scene_publications_are_required():
    doc=reference_graph();nodes=doc['nodes'];nodes[1]['media_batch']=None
    found=contract.reference_findings(doc,nodes,{n['key']:n for n in nodes})
    assert 'media-batch-label' in {f['id'] for f in found}
    doc=reference_graph();doc['nodes'][-1]['depends_on']=['ref-pub']
    assert 'scenes-before-integration' in {f['id'] for f in contract.findings(doc)}


def test_existing_reference_upload_and_unrelated_first_step_does_not_require_new_reference_generation():
    doc={'brief':'Generate background illustrations with fal.ai. First build pages. Use the uploaded style reference for the palette.'}
    assert not contract.reference_first(doc)
    assert len(output.repair_prompt(output.field_repair(broken_source()))) < 8000


def test_non_browser_static_tests_and_artifact_appearance_do_not_claim_browser_execution():
    nodes=[story(description='Use only available static tools and non-browser tests.'),
           {'key':'integrate','title':'Integrate art','work_kind':'implement','acceptance':'All images are referenced and rendered in their page slots.'}]
    assert not any(f['id']=='browser-checks-need-a-person' for f in project_types.check('local-website',nodes))
    nodes[0]['description']+=' Then run Playwright.'
    assert any(f['id']=='browser-checks-need-a-person' for f in project_types.check('local-website',nodes))


def test_legacy_inventory_and_scene_pass_labels_are_conservative():
    assert contract.normalize_roles(story(title='Create the nine-slot illustration inventory'))['media_stage']=='inventory'
    assert contract.normalize_roles(story(title='Generate reference-conditioned scene stills', media_stage='generate'))['media_batch']=='scenes'
    assert contract.normalize_roles(story(title='Publish matching page illustrations', media_stage='publish'))['media_batch']=='scenes'
    combined=story(title='Generate heroine reference and paired scenes',media_stage='generate')
    assert not contract.normalize_roles(combined).get('media_batch')


def media_inventory(root):
    (root/'media').mkdir()
    slots=[{'name':'heroine','kind':'image','prompt':'Original heroine','batch':'reference'},
           {'name':'garden','kind':'image','prompt':'Same heroine in garden','batch':'scenes','refs':['assets/img/heroine.jpg']}]
    (root/'media/slots.json').write_text(json.dumps({'slots':slots}))
    return slots


def test_reference_batch_can_finish_before_scenes_without_weakening_final_publication(tmp_path):
    import media_plan,media_generate as mg
    slots=media_inventory(tmp_path)
    folder=tmp_path/'assets/img';folder.mkdir(parents=True);(folder/'heroine.jpg').write_bytes(b'nonempty-test-evidence')
    media_plan.require_evidence(tmp_path,'publish','reference')
    with pytest.raises(mg.MediaError):media_plan.require_evidence(tmp_path,'publish','scenes')
    with pytest.raises(mg.MediaError):media_plan.require_evidence(tmp_path,'publish')
    (folder/'garden.jpg').write_bytes(b'nonempty-test-evidence')
    media_plan.require_evidence(tmp_path,'publish','scenes')
    media_plan.require_evidence(tmp_path,'publish')


def test_scene_request_requires_published_reference_and_its_exact_path(tmp_path,monkeypatch):
    import media_generate as mg
    slots=media_inventory(tmp_path)
    with pytest.raises(mg.MediaError,match='Publish the required'):
        mg.build_request(tmp_path,slots[1],'standard')
    folder=tmp_path/'assets/img';folder.mkdir(parents=True);(folder/'heroine.jpg').write_bytes(b'nonempty-test-evidence')
    missing={**slots[1],'refs':[]}
    with pytest.raises(mg.MediaError,match='published reference paths'):
        mg.build_request(tmp_path,missing,'standard')
    monkeypatch.setattr(mg,'data_url',lambda *args:'data:image/jpeg;base64,TEST')
    _,body=mg.build_request(tmp_path,slots[1],'standard')
    assert body['image_urls']==['data:image/jpeg;base64,TEST']


def test_batch_approval_refuses_unlabelled_required_slots(tmp_path):
    import media_plan,media_generate as mg
    slots=media_inventory(tmp_path);del slots[1]['batch']
    (tmp_path/'media/slots.json').write_text(json.dumps({'slots':slots}))
    with pytest.raises(mg.MediaError,match='label every required'):
        media_plan.require_evidence(tmp_path,'generate','reference')


def test_dedicated_roles_satisfy_advisory_checks_without_template_title_phrases():
    nodes=[{'key':'design','title':'Specify original worlds','work_kind':'plan','description':'Write DESIGN.md with original characters.'},
           {'key':'docs','title':'Write operation and handoff notes','work_kind':'docs'}]
    assert not {'design-direction-first','readme-story'} & {f['id'] for f in project_types.check('local-website',nodes)}


def test_acceptance_signals_include_measured_units_and_published_evidence_but_not_empty_praise():
    from coordinator_score import CHECKABLE
    assert CHECKABLE.search('DESIGN.md specifies a 1500ms transition.')
    assert CHECKABLE.search('The published nonempty asset matches the inventory.')
    assert not CHECKABLE.search('Looks good and feels professional.')
