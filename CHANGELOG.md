# Changelog

## 2026-11-22

- Remove the `auto-merge.yml` workflow, its `AUTO_MERGE_TOKEN` use and its probe note. Each agent now arms native squash auto-merge on its own reviewed pull request, and GitHub merges it on green `ci` and `security`.

## 2026-11-17

- Run all six math compatibility scenarios through the existing Vitest suite and remove the separate Node test runner and gate step. Bound bootstrap downloads and test timeout refusal.
