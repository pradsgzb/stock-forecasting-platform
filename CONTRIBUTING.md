# Contributing

## Development workflow

1. Create a short-lived branch from `main`.
2. Add or update tests before changing behavior.
3. Run `make check` or `./scripts/check.ps1`.
4. Use Conventional Commits.
5. Request review from the owner of the affected module.
6. Do not merge with failing checks or unresolved security findings.

## Engineering rules

- Domain code must not import adapters, Pydantic, pandas, or infrastructure frameworks.
- Time-dependent behavior must accept a `Clock` or an explicit timestamp.
- Financial values must never use binary floating point.
- External identifiers and symbols must be effective-dated.
- No silent fallback from one exchange calendar to another.
- Every production defect requires a regression test.
- Do not commit real market-data credentials or licensed datasets.

See `docs/engineering/coding-standards.md` and `docs/engineering/git-workflow.md`.
