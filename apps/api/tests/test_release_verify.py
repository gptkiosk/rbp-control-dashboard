"""Release package verifier (s5-verifier): every refusal the update engine relies on.

All packages are synthetic, built in tmp_path. No network, no real release, nothing executed
from a package. Cases where the archive is malicious but its digests are consistent model a
signed-but-hostile release: the member checks must still refuse it.
"""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

import pytest

import release_verify as rv
from release_verify import PinnedDigest, SshSignature, TrustPolicy, VerificationError

REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCT, PLATFORM = "rcd", "linux-arm64"
OTHER_PRODUCT, OTHER_PLATFORM = "mcd", "darwin-arm64"
LOCK = b"fastapi==0.115.0 \\\n    --hash=sha256:" + b"b" * 64 + b"\n"
SSH_KEYGEN = next((p for p in SshSignature.CANDIDATES if os.path.isfile(p)), None)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def member(name: str, data: bytes | None = None, mode: int | None = None, kind: bytes | None = None,
           link: str = "") -> tuple[tarfile.TarInfo, bytes | None]:
    info = tarfile.TarInfo(name)
    info.mtime = 0
    info.type = kind or (tarfile.DIRTYPE if data is None else tarfile.REGTYPE)
    info.mode = mode if mode is not None else (0o755 if info.type == tarfile.DIRTYPE else 0o644)
    info.linkname = link
    if data is not None:
        info.size = len(data)
    return info, data


def tar_gz(members: list) -> bytes:
    raw = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for info, data in members:
                tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return raw.getvalue()


@dataclass
class Release:
    base: str
    manifest: dict
    manifest_bytes: bytes
    manifest_path: Path
    artifact_path: Path


def make_release(tmp_path: Path, *, product: str = PRODUCT, platform: str = PLATFORM, version: str = "1.2.0",
                 repository: str | None = None, eligible: bool = True, extra_files: dict | None = None,
                 members_hook=None, artifact_hook=None, manifest_hook=None, name: str = "release") -> Release:
    repository = repository or rv.OFFICIAL_REPOSITORIES[product]
    channel = ("prerelease" if "-" in version else "stable") if eligible else "dev"
    commit = "a" * 40 if eligible else None
    base = f"{product}-{version}-{platform}"
    build_info = {"product": product, "version": version, "platform": platform, "source_commit": commit,
                  "source_dirty": False if eligible else None, "source_tree_sha256": "c" * 64,
                  "source_date_epoch": 1_700_000_000, "web_build": "prebuilt", "channel": channel}
    entries = {
        "BUILD_INFO.json": (canonical(build_info), 0o644),
        "LICENSE": (b"MIT License\n", 0o644),
        "packaging/product.json": (b"{}\n", 0o644),
        "apps/api/main.py": (b"app = None\n", 0o644),
        "apps/api/version.py": (f'__version__ = "{version}"\n'.encode(), 0o644),
        "apps/api/requirements.release.txt": (LOCK, 0o644),
        "apps/web/dist/index.html": (b"<!doctype html>\n", 0o644),
        "ops/start.sh": (b"#!/bin/sh\n", 0o755),
        **(extra_files or {}),
    }
    records = [{"path": p, "sha256": sha(d), "size": len(d), "mode": f"{m:04o}"} for p, (d, m) in sorted(entries.items())]
    inner = canonical({"schema": rv.FILES_SCHEMA, "product": product, "version": version, "platform": platform,
                       "files": records})
    everything = {**entries, "manifest.json": (inner, 0o644)}
    dirs = {"/".join(p.split("/")[:i]) for p in everything for i in range(1, p.count("/") + 1)}
    members = [member(base)] + sorted(
        [member(f"{base}/{d}") for d in dirs] + [member(f"{base}/{p}", d, m) for p, (d, m) in everything.items()],
        key=lambda item: item[0].name)
    if members_hook:
        members = members_hook(base, members)
    artifact = tar_gz(members)
    if artifact_hook:
        artifact = artifact_hook(artifact)
    os_name, arch = rv.PLATFORM_OS_ARCH[platform]
    manifest = {
        "schema": rv.MANIFEST_SCHEMA, "product": product, "product_name": "Synthetic dashboard",
        "repository": repository, "version": version, "channel": channel,
        "platform": {"key": platform, "os": os_name, "arch": arch},
        "runtime": {"python": "3.12", "python_abi": "cp312", "pip_platforms": ["synthetic"]},
        "source": {"commit": commit, "dirty": False if eligible else None, "release_eligible": eligible,
                   "tree_sha256": "c" * 64},
        "build": {"source_date_epoch": 1_700_000_000, "source_date_epoch_from": "argument", "web_build": "prebuilt",
                  "tools": {"python": "3.12"}},
        "dependencies": {"lock_path": "apps/api/requirements.release.txt", "lock_sha256": sha(LOCK),
                         "packages": [{"name": "fastapi", "version": "0.115.0"}]},
        "artifact": {"name": f"{base}.tar.gz", "root": base, "format": "tar+gzip", "sha256": sha(artifact),
                     "size": len(artifact)},
        "contents": {"manifest_path": "manifest.json", "manifest_sha256": sha(inner), "file_count": len(records),
                     "total_size": sum(r["size"] for r in records)},
        "files": records,
    }
    if manifest_hook:
        manifest_hook(manifest)
    manifest_bytes = canonical(manifest)
    out = tmp_path / name
    out.mkdir()
    (out / f"{base}.tar.gz").write_bytes(artifact)
    (out / f"{base}.manifest.json").write_bytes(manifest_bytes)
    return Release(base, manifest, manifest_bytes, out / f"{base}.manifest.json", out / f"{base}.tar.gz")


