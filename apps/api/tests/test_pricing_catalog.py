"""The price catalog and the checker that keeps it current. No network: the checker reads small page excerpts."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

import billing

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("pricing_check", ROOT / "scripts" / "pricing" / "check.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

CATALOG = json.loads((ROOT / "apps" / "api" / "pricing_catalog.json").read_text())

OPENAI_PAGE = '''<x props="{&quot;tier&quot;:[0,&quot;standard&quot;],&quot;rows&quot;:[1,[[1,[[0,&quot;gpt-6.1-sol&quot;],[0,2],[0,0.1],[0,2.5],[0,10]]],
[1,[[0,&quot;gpt-5.5 (&lt;272K context length)&quot;],[0,5],[0,0.5],[0,&quot;-&quot;],[0,30]]]]]}"> <x props="{&quot;tier&quot;:[0,&quot;batch&quot;],&quot;rows&quot;:[1,[[1,[[0,&quot;gpt-6.1-sol&quot;],[0,1],[0,0.05],[0,1.25],[0,5]]]]]}">'''

ANTHROPIC_PAGE = '''| Model | Base input tokens | 5m cache writes | 1h cache writes | Cache hits | Output |
| Claude Opus 5.5 | $4 / MTok | $5 / MTok | $8 / MTok | $0.20 / MTok<sup>2</sup> | $20 / MTok |
| Claude Haiku 5.5 (for prompts up to 100,000 tokens) | $0.10 / MTok | $0.125 / MTok | $0.20 / MTok | $0.01 / MTok | $0.50 / MTok |
| Claude Haiku 5.5 (for prompts over 100,000 tokens) | $0.50 / MTok | $0.625 / MTok | $1 / MTok | $0.05 / MTok | $2.50 / MTok |
'''

GOOGLE_PAGE = '''## Gemini 3.8 Flash

*[`gemini-3.8-flash`](https://x)*

### Standard

|   | Free Tier | Paid Tier, per 1M tokens in USD |
|---|---|---|
| Input price | Free of charge | $0.75 through December 31, 2026. $1.50 starting January 1, 2027. |
| Output price (including thinking tokens) | Free of charge | $3.75 through December 31, 2026. $7.50 starting January 1, 2027. |
| Context caching price | Free of charge | $0.075 through December 31, 2026. $0.15 starting January 1, 2027. $0.50 / 1,000,000 tokens per hour (storage price) through December 31, 2026. |

## Gemini 3.1 Pro Preview

*[`gemini-3.1-pro-preview`](https://x)*

### Standard

|   | Free Tier | Paid Tier, per 1M tokens in USD |
|---|---|---|
| Input price | Not available | $2.00, prompts \\<= 200k tokens $4.00, prompts \\> 200k tokens |
| Output price (including thinking tokens) | Not available | $12.00, prompts \\<= 200k tokens $18.00, prompts \\> 200k |
| Context caching price | Not available | $0.20, prompts \\<= 200k tokens $0.40, prompts \\> 200k $4.50 / 1,000,000 tokens per hour (storage price) |

## Gemini 2.5 Flash

*[`gemini-2.5-flash`](https://x)*

### Standard

|   | Free Tier | Paid Tier, per 1M tokens in USD |
|---|---|---|
| Input price | Free of charge | $0.30 (text / image / video) $1.00 (audio) |
| Output price (including thinking tokens) | Free of charge | $2.50 |
| Context caching price | Not available | $0.03 (text / image / video) $0.1 (audio) $1.00 / 1,000,000 tokens per hour (storage price) |
'''


def test_catalog_is_complete_and_consistent():
    assert set(CATALOG["sources"]) == {"openai", "anthropic", "google", "xai", "openrouter"}
    for model, e in CATALOG["models"].items():
        assert e["source"] in CATALOG["sources"], model
        assert e["agents"] and set(e["agents"]) <= {"claude", "codex", "grok", "hermes", "openclaw"}, model
        assert e["status"] in ("current", "legacy"), model
        for field in ("input", "output", "cached", "write", "write_1h", "verified"):
            assert field in e, (model, field)
        assert e["input"] > 0 and e["output"] > 0
        assert ("long_after" in e) == ("long_input_multiplier" in e) == ("long_output_multiplier" in e), model
        for change in e.get("changes", []):
            assert change["from"] > e["verified"], model  # a dated change is in the future of the check
    for model, e in CATALOG["free_models"].items():
        assert (model.endswith(":free") or model == "openrouter/free") and e["input"] == 0 and e["output"] == 0
    # what each platform is configured to use here is priced
    for needed in ("gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
                   "gpt-5.5", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "gemini-2.5-flash",
                   "grok-4.7", "grok-4.6", "grok-4.5", "grok-build-0.1"):
        assert needed in billing.DEFAULT_RATES, needed


def test_billing_defaults_come_from_the_catalog():
    assert set(billing.DEFAULT_RATES) == set(CATALOG["models"])
    assert billing.DEFAULT_RATES["claude-haiku-5-5"]["long_after"] == 100_000
    assert billing.DEFAULT_RATES["gpt-5.6-sol"]["input"] == 4


def test_dated_price_change_applies_from_its_date():
    cfg = {"rates": billing.DEFAULT_RATES}
    row = {"model": "gemini-3.8-flash", "input_tokens": 1_000_000, "output_tokens": 0}
    before = billing.price({**row, "ts": 1_798_000_000}, cfg)[0]   # 2026-12-22
    after = billing.price({**row, "ts": 1_799_000_000}, cfg)[0]    # 2027-01-02
    assert round(before, 6) == 0.75 and round(after, 6) == 1.5


def test_readers_understand_each_page():
    openai = check.read_openai(OPENAI_PAGE)
    assert openai["gpt-6.1-sol"] == {"input": 2.0, "output": 10.0, "cached": 0.1, "write": 2.5}  # Standard, not Batch
    assert openai["gpt-5.5"] == {"input": 5.0, "output": 30.0, "cached": 0.5, "write": 5.0}     # '-' means plain input
    claude = check.read_anthropic(ANTHROPIC_PAGE)
    assert claude["claude-opus-5-5"] == {"input": 4.0, "write": 5.0, "write_1h": 8.0, "cached": 0.2, "output": 20.0}
    assert claude["claude-haiku-5-5"]["long_rate"]["after"] == 100_000
    google = check.read_google(GOOGLE_PAGE)
    assert google["gemini-2.5-flash"] == {"input": 0.3, "output": 2.5, "cached": 0.03, "write": 0.3}
    assert google["gemini-3.8-flash"]["changes"] == [{"from": "2027-01-01", "input": 1.5, "write": 1.5, "output": 7.5, "cached": 0.15}]
    assert google["gemini-3.1-pro-preview"]["long"] == {"after": 200_000, "input_multiplier": 2.0, "output_multiplier": 1.5}
    for broken in (check.read_openai, check.read_anthropic):
        with pytest.raises(ValueError):
            broken("nothing here")


def test_current_catalog_matches_the_excerpts():
    for source, page in (("openai", check.read_openai(OPENAI_PAGE)), ("anthropic", check.read_anthropic(ANTHROPIC_PAGE)),
                         ("google", check.read_google(GOOGLE_PAGE))):
        report = check.compare(CATALOG, source, page)
        assert report["differs"] == [], (source, report["differs"])


def test_compare_finds_changes_and_missing_models():
    catalog = copy.deepcopy(CATALOG)
    catalog["models"]["gpt-5.5"]["output"] = 25.0
    report = check.compare(catalog, "openai", check.read_openai(OPENAI_PAGE))
    assert report["differs"] == [{"model": "gpt-5.5", "fields": {"output": {"catalog": 25.0, "source": 30.0}}}]
    assert any(m["model"] == "gpt-5.6-sol" for m in report["missing"])  # on none of the excerpt's rows: reported, not assumed
    free = check.compare_free(CATALOG, {"thinkingmachines/inkling:free": {"input": 0.0, "output": 0.0}})
    assert free["same"] == ["thinkingmachines/inkling:free"] and len(free["missing"]) == len(CATALOG["free_models"]) - 1
    paid = check.compare_free(CATALOG, {"thinkingmachines/inkling:free": {"input": 0.5, "output": 1.0}})
    assert paid["differs"][0]["model"] == "thinkingmachines/inkling:free"


def test_apply_writes_changed_prices_and_the_date(tmp_path, capsys):
    offline = tmp_path / "pages"
    offline.mkdir()
    (offline / "openai.txt").write_text(OPENAI_PAGE)
    catalog = copy.deepcopy(CATALOG)
    catalog["models"]["gpt-5.5"]["output"] = 25.0
    catalog["models"]["gpt-5.5"]["verified"] = "2000-01-01"
    for name in ("anthropic", "google", "xai"):
        del catalog["sources"][name]
    del catalog["sources"]["openrouter"]
    file = tmp_path / "catalog.json"
    file.write_text(json.dumps(catalog))
    assert check.main(["--offline", str(offline), "--catalog", str(file)]) == 1          # a difference fails the check
    assert check.main(["--offline", str(offline), "--catalog", str(file), "--apply"]) == 0
    written = json.loads(file.read_text())
    assert written["models"]["gpt-5.5"]["output"] == 30.0
    assert written["models"]["gpt-5.5"]["verified"] != "2000-01-01"
    assert check.main(["--offline", str(offline), "--catalog", str(file)]) == 0          # and now it matches


def test_models_used_without_a_price_are_found_and_can_be_added(sessions, tmp_path):
    import time
    from models import Run

    page = OPENAI_PAGE.replace("]]]]]}\"> <x", "]],[1,[[0,&quot;gpt-7-test&quot;],[0,3],[0,0.3],[0,3.75],[0,15]]]]]}\"> <x", 1)
    assert "gpt-7-test" in check.read_openai(page)
    with sessions.begin() as s:
        for model, agent in (("gpt-7-test", "codex"), ("gpt-6-sol", "codex"), ("thinkingmachines/inkling:free", "hermes"), ("mystery-model", "claude")):
            s.add(Run(agent=agent, stage="succeeded", started_at=int(time.time()), working_dir="/ws", command="[]",
                      log_path="", model_requested=model, input_tokens=1000, output_tokens=100))
    with sessions() as s:
        used = check.used_unpriced(s)
    # priced, free and unknown-everywhere models: only the two with no catalog price are reported
    assert used == {"gpt-7-test": {"codex"}, "mystery-model": {"claude"}}

    pages = {"openai": check.read_openai(page)}
    source, key, found = check.match_page("openrouter/openai/gpt-7-test", pages)
    assert (source, key) == ("openai", "gpt-7-test") and check.match_page("mystery-model", pages) is None
    entry = check.candidate_entry("gpt-7-test", source, found, {"codex"}, "2026-10-13")
    assert (entry["input"], entry["output"], entry["cached"], entry["write"]) == (3.0, 15.0, 0.3, 3.75)
    assert entry["agents"] == ["codex"] and entry["max_input"] == 272_000   # the page states only the short-context price
    claude = check.candidate_entry("claude-opus-5-9", "anthropic", {"input": 5, "output": 25, "cached": 0.5, "write": 6.25, "write_1h": 10}, {"claude"}, "x")
    assert claude["max_input"] is None


XAI_PAGE = """| Model | Context | Input / 1M tokens | Cached input / 1M tokens | Output / 1M tokens |
| --- | --- | --- | --- | --- |
| grok-4.6 (< 200k prompt tokens) | 500k | $2.00 | $0.50 | $6.00 |
| grok-4.6 (\u2265 200k prompt tokens) | 500k | $4.00 | $1.00 | $12.00 |
| grok-build-0.1 (< 200k prompt tokens) | 256k | $1.00 | $0.20 | $2.00 |
| grok-build-0.1 (\u2265 200k prompt tokens) | 256k | $2.00 | $0.40 | $4.00 |
| grok-imagine-image | $0.02 / image |
"""


def test_xai_reader_and_the_grok_prices_in_the_catalog():
    page = check.read_xai(XAI_PAGE)
    assert page["grok-4.6"] == {"input": 2.0, "cached": 0.5, "output": 6.0, "write": 2.0,
                                "long_rate": {"after": 200_000, "input": 4.0, "cached": 1.0, "output": 12.0}}
    assert "grok-imagine-image" not in page
    report = check.compare(CATALOG, "xai", page)
    assert report["differs"] == [], report["differs"]
    # a long-context tier that changed is a difference the checker reports
    changed = copy.deepcopy(CATALOG)
    changed["models"]["grok-4.6"]["long_output_multiplier"] = 3
    assert check.compare(changed, "xai", page)["differs"][0]["fields"]["long_output_multiplier"]["source"] == 2.0
    with pytest.raises(ValueError):
        check.read_xai("nothing here")
    # priced like any other model: 300k prompt tokens are billed at the long-context rate for every token
    cfg = {"rates": billing.DEFAULT_RATES}
    cost = billing.price({"model": "grok-4.6", "input_tokens": 300_000, "output_tokens": 100_000}, cfg)[0]
    assert round(cost, 6) == round(300_000 * 4 / 1e6 + 100_000 * 12 / 1e6, 6)
