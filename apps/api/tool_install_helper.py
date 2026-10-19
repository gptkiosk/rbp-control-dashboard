"""Agent tools helper: installs, updates, removes and rolls back the agent CLIs, outside the service.

The API starts this detached (as its own transient systemd unit, like the update helper) for an operator's
confirmed request. It can also be run by hand, which is how to use it when dashboard sign-in is off.

    python3 -I tool_install_helper.py status [--root DIR]
    python3 -I tool_install_helper.py plan <tool> <install|update|remove|rollback> [--root DIR]
    python3 -I tool_install_helper.py run  <tool> <install|update|remove|rollback> --plan-sha256 HEX [--root DIR]

`run` refuses unless the plan it builds now has exactly the plan_sha256 the operator confirmed, and it sets
no_new_privs first so no installer it starts can use sudo. Prints one JSON object. Exit 0 on success,
1 when refused or failed, 2 on bad usage. It never signs in to anything and never reads a key.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_PRODUCT = "rcd"

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # -I does not add the script directory

import tool_install as ti  # noqa: E402


def default_root() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / (f"{DEFAULT_PRODUCT}-agent-tools")


def build_config(root: Path, catalog_dir: Path = HERE, product: str | None = None) -> tuple[ti.ToolsConfig, ti.Catalog]:
    catalog = ti.load_catalog(catalog_dir)
    facts = ti.detect_host(root)
    cfg = ti.ToolsConfig(root=root, catalog_dir=catalog_dir, platform_key=facts.platform_key, home=Path.home(), product=product or DEFAULT_PRODUCT)
    return cfg, catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tool_install_helper.py")
    parser.add_argument("--root", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    for name in ("plan", "run"):
        p = sub.add_parser(name)
        p.add_argument("tool")
        p.add_argument("action", choices=ti.ACTIONS)
        if name == "run":
            p.add_argument("--plan-sha256", required=True)
    args = parser.parse_args(argv)
    if args.command == "run" and not re.fullmatch(r"[0-9a-f]{64}", args.plan_sha256):
        parser.error("--plan-sha256 must be the 64-hex plan digest shown in the confirmation")

    os.umask(0o077)
    root = (args.root or default_root()).absolute()
    log = None
    try:
        cfg, catalog = build_config(root)
        if args.command == "status":
            result = ti.inspect(cfg, catalog)
        elif args.command == "plan":
            result = ti.build_plan(cfg, catalog, ti.detect_host(root, ti._tool_commands(catalog)), args.tool, args.action)
        else:
            ti.prepare_layout(cfg)
            # A tool installed outside the tools root (Hermes under ~/.hermes, say) cannot run once the macOS sandbox hides the home
            # folder, so its version is read now and the plan below reuses it; otherwise every native upgrade is refused as unverifiable.
            ti.native_install(cfg, catalog, ti.detect_host(root, ti._tool_commands(catalog)), args.tool)
            if not ti.harden_process(cfg):
                raise ti.ToolError("This host could not restrict the installer from gaining privileges (Linux no_new_privs / macOS Seatbelt), "
                                   "so nothing was installed.")
            log = ti.Log(cfg.state_dir / "helper.log")
            log.line("helper started; installer privilege restrictions are active")
            result = ti.run_action(cfg, catalog, args.tool, args.action, expect_plan_sha256=args.plan_sha256, log=log)
    except ti.ToolError as exc:
        print(json.dumps({"ok": False, "problems": exc.problems}))
        return 1
    except OSError as exc:
        print(json.dumps({"ok": False, "problems": [f"{type(exc).__name__}: {exc.strerror or exc}"]}))
        return 1
    finally:
        if log is not None:
            log.close()
    print(json.dumps({"ok": True, "result": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
