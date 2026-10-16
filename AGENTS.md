# AGENTS.md

## Ship

Ship profile: `gate-only`

**Integration: branch → reviewed PR → merge on green `CI / ci`.** Follow [local release instructions](docs/development.md). Agents never push to `main`, change rulesets, or admin-merge.

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

This repo owns `gate/gate-lib.sh` and `scripts/repo-hooks.py`. Run reviewed
`scripts/setup-agent-environment.sh` on main to install its outside-worktree
pre-commit dispatcher. Never set hooksPath to `.git-hooks`: a branch could then
register executable hooks. See [development and release](docs/development.md).

## Local UI verification

No local server or build: GitHub renders `README.md`. Once `/ship` pushes, review the pushed head at
`https://github.com/jsolly/jsolly/blob/<head-sha>/README.md` in the harness browser (the SHA URL
survives the squash merge's branch deletion; the loopback-only smoke fallback cannot reach
github.com). After merge, the live page is <https://github.com/jsolly>. No auth. Check that the profile content renders and its images and links remain usable;
record the inspected head and live URL in the release report.
The fleet No-CDN rule is n/a here: GitHub strips `<script>` and `<style>` from rendered READMEs.

## AWS

n/a — no AWS resources or deployment. Cloud setup installs repo-pinned public
tools and hooks and does not run `.cursor/aws-oidc-login.sh` or require AWS login.

## Verified-tree CI

PRs run the full CI suite. Post-merge CI reuses a successful PR run only when
its recorded checkout tree exactly matches the landed tree, using
the repo-owned `scripts/ci-verified-tree.sh`. Missing proof runs full CI;
manual runs always validate. Job names and deployment triggers stay intact.
Canonical contract: [local CI helper](scripts/ci-verified-tree.sh).

## Dependabot CI

Dependabot PR events allocate no validation runners until an explicitly
authorized maintenance run applies the `ow-ci` label. Only the `labeled` event
that adds `ow-ci` runs the real `ci` check. A later Dependabot push defers again
until a drain re-kicks the new head (remove, then re-add `ow-ci`). Deferred runs
report `ci-deferred` and cannot satisfy the required `ci` check. Skipped or
absent checks never authorize a dependency merge. See the Dependabot CI kick in
the repository CI workflow and local release instructions.

## Configuration

Relocatable tracked settings live under `config/<domain>/`, with one owner per
setting. See [configuration guidance](config/README.md) for native exceptions
and verification. This repository owns its configuration and consumers.

## Repository ownership

This repo maintains its executable helpers, agent instructions and workflow
contracts. Changes in another repo do not automatically rewrite this one. A
cross-repository migration needs the user's explicit scope, independent review,
and a separate verified PR in each affected repository.

## Agent environment

Use this repository's AGENTS.md and [development guide](docs/development.md).
Run its reviewed `scripts/setup-agent-environment.sh` for pinned tools and hooks.
No private configuration repo, external instruction import or global skill is
required. Optional personal skills do not change this repository's authority.