def policy(release: Release, **overrides) -> TrustPolicy:
    values = {"product": PRODUCT, "platform": PLATFORM, "check_host": False, "installed_version": "1.1.0",
              "authenticator": PinnedDigest(sha(release.manifest_bytes), "test pin")}
    values.update(overrides)
    return TrustPolicy(**values)


def refused(release: Release, trust: TrustPolicy | None = None, **kwargs) -> str:
    with pytest.raises(VerificationError) as exc:
        rv.verify_release(release.manifest_path, release.artifact_path, trust or policy(release), **kwargs)
    return " | ".join(exc.value.problems)


def add(*extra):
    """members_hook appending (rel path, data[, mode]) files under the release root."""
    return lambda base, members: members + [member(f"{base}/{rel}", *rest) for rel, *rest in extra]


# --- accepted package ----------------------------------------------------------------------


def test_valid_release_verifies_and_extracts_only_verified_files(tmp_path):
    release = make_release(tmp_path)
    verified = rv.verify_release(release.manifest_path, release.artifact_path, policy(release))
    assert (verified.product, verified.platform, verified.version) == (PRODUCT, PLATFORM, "1.2.0")
    assert (verified.channel, verified.change) == ("stable", "upgrade")
    assert verified.authenticity == "pinned-digest (test pin)"
    assert verified.artifact_sha256 == release.manifest["artifact"]["sha256"]

    (tmp_path / "stage").mkdir()
    dest = rv.extract(verified, tmp_path / "stage" / "v1.2.0")
    written = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
    assert written == set(verified.files)
    assert "manifest.json" in written
    assert (dest / "ops/start.sh").stat().st_mode & 0o7777 == 0o755
    assert (dest / "LICENSE").stat().st_mode & 0o7777 == 0o644
    assert (dest / "apps").stat().st_mode & 0o7777 == 0o755
    assert not any(p.is_symlink() for p in dest.rglob("*"))


def test_fixture_matches_the_release_builder_format(tmp_path):
    tool_path = REPO_ROOT / "scripts" / "release" / "release.py"
    if not tool_path.is_file():
        pytest.skip("release builder is not in this checkout")
    spec = importlib.util.spec_from_file_location("release_tool_under_test", tool_path)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    release = make_release(tmp_path)
    assert tool.validate_manifest(release.manifest) == []
    assert tool.verify_artifact(release.manifest, release.artifact_path) == []


