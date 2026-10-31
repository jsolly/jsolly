# Development and release

This repository owns its gate, setup, CI and deployment scripts. A separate
configuration repository, private package or global skill installation is not
required. Templates used during migration are examples, not an enforced upstream.

Prerequisites: Git, Bash >= 5 and Python >= 3.11. Install mise on non-Linux hosts;
fresh Linux setup provisions a pinned, checksum-verified public mise binary in
`/usr/local/bin`, using noninteractive sudo only when needed. The repository's `.mise.toml`
and `.nvmrc` own its tool pins. On a reviewed fresh `origin/main` checkout run:

```bash
bash scripts/setup-agent-environment.sh
```

Setup installs repo-owned hooks outside the working tree, provisions the pinned
tools and lockfile dependencies, and installs pinned Chromium when this repo uses
Playwright. Run the repo's documented quality gate with its pinned tools:

```bash
mise exec -- npm run gate
```

Use the repository's README and AGENTS.md for its build, test and deployment
commands. A missing prerequisite is a failed setup; report it rather than claiming
that the gate ran. No setup command deploys the application or infrastructure.

## Hook trust

The dispatcher lives in this clone's Git common directory, shared only by its
linked worktrees. It registers pre-commit only. The complete hook/library/setup
bundle must match current reviewed `origin/main`, or a deliberately approved exact
bundle digest. Missing files, symlinks, unreviewed modes and a foreign origin fail
closed. The dispatcher executes a verified snapshot, then runs quality scripts in
the committing checkout. Re-run reviewed setup after changing tool setup on main.

This is hook-registration integrity, not a sandbox. Never check out or execute
third-party/fork PR code in a trusted clone; review its diff through GitHub. Do not
run its npm lifecycle or setup scripts. Use a separate disposable environment when
execution of untrusted code has been explicitly authorized.

After independent semantic/security review of your own gate change, get its exact
digest with `bash scripts/repo-python.sh scripts/repo-hooks.py digest`. Use the installed snapshot's
`approve --root <absolute-repo-root> --digest <reviewed-digest>` command, with actual
values, to approve only those bytes; never approve a fork's bundle. Approvals are
repo-local. Revoke explicit approvals with `git config --local --unset-all
repo.trustedGateBundle`; current reviewed main remains trusted. Changing origin
invalidates the bundle identity. No environment variable selects another library.

The authoritative identity manifest is `config/agents/repository.json`. Current
checkouts refuse a retired root `.repo-independent.json`, including dangling links.
An installed snapshot from before this relocation needs the explicit upgrade flow.
After reviewing the complete candidate hook bundle, run from its repository root:

```bash
digest="$(bash scripts/repo-python.sh scripts/repo-hooks.py digest)" &&
  bash scripts/repo-python.sh scripts/repo-hooks.py approve-upgrade --digest "$digest" &&
  bash scripts/repo-python.sh scripts/repo-hooks.py install &&
  bash scripts/repo-python.sh scripts/repo-hooks.py verify
```

The upgrade reauthorizes the exact old installed snapshot against protected
`origin/main` or an existing repo-local approval, verifies its origin, files, modes,
digest and dispatcher, then approves only the reviewed new digest. It does not
trust an old manifest in the candidate checkout. Once reviewed main has the new
layout, ordinary setup installs it directly, including over a valid old snapshot.
Older checkouts must merge the reviewed migration before rerunning setup.

## Review and integration

Work from fresh main on an isolated branch. Review the actual final diff for bugs,
secrets, security, tests and repository guidelines; use an independent reviewer
for substantial or sensitive changes. Run the required complete local gate before
pushing. Create a same-repository PR; use a draft while approval/work remains.
Merge only when the required CI validates the exact current head. Never push to
the default branch, weaken rulesets, bypass checks or use an admin merge. Optional
personal review skills may help, but they are not prerequisites for this flow.

Preserve existing code-only Deploy, production-main-only Vercel and opt-in Preview
rules. Never trigger a preview merely to validate this migration. Verify the
intended deployment and exact-release smoke when the repository requires them.

## Infrastructure and access

This profile repository has no AWS stack, infrastructure checks or deployment.
Setup and gate use public tools and need no AWS login. Separately authorized AWS
reads use exactly one native production `aws_mcp` connection for
`agent@jsolly.com`, authorized as `AgentMcp` in account `730335616323`. Do not
install an agent AWS profile or credential-process helper, export OAuth
credentials, add a second MCP connection or bridge it into local CLI calls.
Preserve AWS Core for skills and public knowledge, named human administrator
profiles, and application/provider credentials.

Source cleanup does not remove installed helpers, cached sessions, saved provider
settings or live IAM trust. Provider isolation and legacy credential retirement
require their separate acceptance evidence. Agents do not recover credentials,
broaden grants or run destructive infrastructure/database operations.

Repository instructions and access rules are maintained here. Personal home
configuration and optional global skills remain separate and are not installed,
removed or overwritten by repo setup.

## Python tests

Run `mise exec -- npm run test:python` for the repository hook, bootstrap and
README link-checker regressions. The gate uses the same pytest 9.0.2 runner through uvx; mise pins uv.
The existing TestCase assertions, cleanup and subtests remain intact under
pytest. Direct unittest runner entrypoints have been retired.

## README health

`.github/workflows/readme-health.yml` runs `scripts/check-readme-links.py` weekly,
on manual dispatch, and on each push to main that changes the page, the checker or
the workflow. Every `href`, `src` and `srcset` in `README.md` must be an https URL
answering 2xx, and images must answer `image/*` (`mailto:` and `#` links are not
fetched). Write profile links as HTML
`<a href>` and images as `<img src>`: link forms the checker cannot verify fail
instead of passing unchecked, as its module docstring lists. The gate's Python
tests also parse the shipped `README.md` offline, so an unverifiable form fails
PR CI before it reaches main. Run the same check locally from the repository root:

```bash
bash scripts/repo-python.sh scripts/check-readme-links.py README.md
```

A broken reference fails the run, with the failures in an error annotation and the
job summary. Issues are disabled on this repository, so GitHub's failed-workflow
notification is the alert. GitHub sends it to the account that last changed the
workflow's `cron` line or, after a disable, to whoever re-enabled it. Only the
owner account (`jsolly`) should edit the schedule or re-enable the workflow, so
alerts keep reaching John.

GitHub disables scheduled workflows after 60 days without repository activity, and
a disabled workflow runs on no trigger, push included. If the Actions tab shows
README health as disabled, re-enable it there as `jsolly`, or run as `jsolly`:

```bash
gh workflow enable readme-health.yml --repo jsolly/jsolly
```
