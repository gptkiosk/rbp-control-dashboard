import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace, ModuleType
import pytest
import native_routes
import hermes_runtime

def test_fresh_catalog_uses_current_targets_and_excludes_secrets(tmp_path):
    claw=tmp_path/'openclaw.json';hermes=tmp_path/'config.yaml'
    claw.write_text(json.dumps({'env':{'TOKEN':'private-token'},'agents':{'defaults':{'model':{'primary':'openrouter/thinkingmachines/inkling:free','fallbacks':['openrouter/google/gemini-2.5-flash']},'models':{'openrouter/cohere/north-mini-code:free':{'apiKey':'private-key'}}},'list':[{'id':'mm-developer','name':'Developer','model':{'primary':'openrouter/cohere/north-mini-code:free'}},{'id':'mm-security','name':'Security Reviewer'}]}}))
    hermes.write_text('model:\n  default: thinkingmachines/inkling:free\nfallback_providers:\n- provider: openrouter\n  model: google/gemma-4-31b-it:free\n  api_key: private-key\n')
    settings=SimpleNamespace(environment='test',openclaw_config_path=claw,hermes_config_path=hermes)
    result=native_routes.read(settings)
    assert result['openclaw']['targets'][0]['model']=='openrouter/cohere/north-mini-code:free'
    assert [r['id'] for r in result['openclaw']['targets']]==['mm-developer','mm-security']
    assert result['hermes']['models']==['thinkingmachines/inkling:free','google/gemma-4-31b-it:free']
    assert 'private-' not in json.dumps(result)
    assert native_routes.automatic_route('openrouter/cohere/north-mini-code:free')
    assert not native_routes.automatic_route('anthropic/paid')

def test_hermes_shim_disables_only_pinned_fallbacks_and_reports_final_model(monkeypatch):
    spec=importlib.util.spec_from_file_location('mcd_shim',hermes_runtime.SHIM);shim=importlib.util.module_from_spec(spec);spec.loader.exec_module(shim)
    package=ModuleType('hermes_cli');package.__path__=[]
    fallback=ModuleType('hermes_cli.fallback_config');fallback.get_fallback_chain=lambda config:['native-free','capped-google']
    stream=ModuleType('hermes_cli.stream_json')
    class Emitter:
        def attach(self,agent): return self
        def _emit(self,event): self.event=event
    stream.StreamJsonEmitter=Emitter
    monkeypatch.setitem(sys.modules,'hermes_cli',package)
    monkeypatch.setitem(sys.modules,'hermes_cli.fallback_config',fallback)
    monkeypatch.setitem(sys.modules,'hermes_cli.stream_json',stream)
    shim.install(False);assert fallback.get_fallback_chain({})==['native-free','capped-google']
    shim.install(True);assert fallback.get_fallback_chain({})==[]
    emitter=Emitter();emitter.attach(SimpleNamespace(model='final-model',provider='openrouter'));emitter._emit({'type':'result'})
    assert emitter.event['model']=='final-model' and emitter.event['provider']=='openrouter'

def test_unsupported_hermes_launcher_fails_before_start(tmp_path):
    launcher=tmp_path/'hermes';launcher.write_text('#!/bin/sh\nexit 0\n')
    with pytest.raises(FileNotFoundError,match='enforce assigned models'):hermes_runtime.command([str(launcher),'chat','-m','assigned'])