# --- trusted repository, product and platform ---------------------------------------------


def test_refuses_release_naming_another_repository(tmp_path):
    release = make_release(tmp_path, repository="someone/mac-control-dashboard")
    assert "fetched from" in refused(release)


def test_refuses_other_products_official_repository(tmp_path):
    release = make_release(tmp_path, repository=rv.OFFICIAL_REPOSITORIES[OTHER_PRODUCT])
    assert "fetched from" in refused(release)


def test_fork_needs_explicit_opt_in(tmp_path):
    release = make_release(tmp_path, repository="someone/fork")
    assert "forks need explicit opt-in" in refused(release, policy(release, repository="someone/fork"))
    verified = rv.verify_release(release.manifest_path, release.artifact_path,
                                 policy(release, repository="someone/fork", allow_fork=True))
    assert verified.repository == "someone/fork"


def test_refuses_wrong_product(tmp_path):
    release = make_release(tmp_path, product=OTHER_PRODUCT, platform=OTHER_PLATFORM)
    message = refused(release)
    assert f"product {OTHER_PRODUCT}, not {PRODUCT}" in message
    assert f"for {OTHER_PLATFORM}, not {PLATFORM}" in message


def test_refuses_wrong_or_inconsistent_platform(tmp_path):
    def other_arch(m):
        m["platform"]["arch"] = "x86_64"

    assert "platform os/arch mismatch" in refused(make_release(tmp_path, manifest_hook=other_arch, name="a"))

    def other_key(m):
        m["platform"] = {"key": OTHER_PLATFORM, "os": rv.PLATFORM_OS_ARCH[OTHER_PLATFORM][0], "arch": "arm64"}

    assert "unsupported product/platform" in refused(make_release(tmp_path, manifest_hook=other_key, name="b"))


def test_refuses_install_on_a_host_of_another_platform(tmp_path, monkeypatch):
    release = make_release(tmp_path)
    monkeypatch.setattr(rv, "host_platform", lambda: OTHER_PLATFORM)
    assert f"this host is {OTHER_PLATFORM}" in refused(release, policy(release, check_host=True))
    monkeypatch.setattr(rv, "host_platform", lambda: None)
    assert "unsupported" in refused(release, policy(release, check_host=True))
    monkeypatch.setattr(rv, "host_platform", lambda: PLATFORM)
    rv.verify_release(release.manifest_path, release.artifact_path, policy(release, check_host=True))


# --- tampering -----------------------------------------------------------------------------


