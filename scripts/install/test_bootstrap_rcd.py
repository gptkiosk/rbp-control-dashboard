"""Tests for scripts/install/bootstrap-rcd.sh and scripts/release/build-linux-arm64.sh.

Run from the repository root:  python3 -I -m unittest scripts/install/test_bootstrap_rcd.py

The bootstrap cases use --dry-run on synthetic packages: they verify the package and change
nothing on disk. Only the success case needs an arm64 Linux host with systemd; it is skipped
elsewhere. Nothing here touches port 8800, systemd or the live data directory.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import re
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BOOTSTRAP = REPO / "scripts" / "install" / "bootstrap-rcd.sh"
BUILD = REPO / "scripts" / "release" / "build-linux-arm64.sh"
BASE = "rcd-0.1.0-linux-arm64"
ON_TARGET = platform.system() == "Linux" and platform.machine() in ("aarch64", "arm64")


def make_archive(path: Path, members: list[tarfile.TarInfo | tuple[str, bytes]]) -> None:
    with tarfile.open(path, "w:gz") as tf:
        for m in members:
            if isinstance(m, tuple):
                info = tarfile.TarInfo(m[0])
                info.size = len(m[1])
                tf.addfile(info, io.BytesIO(m[1]))
            else:
                tf.addfile(m)


def good_members() -> list[tuple[str, bytes]]:
    return [
        (f"{BASE}/apps/api/update_helper.py", b"# helper\n"),
        (f"{BASE}/apps/api/update_engine.py", b"# engine\n"),
        (f"{BASE}/apps/api/release_verify.py", b"# verify\n"),
        (f"{BASE}/ops/systemd/rcd-api.service.template", b"[Unit]\n"),
    ]


class Package:
    """A synthetic release: archive plus a manifest that describes it, as release.py would."""

    def __init__(self, directory: Path, members=None, **overrides):
        self.dir = directory
        self.archive = directory / f"{BASE}.tar.gz"
        make_archive(self.archive, members if members is not None else good_members())
        data = self.archive.read_bytes()
        manifest = {
            "schema": "dashboard-release-manifest/v1",
            "product": "rcd",
            "version": "0.1.0",
            "channel": "stable",
            "platform": {"key": "linux-arm64", "os": "linux", "arch": "arm64"},
            "source": {"commit": "0" * 40, "dirty": False, "release_eligible": True},
            "artifact": {"name": f"{BASE}.tar.gz", "root": BASE, "format": "tar+gzip",
                         "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)},
        }
        manifest.update(overrides)
        self.manifest = directory / f"{BASE}.manifest.json"
        self.manifest.write_bytes(json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n")
        self.digest = hashlib.sha256(self.manifest.read_bytes()).hexdigest()

    def run(self, *extra: str, digest: str | None = None) -> subprocess.CompletedProcess:
        args = ["bash", str(BOOTSTRAP), "--archive", str(self.archive), "--manifest", str(self.manifest),
                "--manifest-sha256", digest or self.digest, "--dry-run", *extra]
        env = {**os.environ, "RCD_INSTALL_ROOT": str(self.dir / "root")}
        return subprocess.run(args, capture_output=True, text=True, env=env, timeout=60)


class BootstrapRefusals(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def assert_refused(self, result: subprocess.CompletedProcess, *fragments: str) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout)
        for fragment in fragments:
            self.assertIn(fragment, result.stderr)
        self.assertNotIn("dry run: nothing was changed", result.stdout)

    def test_wrong_manifest_digest_is_refused(self) -> None:
        pkg = Package(self.dir)
        self.assert_refused(pkg.run(digest="0" * 64), "not the pinned")

    def test_cross_product_package_is_refused(self) -> None:
        pkg = Package(self.dir, product="mcd")
        self.assert_refused(pkg.run(), "cross-product")

    def test_wrong_platform_is_refused(self) -> None:
        pkg = Package(self.dir, platform={"key": "darwin-arm64", "os": "darwin", "arch": "arm64"})
        self.assert_refused(pkg.run(), "not for linux-arm64")

    def test_dev_channel_is_refused(self) -> None:
        pkg = Package(self.dir, channel="dev")
        self.assert_refused(pkg.run(), "only stable or prerelease")

    def test_unclean_source_is_refused(self) -> None:
        pkg = Package(self.dir, source={"commit": None, "dirty": True, "release_eligible": False})
        self.assert_refused(pkg.run(), "clean committed tree")

    def test_prerelease_needs_opt_in(self) -> None:
        pkg = Package(self.dir, channel="prerelease")
        self.assert_refused(pkg.run(), "--allow-prerelease")

    def test_size_mismatch_is_refused(self) -> None:
        pkg = Package(self.dir)
        manifest = json.loads(pkg.manifest.read_text())
        manifest["artifact"]["size"] += 1
        pkg.manifest.write_bytes(json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n")
        self.assert_refused(pkg.run(digest=hashlib.sha256(pkg.manifest.read_bytes()).hexdigest()),
                            "archive is")

    def test_tampered_archive_is_refused(self) -> None:
        pkg = Package(self.dir)
        pkg.archive.write_bytes(pkg.archive.read_bytes()[:-1] + b"\x00")
        self.assert_refused(pkg.run(), "archive")

    def test_partial_download_is_refused(self) -> None:
        pkg = Package(self.dir)
        pkg.archive.write_bytes(pkg.archive.read_bytes()[:100])
        self.assert_refused(pkg.run(), "archive")

    def test_path_traversal_member_is_refused(self) -> None:
        pkg = Package(self.dir, members=good_members() + [(f"{BASE}/../escape.py", b"x")])
        self.assert_refused(pkg.run(), "member refused")

    def test_absolute_member_is_refused(self) -> None:
        pkg = Package(self.dir, members=good_members() + [("/etc/evil", b"x")])
        self.assert_refused(pkg.run(), "member refused")

    def test_symlink_member_is_refused(self) -> None:
        link = tarfile.TarInfo(f"{BASE}/apps/api/link.py")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        pkg = Package(self.dir, members=good_members() + [link])
        self.assert_refused(pkg.run(), "member refused")

    def test_member_outside_release_root_is_refused(self) -> None:
        pkg = Package(self.dir, members=good_members() + [("rcd-0.1.0-linux-arm64-evil/x.py", b"x")])
        self.assert_refused(pkg.run(), "member refused")

    def test_explicit_python_path_is_not_silently_replaced(self) -> None:
        pkg = Package(self.dir)
        result = pkg.run("--python", str(self.dir / "no-such-python"))
        self.assert_refused(result, "Python 3.11 is required")

    def test_version_and_archive_together_are_refused(self) -> None:
        pkg = Package(self.dir)
        result = subprocess.run(["bash", str(BOOTSTRAP), "--version", "0.1.0", "--archive", str(pkg.archive),
                                 "--manifest", str(pkg.manifest), "--manifest-sha256", pkg.digest],
                                capture_output=True, text=True, timeout=60)
        self.assert_refused(result, "not both")

    def test_missing_manifest_digest_is_refused(self) -> None:
        pkg = Package(self.dir)
        result = subprocess.run(["bash", str(BOOTSTRAP), "--archive", str(pkg.archive),
                                 "--manifest", str(pkg.manifest), "--dry-run"],
                                capture_output=True, text=True, timeout=60)
        self.assert_refused(result, "--manifest-sha256")


@unittest.skipUnless(ON_TARGET, "the success path needs an arm64 Linux host")
class BootstrapPlan(unittest.TestCase):
    def test_valid_package_dry_run_prints_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Package(Path(tmp))
            result = pkg.run()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("dry run: nothing was changed", result.stdout)
            self.assertFalse((Path(tmp) / "root").exists())


class HelperCopyList(unittest.TestCase):
    """The bootstrap must copy every module the staged helper imports, or stage fails at load time."""

    API = REPO / "apps" / "api"
    ENTRY_POINTS = ["update_helper.py", "update_recovery.py"]

    def copied_helper_files(self) -> set[str]:
        for line in BOOTSTRAP.read_text().splitlines():
            if line.startswith("for f in ") and "update_helper.py" in line:
                return set(line[len("for f in "):].split(";")[0].split())
        self.fail("no helper copy loop found in bootstrap-rcd.sh")

    def local_imports_closure(self) -> set[str]:
        seen: set[str] = set()
        pending = list(self.ENTRY_POINTS)
        while pending:
            name = pending.pop()
            if name in seen:
                continue
            seen.add(name)
            for module in re.findall(r"^import (\w+)\b", (self.API / name).read_text(), re.MULTILINE):
                if (self.API / f"{module}.py").is_file():
                    pending.append(f"{module}.py")
        return seen

    def test_copy_loop_covers_every_local_import(self) -> None:
        copied = self.copied_helper_files()
        missing = self.local_imports_closure() - copied
        self.assertEqual(missing, set(), f"bootstrap does not copy {sorted(missing)} into the helper directory")

    def test_copied_files_exist_in_the_api_tree(self) -> None:
        for name in self.copied_helper_files():
            self.assertTrue((self.API / name).is_file(), name)


class BuildWrapper(unittest.TestCase):
    def test_build_refuses_a_tree_without_git(self) -> None:
        # This checkout has no .git directory, so the clean-source gate must stop the build before
        # any output is written.
        if (REPO / ".git").exists():
            self.skipTest("repository has .git; the no-git refusal does not apply")
        with tempfile.TemporaryDirectory() as out:
            result = subprocess.run(["bash", str(BUILD), "--out", out], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("no .git directory", result.stderr)
            self.assertEqual(os.listdir(out), [])


if __name__ == "__main__":
    unittest.main()
