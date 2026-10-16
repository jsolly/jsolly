# Configuration

Relocatable tracked settings live here, grouped by the domain that owns them.
Each setting has one authoritative owner. This repository uses only `quality/`:
`quality/.markdownlint-cli2.jsonc` owns Markdownlint rules and ignore settings.
`scripts/lint-md.sh` selects it explicitly after changing to the repository root,
preserving command scope from any working directory.

Native exceptions remain at their required discovery paths: package manifests
and lockfiles, `.npmrc`, `.nvmrc`, `.mise.toml`, Git files, `.github/`, native agent
registrations and `.repo-independent.json`. Executable helpers and behavioral
instructions remain with their owners. Gitleaks continues to use its pinned
built-in rules; there is no repository-specific scanner configuration.

New relocatable settings belong in the relevant `config/<domain>/` directory;
create only domains this repository uses. Preserve effective roots, scopes,
imports and outputs when moving settings. Use supported minimal native adapters
when discovery requires them, and document the exception here.

Validate with `npm ci`, `npm run check:md` and the full `npm run gate`. This
repository requires no external configuration checkout, home links, generation
step or automatic synchronization.