def test_refuses_tampered_artifact(tmp_path):
    release = make_release(tmp_path)
    data = bytearray(release.artifact_path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    release.artifact_path.write_bytes(bytes(data))
    assert "artifact sha256 does not match" in refused(release)


def test_refuses_manifest_changed_after_it_was_authenticated(tmp_path):
    release = make_release(tmp_path)
    trust = policy(release)
    swapped = dict(release.manifest, version="9.9.9")
    release.manifest_path.write_bytes(canonical(swapped))
    assert "authenticity" in refused(release, trust)


def test_refuses_tampered_member_inside_a_consistent_archive(tmp_path):
    def swap(base, members):
        return [member(info.name, b"import os; os.system('x')\n") if info.name == f"{base}/apps/api/main.py"
                else (info, data) for info, data in members]

    assert "digest mismatch: apps/api/main.py" in refused(make_release(tmp_path, members_hook=swap))


def test_refuses_unlisted_file_and_changed_mode(tmp_path):
    assert "unlisted" in refused(make_release(tmp_path, members_hook=add(("apps/api/extra.py", b"x\n")), name="a"))

    def chmod(base, members):
        return [member(i.name, d, 0o755) if i.name == f"{base}/apps/api/main.py" else (i, d) for i, d in members]

    assert "mode mismatch: apps/api/main.py" in refused(make_release(tmp_path, members_hook=chmod, name="b"))


def test_refuses_missing_listed_file(tmp_path):
    def drop(base, members):
        return [(i, d) for i, d in members if i.name != f"{base}/LICENSE"]

    assert "missing from the artifact" in refused(make_release(tmp_path, members_hook=drop))


def test_refuses_corrupt_gzip_and_trailing_data(tmp_path):
    assert "not valid gzip" in refused(make_release(tmp_path, artifact_hook=lambda a: b"not a gzip stream" * 8, name="a"))
    assert "data after the gzip stream" in refused(make_release(tmp_path, artifact_hook=lambda a: a + a, name="b"))
    assert "truncated" in refused(make_release(tmp_path, artifact_hook=lambda a: a[: len(a) // 2], name="c"))


# --- zip-slip, links and special members -----------------------------------------------------


@pytest.mark.parametrize("name", [
    "{base}/../escape.txt",
    "{base}/apps/../../escape.txt",
    "/tmp/escape.txt",
    "escape.txt",
    "{base}-other/escape.txt",
    "{base}/apps/./escape.txt",
    "{base}/apps//escape.txt",
    "{base}/apps\\..\\escape.txt",
    "{base}/apps/esc ape.txt",
])
def test_refuses_path_traversal_and_unsafe_names(tmp_path, name):
    def hook(base, members):
        return members + [member(name.format(base=base), b"owned\n")]

    message = refused(make_release(tmp_path, members_hook=hook))
    assert "outside the release root" in message or "unsafe member path" in message
    assert not (tmp_path / "escape.txt").exists() and not (tmp_path.parent / "escape.txt").exists()


@pytest.mark.parametrize("kind,link", [
    (tarfile.SYMTYPE, "/etc/passwd"),
    (tarfile.SYMTYPE, "../../../escape"),
    (tarfile.SYMTYPE, "LICENSE"),
    (tarfile.LNKTYPE, "/etc/passwd"),
    (tarfile.LNKTYPE, "{base}/LICENSE"),
])
def test_refuses_symlinks_and_hardlinks(tmp_path, kind, link):
    def hook(base, members):
        info, _ = member(f"{base}/apps/link", kind=kind, link=link.format(base=base))
        return members + [(info, None)]

    assert "symlink or hardlink" in refused(make_release(tmp_path, members_hook=hook))


def test_refuses_file_written_through_a_symlinked_directory(tmp_path):
    def hook(base, members):
        link, _ = member(f"{base}/apps/out", kind=tarfile.SYMTYPE, link="/tmp")
        return members + [(link, None), member(f"{base}/apps/out/escape.txt", b"owned\n")]

    assert "symlink or hardlink" in refused(make_release(tmp_path, members_hook=hook))


@pytest.mark.parametrize("kind", [tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.CONTTYPE])
def test_refuses_special_members(tmp_path, kind):
    def hook(base, members):
        info, _ = member(f"{base}/apps/special", kind=kind)
        return members + [(info, None)]

    assert "not a regular file or directory" in refused(make_release(tmp_path, members_hook=hook))


def test_refuses_case_collisions_duplicates_and_file_directory_clashes(tmp_path):
    assert "case-colliding" in refused(make_release(tmp_path, members_hook=add(("license", b"x\n")), name="a"))
    assert "case-colliding" in refused(make_release(tmp_path, members_hook=add(("LICENSE", b"x\n")), name="b"))
    clash = add(("apps/api/main.py/inner.py", b"x\n"))
    assert "also used as a directory" in refused(make_release(tmp_path, members_hook=clash, name="c"))


@pytest.mark.parametrize("mode", [0o4755, 0o2755, 0o1755, 0o777, 0o666, 0o600])
def test_refuses_unexpected_file_modes(tmp_path, mode):
    message = refused(make_release(tmp_path, members_hook=add(("apps/api/tool.py", b"x\n", mode))))
    assert "unexpected file mode" in message


def test_extract_refuses_existing_destination_symlinked_parent_and_unverified_input(tmp_path):
    release = make_release(tmp_path)
    verified = rv.verify_release(release.manifest_path, release.artifact_path, policy(release))
    (tmp_path / "stage" / "taken").mkdir(parents=True)
    with pytest.raises(VerificationError):
        rv.extract(verified, tmp_path / "stage" / "taken")
    assert list((tmp_path / "stage" / "taken").iterdir()) == []

    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "linked").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(VerificationError):
        rv.extract(verified, tmp_path / "linked" / "v1")
    assert list((tmp_path / "elsewhere").iterdir()) == []

    with pytest.raises(VerificationError):
        rv.extract({"files": verified.files}, tmp_path / "stage" / "fake")


def test_refuses_symlinked_manifest_or_artifact(tmp_path):
    release = make_release(tmp_path)
    link = tmp_path / "link.manifest.json"
    link.symlink_to(release.manifest_path)
    with pytest.raises(VerificationError, match="cannot open release manifest"):
        rv.verify_release(link, release.artifact_path, policy(release))
    art_link = tmp_path / "link.tar.gz"
    art_link.symlink_to(release.artifact_path)
    with pytest.raises(VerificationError, match="cannot open release artifact"):
        rv.verify_release(release.manifest_path, art_link, policy(release))


# --- size limits ---------------------------------------------------------------------------


def test_refuses_oversize_artifact(tmp_path, monkeypatch):
    release = make_release(tmp_path)
    monkeypatch.setattr(rv, "MAX_ARTIFACT_BYTES", release.artifact_path.stat().st_size - 1)
    assert "larger than" in refused(release)


def test_refuses_oversize_manifest(tmp_path, monkeypatch):
    release = make_release(tmp_path)
    monkeypatch.setattr(rv, "MAX_MANIFEST_BYTES", 100)
    assert "release manifest is larger than" in refused(release)


def test_refuses_oversize_member_listed_or_not(tmp_path, monkeypatch):
    monkeypatch.setattr(rv, "MAX_FILE_BYTES", 1024)
    listed = make_release(tmp_path, extra_files={"apps/web/dist/big.js": (b"x" * 2048, 0o644)}, name="a")
    assert "file size out of range" in refused(listed)
    unlisted = make_release(tmp_path, members_hook=add(("apps/web/dist/big.js", b"x" * 2048)), name="b")
    assert "per-file size limit" in refused(unlisted)


def test_refuses_decompression_bomb(tmp_path, monkeypatch):
    release = make_release(tmp_path, members_hook=add(("apps/web/dist/zeros.bin", b"\0" * (4 << 20))))
    assert release.artifact_path.stat().st_size < 64 * 1024  # small on disk, large when expanded
    monkeypatch.setattr(rv, "MAX_TOTAL_BYTES", 256 * 1024)
    monkeypatch.setattr(rv, "TAR_OVERHEAD_BYTES", 64 * 1024)
    assert "expands beyond the size limit" in refused(release)


def test_refuses_too_many_members(tmp_path, monkeypatch):
    monkeypatch.setattr(rv, "MAX_MEMBERS", 5)
    assert "too many archive members" in refused(make_release(tmp_path))


# --- version, channel and downgrade --------------------------------------------------------


def test_downgrade_needs_explicit_opt_in(tmp_path):
    release = make_release(tmp_path, version="1.2.0")
    assert "downgrades need explicit opt-in" in refused(release, policy(release, installed_version="1.3.0"))
    verified = rv.verify_release(release.manifest_path, release.artifact_path,
                                 policy(release, installed_version="1.3.0", allow_downgrade=True))
    assert verified.change == "downgrade"


def test_prerelease_of_installed_version_counts_as_downgrade(tmp_path):
    release = make_release(tmp_path, version="1.3.0-rc.1")
    message = refused(release, policy(release, installed_version="1.3.0", allow_prerelease=True))
    assert "downgrades need explicit opt-in" in message


def test_reinstall_needs_explicit_opt_in(tmp_path):
    release = make_release(tmp_path, version="1.2.0")
    assert "already installed" in refused(release, policy(release, installed_version="1.2.0"))
    verified = rv.verify_release(release.manifest_path, release.artifact_path,
                                 policy(release, installed_version="1.2.0", allow_reinstall=True))
    assert verified.change == "reinstall"


def test_prerelease_needs_explicit_opt_in(tmp_path):
    release = make_release(tmp_path, version="1.3.0-rc.1")
    assert "prereleases need explicit opt-in" in refused(release)
    verified = rv.verify_release(release.manifest_path, release.artifact_path, policy(release, allow_prerelease=True))
    assert (verified.channel, verified.change) == ("prerelease", "upgrade")


def test_dev_build_is_never_an_update_candidate_by_default(tmp_path):
    release = make_release(tmp_path, eligible=False)
    assert "dev build" in refused(release)
    assert rv.verify_release(release.manifest_path, release.artifact_path, policy(release, allow_dev=True))


def test_refuses_version_other_than_the_selected_release(tmp_path):
    release = make_release(tmp_path, version="1.2.0")
    assert "not the selected 1.2.1" in refused(release, policy(release, expected_version="1.2.1"))


def test_refuses_channel_that_does_not_match_version(tmp_path):
    def stable(m):
        m["channel"] = "stable"

    release = make_release(tmp_path, version="1.3.0-rc.1", manifest_hook=stable)
    assert "channel does not match" in refused(release, policy(release, allow_prerelease=True))


def test_semantic_version_precedence():
    ordered = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2",
               "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0", "1.0.1", "1.9.0", "1.10.0", "2.0.0"]
    for low, high in zip(ordered, ordered[1:]):
        assert rv.compare_versions(low, high) == -1
        assert rv.compare_versions(high, low) == 1
    assert rv.compare_versions("1.2.3", "1.2.3") == 0
    for bad in ("01.0.0", "1.0", "v1.0.0", "1.0.0+build.1", "1.0.0-rc..1", "1.0.0-", "1.0.0-01", " 1.0.0"):
        with pytest.raises(ValueError):
            rv.parse_version(bad)


# --- authenticity and manifest structure --------------------------------------------------


def test_refuses_without_an_authenticity_check(tmp_path):
    release = make_release(tmp_path)
    assert "no authenticity check is configured" in refused(release, policy(release, authenticator=None))


def test_refuses_wrong_pinned_digest(tmp_path):
    release = make_release(tmp_path)
    assert "pinned digest" in refused(release, policy(release, authenticator=PinnedDigest("0" * 64, "test")))
    with pytest.raises(ValueError):
        PinnedDigest("not-a-digest", "test")


def test_unexpected_errors_fail_closed(tmp_path):
    release = make_release(tmp_path)

    def broken(manifest, signature):
        raise RuntimeError("boom")

    assert "could not complete (RuntimeError)" in refused(release, policy(release, authenticator=broken))
    assert "returned no result" in refused(release, policy(release, authenticator=lambda m, s: ""))


def test_refuses_duplicate_keys_unknown_keys_and_non_finite_numbers(tmp_path):
    release = make_release(tmp_path)
    artifact = release.artifact_path.read_bytes()
    for raw in (release.manifest_bytes.replace(b'"schema": ', b'"schema": "x", "schema": ', 1),
                canonical({**release.manifest, "install_hook": "curl | sh"}),
                release.manifest_bytes.replace(b'"size": ', b'"size": NaN, "x": ', 1)):
        with pytest.raises(VerificationError):
            rv.verify_bytes(raw, None, artifact, policy(release, authenticator=PinnedDigest(sha(raw), "t")))


def test_refuses_unsupported_policy(tmp_path):
    release = make_release(tmp_path)
    assert "not a supported product and platform" in refused(release, policy(release, platform=OTHER_PLATFORM))
    assert "installed_version is not a semantic version" in refused(release, policy(release, installed_version="x"))


@pytest.mark.skipif(SSH_KEYGEN is None, reason="system ssh-keygen is not installed")
class TestSshSignature:
    def keypair(self, tmp_path: Path, name: str) -> tuple[Path, str]:
        key = tmp_path / name
        subprocess.run([SSH_KEYGEN, "-q", "-t", "ed25519", "-N", "", "-C", "synthetic", "-f", str(key)],
                       check=True, capture_output=True, timeout=30)
        key_type, key_data = (tmp_path / f"{name}.pub").read_text().split()[:2]
        return key, f"{key_type} {key_data}"

    def sign(self, key: Path, path: Path, namespace: str = SshSignature.NAMESPACE) -> Path:
        sig = path.with_name(path.name + ".sig")
        sig.unlink(missing_ok=True)
        subprocess.run([SSH_KEYGEN, "-Y", "sign", "-f", str(key), "-n", namespace, str(path)],
                       check=True, capture_output=True, timeout=30)
        return sig

    def setup(self, tmp_path: Path):
        release = make_release(tmp_path)
        key, public = self.keypair(tmp_path, "release_key")
        signers = tmp_path / "allowed_signers"
        signers.write_text(f"release@synthetic.invalid {public}\n")
        signers.chmod(0o644)
        trust = policy(release, authenticator=SshSignature(signers, "release@synthetic.invalid"))
        return release, key, signers, trust

    def test_valid_signature_is_accepted(self, tmp_path):
        release, key, _, trust = self.setup(tmp_path)
        sig = self.sign(key, release.manifest_path)
        verified = rv.verify_release(release.manifest_path, release.artifact_path, trust, signature_path=sig)
        assert verified.authenticity == "ssh-signature (release@synthetic.invalid)"

    def test_missing_signature_is_refused(self, tmp_path):
        release, _, _, trust = self.setup(tmp_path)
        assert "no SSH signature" in refused(release, trust)

    def test_signature_by_an_untrusted_key_is_refused(self, tmp_path):
        release, _, _, trust = self.setup(tmp_path)
        other, _ = self.keypair(tmp_path, "other_key")
        sig = self.sign(other, release.manifest_path)
        assert "not valid" in refused(release, trust, signature_path=sig)

    def test_signature_in_another_namespace_is_refused(self, tmp_path):
        release, key, _, trust = self.setup(tmp_path)
        sig = self.sign(key, release.manifest_path, namespace="file")
        assert "not valid" in refused(release, trust, signature_path=sig)

    def test_manifest_changed_after_signing_is_refused(self, tmp_path):
        release, key, _, trust = self.setup(tmp_path)
        sig = self.sign(key, release.manifest_path)
        release.manifest_path.write_bytes(canonical(dict(release.manifest, version="9.9.9")))
        assert "not valid" in refused(release, trust, signature_path=sig)

    def test_wrong_signer_identity_is_refused(self, tmp_path):
        release, key, signers, _ = self.setup(tmp_path)
        sig = self.sign(key, release.manifest_path)
        trust = policy(release, authenticator=SshSignature(signers, "someone@synthetic.invalid"))
        assert "not valid" in refused(release, trust, signature_path=sig)

    def test_writable_or_symlinked_signers_file_is_refused(self, tmp_path):
        release, key, signers, trust = self.setup(tmp_path)
        sig = self.sign(key, release.manifest_path)
        signers.chmod(0o666)
        assert "writable by group or others" in refused(release, trust, signature_path=sig)
        signers.chmod(0o644)
        link = tmp_path / "signers_link"
        link.symlink_to(signers)
        linked = policy(release, authenticator=SshSignature(link, "release@synthetic.invalid"))
        assert "cannot open allowed signers file" in refused(release, linked, signature_path=sig)


def test_content_scan_flags_addresses_but_not_binary_like_runs_in_a_bundle():
    tool_path = REPO_ROOT / "scripts" / "release" / "release.py"
    if not tool_path.is_file():
        pytest.skip("release builder is not in this checkout")
    spec = importlib.util.spec_from_file_location("release_tool_scan", tool_path)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    # A real address is found (the allowed example domains are not), a minified-bundle run that merely
    # contains '@' between characters of any case is not.
    assert tool.scan_contents({"a.txt": b"contact someone@company.io for access"}, [])
    assert not tool.scan_contents({"a.txt": b"contact someone@example.com for access"}, [])
    assert not tool.scan_contents({"assets/x.js": b"_@Wl(g;u1Si/ebKu'B&!*Sh?eb@Wl'z@aPeb95Si.ebcpputyvjB)!,&a+0a"}, [])
