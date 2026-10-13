# Versioning and the standard footer (MCD and RCD)

## What the footer shows

```
© 2026 Raspberry Pi Control Dashboard · Bamcio LLC
v0.2.0 • production • api 48b68fe · web 48b68fe
```

- Product and owner come from the running app (`product_name`, `organization_name`), so the Mac Control
  Dashboard (MCD) reads "© 2026 Mac Control Dashboard · Bamcio LLC" with the same layout.
- `v0.2.0` is the version, `production` or `local` the environment, then the short commit of the API
  and of the web bundle. Two equal values mean both halves are current; different values mean a
  half-finished roll.
- `• modified` appears when tracked files differ from the commit named, so a running build can always
  be told from the commit it claims. `• migrations` appears while a database migration is pending.
- The owner is configuration, not code: `MAC_CONTROL_ORGANIZATION_NAME="Bamcio LLC"` in
  `~/.rcd-control/.env`. The public default stays neutral for forks.

## One version, one source

- `apps/api/version.py` holds `__version__`. `apps/web/package.json` carries the same number; a test
  fails if they differ.
- A release is the tag `v<version>` on the commit that carries that version. The footer's commit
  must be that commit or a descendant when the build is `modified`.

## MCD and RCD move together

MCD and RCD share **major.minor**: that pair is the feature level. If MCD is 0.2.x, RCD is 0.2.x
and has the same features. The patch number is each product's own fixes. A feature lands in both
products before the minor is raised, and a release note lists what the feature level contains.

| Feature level | Contents |
|---|---|
| 0.2 | Branch-scoped agent git access; subscription limits (lift time, one notice, same-grade reroute, Discord status); context digests with a full ledger file and a cache-friendly prompt order; deletable duplicate project cards; the standard footer with a modified marker; failure mining for Hermes; the release flow scripts. RCD reaches 0.2 when it has all of these. |

## Am I on the latest?

1. Read the footer or `/healthz`: version and commit.
2. Compare the commit with the head of the branch or tag you expect (`git ls-remote`, or the GitHub
   branch page). The same commit on `api` and `web` and no `modified` means that build is exactly
   that commit.
3. An installed release records its version and commit in its install receipt; the in-app updater
   (Settings, Application update) compares it with the latest GitHub release.
