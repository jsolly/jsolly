# AGENTS.md

## Ship

Ship profile: `gate-only`

**Integration: branch → PR → merge on green `CI / ci`.** `/ship` opens the PR,
arms native auto-merge as the backstop where the base branch's ruleset requires
`ci`, and runs the head-pinned squash itself as soon as `ci` passes on the head
(`~/code/dotagents/skills/ship/references/git-discipline.md` → Merge a same-repo self PR).
Agents never push to `main`, change rulesets, or admin-merge.

**CI owner: local.** Agent runs the full local gate before push; `/ship` babysits
GitHub CI on the PR until merge (watch failures and fix forward). There is no
fire-and-forget path.

Local gate before push: `npm run gate` (full working-tree checks, including an empty index).

**Deploy:** `no-http-release-id (n/a)` — GitHub renders `README.md` on the [github.com/jsolly](https://github.com/jsolly) profile straight from `main`; there is no deploy step or release-id probe.

## Purpose

John's GitHub profile README. `README.md` is the whole page: HTML plus remote images, with no local image references. `assets/` holds images the README does not reference (none since 8f38963).

## Commands

```bash
npm ci                              # gate tooling (markdownlint, actionlint)
npm run gate                        # full local gate, including an empty index
npm run check:md                    # markdown lint
npm run check:actions               # actionlint + shellcheck
```

Git hooks: `git config core.hooksPath .git-hooks` (set once per clone).

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
