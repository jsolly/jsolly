# AGENTS.md

## Ship

Ship profile: `gate-only`

**Integration: branch → PR → merge on green `CI / ci`.** `/ship` merges per `skills/ship/references/git-discipline.md` → Merge a same-repo self PR (read the installed `/ship` reference). Agents never push to `main`, change rulesets, or admin-merge.

Local gate before push: `npm run gate` (full working-tree checks, including an empty index).

**Deploy:** `none` — GitHub renders `README.md` on the [github.com/jsolly](https://github.com/jsolly) profile straight from `main`; there is no deploy step or release-id probe.

## Purpose

John's GitHub profile README. `README.md` is the whole page: HTML plus remote images, with no local image files in the repo.

## Commands

```bash
npm ci                              # gate tooling (markdownlint; pinned Actions binaries)
npm run gate                        # full local gate, including an empty index
npm run check:md                    # markdown lint
npm run check:actions               # actionlint + shellcheck
```

## Git hooks

`core.hooksPath` is the dotagents dispatcher `~/.local/share/dotagents/hooks`, installed and set by the dotagents installers. Never point it at `.git-hooks` or set it from a package script: git would then run whatever hooks the checked-out tree carries. The dispatcher serves only `pre-commit`, and runs this repo’s tracked `.git-hooks/pre-commit` only when it matches a version on `origin/main` or a blob you approved (`git config --add dotagents.trustedHook <blob>`, printed by the refusal; approve only your own edit). Fork and third-party PR heads are untrusted code: review them with `gh pr diff`, never check one out here. Canon: dotagents `rules/agent-cloud-access.md` → GitHub.

## Local UI verification

No local server or build: GitHub renders `README.md`. Once `/ship` pushes, review the pushed head at
`https://github.com/jsolly/jsolly/blob/<head-sha>/README.md` in the harness browser (the SHA URL
survives the squash merge's branch deletion; the loopback-only smoke fallback cannot reach
github.com). After merge, the live page is <https://github.com/jsolly>. No auth. Follow `~/code/dotagents/rules/frontend-verification.md` (`/verify-ui` where installed).
The fleet No-CDN rule is n/a here: GitHub strips `<script>` and `<style>` from rendered READMEs.

## AWS

n/a — no AWS resources or deploy. The Cloud `environment.json` install is skills-only and does not
run `.cursor/aws-oidc-login.sh`, so the `.cursor/CLOUD.md` "AWS reads" setup (AWS CLI,
`AWS_PROFILE=agent-readonly`) is absent on this repo's Cloud Agents.

## Verified-tree CI

PRs run the full CI suite. Post-merge CI reuses a successful PR run only when
its recorded checkout tree exactly matches the landed tree, using
`scripts/ci-verified-tree.sh` from dotagents. Missing proof runs full CI;
manual runs always validate. Job names and deployment triggers stay intact.
Canonical contract: `~/code/dotagents/templates/github/verified-tree-ci.md`.

## Dependabot CI

Dependabot PR events allocate no validation runners until a manually invoked
`/optimize-workspaces drain` applies the `ow-ci` label. Only the `labeled` event
that adds `ow-ci` runs the real `ci` check. A later Dependabot push defers again
until a drain re-kicks the new head (remove, then re-add `ow-ci`). Deferred runs
report `ci-deferred` and cannot satisfy the required `ci` check. Skipped or
absent checks never authorize a dependency merge. See the Dependabot CI kick in
the canonical `dotagents/skills/optimize-workspaces/references/pr-drain.md`.

## Fleet rollout

Changes inside this repo ship normally. For changes other repos must adopt, link the merged PR on the one existing dotagents Todoist fleet-rollout task. Do not start that rollout or spawn per-repo chips, PRs or tasks from here. John authorizes one lead to walk the fleet after canon settles. Follow the installed `persist-todos-in-todoist` skill → Fleet rollout.
