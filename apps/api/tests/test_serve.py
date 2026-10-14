from __future__ import annotations

import pytest


@pytest.mark.parametrize("host", ["0.0.0.0", "192.0.2.80", "198.51.100.109"])
def test_refuses_non_loopback_before_auth(monkeypatch, host):
    monkeypatch.setenv("MAC_CONTROL_HOST", host)
    import serve
    import settings

    settings.get_settings.cache_clear()
    called = []
    monkeypatch.setattr(serve.uvicorn, "run", lambda *a, **k: called.append(1))
    assert serve.main() == 2
    assert called == []
    settings.get_settings.cache_clear()


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_allows_loopback(monkeypatch, host):
    monkeypatch.setenv("MAC_CONTROL_HOST", host)
    import serve
    import settings

    settings.get_settings.cache_clear()
    called = []
    monkeypatch.setattr(serve.uvicorn, "run", lambda *a, **k: called.append(k["host"]))
    assert serve.main() == 0
    assert called == [host]
    settings.get_settings.cache_clear()
