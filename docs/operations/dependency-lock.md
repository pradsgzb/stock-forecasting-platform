# Dependency Lockfile Release Gate

## Policy

`pyproject.toml` defines reviewed compatibility ranges. A committed `uv.lock` is mandatory
before a tagged release or production deployment. The lockfile captures the exact transitive
resolution across supported Python versions and platforms.

The generated source package deliberately does not contain a hand-written or synthetic
lockfile. Lockfiles are resolver output and must never be fabricated or edited manually.

## Generate and verify

Run these commands on a networked workstation or CI runner with Python 3.13 or 3.14 available:

```bash
uv lock --python 3.13
uv lock --check
uv sync --locked --all-groups
uv run --locked ruff format --check src tests
uv run --locked ruff check src tests
uv run --locked pyright
uv run --locked pytest --cov=stock_predictor --cov-report=term-missing
uv run --locked pip-audit
uv build --locked
```

Commit `uv.lock` in the same pull request as any dependency change. Review the resolved
version diff and the dependency-audit result before merging.

## Production hardening after the lockfile is committed

Use lock-enforcing commands in release paths:

```bash
uv sync --locked --no-dev --no-editable
uv run --locked stock-predictor doctor
```

The production Dockerfile already requires the committed lockfile and uses `--locked`.
Do not tag a release or build a production image while dependency resolution remains implicit.
