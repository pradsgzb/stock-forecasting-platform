# Git Workflow

## Branching

Use short-lived branches from a protected `main` branch:

- `feat/<scope>-<description>`
- `fix/<scope>-<description>`
- `docs/<description>`
- `chore/<description>`

## Commit format

Use Conventional Commits:

```text
<type>(<scope>): <imperative summary>

<body explaining motivation and notable design decisions>

<footer for breaking changes or issue references>
```

Allowed common types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`,
`chore`, and `revert`.

## Pull requests

- Keep a pull request focused on one coherent change.
- Require all CI checks and at least one code-owner review.
- Use squash merge for feature branches unless preserving individual commits has operational
  value.
- Never bypass branch protection for routine work.

## Release tags

Use signed semantic-version tags. Release notes must describe behavior changes, migration
steps, known limitations, and rollback guidance.
