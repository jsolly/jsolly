# Configuration

This directory groups the repository's quality and hook settings by owner.
Each setting has one authoritative owner. `quality/` contains lint settings:
`quality/.markdownlint-cli2.jsonc` owns Markdownlint rules and ignore settings.
`scripts/lint-md.sh` selects it explicitly after changing to the repository root,
preserving command scope from any working directory.

Native exceptions remain at their required discovery paths: package manifests
and lockfiles, `.npmrc`, `.nvmrc`, `.mise.toml`, Git files, `.github/`, native agent
registrations. Executable helpers and behavioral
instructions remain with their owners. Gitleaks continues to use its pinned
built-in rules; there is no repository-specific scanner configuration.

Repository-owned hook identity and its fixed trusted-bundle roster live at
`config/agents/repository.json`. Current checkouts require this owner and refuse a
retired root `.repo-independent.json`, including a dangling link. The hook helper
supports an explicit reviewed upgrade from a bounded authenticated old installed
snapshot; [hook trust](../docs/development.md#hook-trust) describes the procedure.
No current-checkout legacy fallback or duplicated owner is retained.

Move optional root-level settings to the relevant `config/<domain>/` directory
or their natural owner. Preserve valid existing nested, component-owned and
tool-owned configuration; test configuration may live under `tests/`. Create only
domains this repository uses. Read the pinned tool's official configuration
documentation and preserve effective roots, scopes, imports and outputs when
moving settings. Prove that the actual consumers apply them. Select supported CLI
paths explicitly. Keep a minimal native adapter only for a named active consumer
without an equivalent supported path, and document it here.

Validate with `npm ci`, `npm run check:md` and the full `npm run gate`. This
repository requires no external configuration checkout, home links, generation
step or automatic synchronization.

`python/pytest.ini` owns Python test discovery: the `test-*.py` hook fixtures and
the README link-checker tests. `npm run test:python` selects it explicitly.
