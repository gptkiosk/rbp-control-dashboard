from __future__ import annotations

import time

import pytest

from zc_support import FREE, PAID, ZERO, Upstream, zeroclaw_binary  # noqa: F401  (sets sys.path)
from integrations.zeroclaw import FreeModelCatalog, ProviderProxy, ZeroClawAdapter, ZeroClawConfig


@pytest.fixture
def upstream():
    stub = Upstream()
    yield stub
    stub.close()


@pytest.fixture
def catalog():
    return FreeModelCatalog({FREE: ZERO, PAID: {"prompt": "0.0000005", "completion": "0.000001"}},
                            verified_at=int(time.time()))


@pytest.fixture(autouse=True)
def provider_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-a-secret")


@pytest.fixture
def proxy(catalog, upstream):
    server = ProviderProxy(catalog, upstream=upstream.url, upstream_timeout_s=20,
                           account_fetch=lambda key: {"lifetime_usd": 0, "limit_usd": 0, "remaining_usd": 0})
    server.start()
    yield server
    server.stop()


@pytest.fixture
def make_adapter(tmp_path, proxy, catalog):
    def build(**overrides):
        executable = overrides.pop("executable", None) or zeroclaw_binary() or "zeroclaw"
        return ZeroClawAdapter(ZeroClawConfig(state_dir=tmp_path / "state", proxy=proxy, catalog=catalog,
                                              executable=executable, **overrides))
    return build


@pytest.fixture
def need_runtime():
    if not zeroclaw_binary():
        pytest.skip("zeroclaw binary not available (set RCD_ZEROCLAW_BIN)")


@pytest.fixture
def workspace(tmp_path):
    path = tmp_path / "ws"
    path.mkdir()
    return path
