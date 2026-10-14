# Production release signatures

Version 0.3.1 is the first production release. Both products sign manifest bytes with the dedicated Ed25519 release key, namespace `dashboard-release`, identity `dashboard-release`. Its public fingerprint is `SHA256:CV1+p0B/fa4k3eDVXkZSoph1/Mkrth9v0jBg6Z9WOW8`. Only the public key is committed in [allowed_signers](allowed_signers); private signing material stays outside the repository and in the GitHub release-signing secret.

Download the archive, manifest, detached `.manifest.json.sig` and SHA256SUMS from the product’s GitHub release. Verify the signature against a separately trusted copy of allowed_signers before installing:

```sh
ssh-keygen -Y verify -f packaging/allowed_signers -I dashboard-release -n dashboard-release -s PRODUCT.manifest.json.sig < PRODUCT.manifest.json
```

Replace PRODUCT with the release file stem. Compare the public fingerprint through a trusted maintainer/source channel when establishing the first trust pin. A public key downloaded only alongside an untrusted artifact is not independent proof. Installer digest pinning and updater authenticity checks remain unchanged; this release setup does not bypass them. User-owned provider sign-ins and live-task testing remain separate from package signing.
