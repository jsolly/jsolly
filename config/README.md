# Configuration

Relocatable tracked settings live here, grouped by the domain that owns them.
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

New relocatable settings belong in the relevant `config/<domain>/` directory;
create only domains this repository uses. Preserve effective roots, scopes,
imports and outputs when moving settings. Select CLI configuration explicitly. Keep a minimal native adapter only for a
named active consumer without an equivalent supported path, and document it here.

Validate with `npm ci`, `npm run check:md` and the full `npm run gate`. This
repository requires no external configuration checkout, home links, generation
step or automatic synchronization.
