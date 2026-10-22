import os

import settings


def test_agent_path_includes_the_managed_node_runtime(tmp_path, monkeypatch):
    root = tmp_path / "agent-tools"
    monkeypatch.setenv("MAC_CONTROL_AGENT_TOOLS_ROOT", str(root))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert str(root / "tools" / "node" / "current" / "bin") in settings.tool_search_dirs()
