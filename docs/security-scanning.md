# Repository security checks

The repository retains staged gitleaks and the complete pre-commit quality gate.
Zizmor checks workflow security before commits. The installed dispatcher registers
both pre-commit and pre-push from an outside-worktree, verified snapshot.
`gate/security-scan.py` is part of that trusted bundle.

Pre-push runs only gitleaks on outgoing commits. It checks every pushed ref,
including commits created with hooks bypassed. Pinned built-in gitleaks rules
are explicit; repository config, ignore files and inline allow comments cannot
suppress findings. Required secret checks refuse a root `.gitleaksignore`,
which the pinned gitleaks loads even with an explicit ignore-path flag. Only the destination's advertised old commit determines excluded history. Cached
tracking refs may be stale and are never exclusions. New refs scan their complete
reachable history. Deletions send no commits. Malformed
input, scanner failure, non-commit targets and outgoing octopus merges fail.
Git replacement objects cannot hide the actual pushed commits. The pre-push
entry verifies the complete installed snapshot and repository identity before
sourcing its library.

Semgrep `p/default` and OSV run in `Security / security` on PRs and main,
with Dependabot validation deferred until an authorized `ow-ci` label event,
matching the existing CI policy. Every later bot update needs a fresh kick.
Semgrep findings fail through `--error`; telemetry and
version checks are disabled. The service-managed rules can change independently
of the pinned CLI. Tests are included, repository ignore files cannot remove
Semgrep targets, and only generated `node_modules` is explicitly excluded.
Parser warnings remain visible and do not establish complete language coverage.
OSV reads `package-lock.json` with an empty external config and all findings
enabled. This repository has no inherited risk exceptions.

The existing `CI / ci` job still owns the gitleaks history scan, before any
repository code runs. It is extended with SHA-pinned Actions and disabled
persisted checkout credentials. The Security job also uses SHA-pinned Actions,
read-only repository permission, and no AWS credentials. No duplicate CI
gitleaks job is added. A failed security job blocks only when GitHub rulesets
require it; committing a workflow does not establish that setting.

Cursor's native `.cursor/hooks.json` registers a `beforeShellExecution` gate
with `failClosed: true`. It scans tracked and unignored working files plus staged
blobs independently, so a safe working copy cannot conceal a staged secret.
Symlink escapes, invalid input, missing scanners and nonzero scanner exits deny
execution. This is a development guard, not a sandbox against arbitrary shell
code, deliberate hook bypass, or secrets in ignored files and environment
variables. Native Cursor execution needs separate verification in Cursor.

## Installation and verification

After review and merge, run the existing
`bash scripts/setup-agent-environment.sh` on reviewed main. Setup installs both
Git hooks and mise-pinned gitleaks, uv and OSV. Python scanner versions are pinned
in the trusted runner and resolved through uvx when invoked. Network access is
needed for initial tool resolution, Semgrep rules and OSV advisory queries.
Unavailable tools and services fail the relevant check.

Existing pre-push-free installations stay intact until the new bundle is
reviewed and installed. The helper accepts their exact historical roster only
for installed-snapshot verification and upgrade, never as current source trust.
Use the [exact-digest approval procedure](development.md#hook-trust) when
developing a reviewed hook change. For this roster transition, use the reviewed
candidate helper as described there; do not register branch-owned hooks directly.

Run `npm run gate` for the complete local gate and regression tests.
Run `python3 -I gate/security-scan.py ci` for Semgrep, OSV and zizmor.
Gitleaks history scanning remains in CI, and local outgoing scans run on push.
Tests exercise real Git history and real gitleaks, including bypassed commits,
multiple refs, range exclusion, malformed input, staged/worktree divergence and
Cursor denial. Protocol tests do not prove native Cursor installation.

This profile repository has no CFN or CDK. cfn-lint, cdk-nag and Checkov on
`cdk.out` do not apply. Dependabot covers npm and GitHub Actions with a seven-day
proposal cooldown. Socket Free installation and required-check settings remain
human/account acceptance steps; neither is inferred from this configuration.

## Remediation and compatibility

The initial scan found two Semgrep audit matches and five advisories across
three development dependencies. The shipping candidate fixes those findings
without suppressions or accepted vulnerabilities.

The npm policy sets `min-release-age=7`. `.mise.toml` and `.nvmrc` pin Node
24.22.2, which includes npm 11.19.1 and supports that policy. Lockfile installs
remain reproducible; the age policy applies when resolving new package versions.

The README checker now uses an explicit HTTP(S) opener with no file, data or FTP
handler. It validates the initial URL and every redirect, keeping HTTPS-only
production requests and normal certificate verification. Loopback tests enable
HTTP explicitly. Tests cover non-web targets, same-scheme redirects, HTTPS
downgrade prevention and bounded redirect loops.

Markdownlint CLI 0.24.0 supplies patched `markdown-it@15.0.3` and
`smol-toml@1.9.1`. A scoped `markdownlint` override updates its pinned
`re2js` from 2.8.6 to the patched 2.8.7 for GHSA-gg6h-894w-4m9c. Its math extension still declares KaTeX `^0.16.0`, whose latest
release is affected by GHSA-238p-pmpm-9mq7. A scoped override selects
`micromark-extension-math`'s KaTeX 0.18.2, outside that declared range.
`npm run test:math`, included in the complete gate, verifies the actual parent's
resolved KaTeX version, inline and block rendering, malformed input, untrusted
commands, bounded macro expansion and Markdownlint's handling of math tokens.
The override changes development tooling only. Remove it when the parent
supports a patched release directly.
