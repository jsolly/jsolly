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
Git replacement objects cannot hide the actual pushed commits.

Semgrep `p/default` and OSV run in `Security / security` on PRs and main,
including Dependabot PRs. Semgrep findings fail through `--error`; telemetry and
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
developing a reviewed hook change; do not register branch-owned hooks directly.

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

## Initial findings

The first actual scan blocked on existing source and lockfile findings. These
remain visible and are not accepted risks or suppressed rules. Keep the rollout
PR as a draft until they have reviewed dispositions or fixes.

Semgrep flags the missing npm release-age policy and the README link checker's
dynamic `urllib.request.urlopen` call. The latter needs a review of its existing
HTTPS validation and redirect behavior before deciding whether to change code
or approve a narrow audit disposition.

OSV reports five advisories across three development dependencies:

- `katex@0.16.47`: GHSA-238p-pmpm-9mq7, fixed in 0.18.2.
- `markdown-it@15.0.1`: GHSA-gfr2-rv44-r23c, GHSA-r7fv-28h4-cvq7 and
  GHSA-vfgh-jcmw-g37q, all fixed by 15.0.3.
- `smol-toml@1.8.0`: GHSA-r4xh-jqrq-34v2, fixed in 1.9.0.

KaTeX's fixed version crosses its existing parent's declared range. This scanning
PR does not force that upgrade, change npm policy or inherit another repository's
risk acceptance. Dependency remediations need their own compatibility evidence.
