# Verify a release by hand

**Status: read from source, not run on a Raspberry Pi.** The checks below are what the bootstrap and the helper
perform. Run them yourself before you trust a download.

## What a release contains

| Asset | Used by | Purpose |
|---|---|---|
| `rcd-X.Y.Z-linux-arm64.tar.gz` | bootstrap, updater | The application, `BUILD_INFO.json`, the lock and the helper sources |
| `rcd-X.Y.Z-linux-arm64.manifest.json` | bootstrap, updater | File list, sizes and digests. Schema `dashboard-release-manifest/v1` |
| `rcd-X.Y.Z-linux-arm64.manifest.json.sig` | CI signing job; fetch downloads it | Detached SSH signature over the manifest. **Not checked by the bootstrap**: see below |
| `SHA256SUMS` | you | Checksums for the assets above |

The release workflow publishes exactly these assets. Nothing else is attached.

## What the bootstrap checks

With `--manifest-sha256` (the digest you copy from the release page), the bootstrap runs these checks in order, and
refuses the package if any fails:

1. **Manifest digest.** The SHA-256 of the manifest file must equal the pinned digest.
2. **Manifest identity.** Schema `dashboard-release-manifest/v1`, product `rcd`, platform `linux-arm64`
   (`os: linux`, `arch: arm64`), and version `X.Y.Z` (or `X.Y.Z-pre`). Channel is `stable` or `prerelease`. A
   prerelease needs `--allow-prerelease`. `release_eligible` must be `true`, which means it was built from a clean
   committed tree.
3. **Archive size and digest.** The archive's byte length and SHA-256 must match the manifest's `artifact` entry.
4. **Archive members.** Only regular files and directories under `rcd-X.Y.Z-linux-arm64/`. The bootstrap refuses
   absolute paths, `..`, backslashes, setuid and setgid bits, links and devices. It caps the member count at 5,000.

The packaged helper then checks the package again during `stage`: every file's digest, size and mode, the dependency
lock and `BUILD_INFO.json`. That check runs in the helper, and has not been run on a Pi yet.

## Check the manifest digest by hand

Copy the digest from the GitHub release page for the manifest asset, then compare it with the file you downloaded:

```sh
sha256sum rcd-X.Y.Z-linux-arm64.manifest.json
```

The two values must be identical. A different value means a different manifest. Stop there.

## Check the archive by hand

```sh
sha256sum rcd-X.Y.Z-linux-arm64.tar.gz
```

Compare with the `artifact.sha256` field in the manifest. The manifest is JSON, so read it with a JSON tool
(`python3.11 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["artifact"])' <manifest>`). Use
`python3.11 -I`, not a bare `python3`, so that no script in the current directory is loaded.

If you have `SHA256SUMS`, check every asset in one step:

```sh
sha256sum -c SHA256SUMS
```

## The SSH signature is not checked yet

The updater's `ssh-signature` trust, with an `allowed_signers` file and namespace `dashboard-release`, is written in
the code. **No signing key exists, and the bootstrap does not use it.** The bootstrap uses `pinned-digest` only, so
the digest you copy from the release page is the only trust anchor. Both the source of that digest and the release
page are GitHub-hosted, so a compromised release page would defeat this check. Treat the digest as integrity only,
not as authenticity, until the trust-root decision is made.

## The published digest is not enough on its own

`GET /api/updates/check` shows the digest GitHub publishes for each asset. That value comes from the same release
as the asset, so it does not add a second, independent check.
