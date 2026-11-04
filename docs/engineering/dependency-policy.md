# Dependency and Compatibility Policy

## Selection criteria

A production dependency must have a clear purpose, active maintenance, compatible licensing,
supported Python versions, a documented security process, and a replaceable boundary when it
controls strategic behavior.

## Version policy

- Direct dependencies use bounded compatible ranges in `pyproject.toml`.
- A generated `uv.lock` pins the full transitive graph for reproducible CI and development.
- Dependency upgrades occur through reviewed pull requests.
- Major upgrades require an ADR or recorded impact assessment.
- Production images use the lockfile with `--frozen`.
- The project tests Python 3.13 and 3.14 during the compatibility period; Python 3.14 is the
  preferred production runtime.

## Current strategic dependencies

- **Pydantic / pydantic-settings:** configuration boundary only.
- **exchange_calendars:** adapter only; never imported by domain or application layers.
- **pandas:** declared directly because the calendar adapter imports its timestamp types; it remains outside the domain and application layers.
- **pytest:** executable behavior specifications.
- **Ruff:** formatting and linting.
- **Pyright:** strict static type checking.
- **SQLAlchemy / Alembic:** transactional persistence and controlled schema migrations.
- **FastAPI / Uvicorn:** authenticated internal API adapter and runtime.
- **PyJWT:** explicit bearer-token verification boundary.
- **Prometheus client / OpenTelemetry:** replaceable metrics and tracing adapters.
- **Bandit / Trivy / pip-audit / CodeQL:** layered source, dependency, secret, configuration,
  container, and workflow security evidence.

## Lockfile handling

The lockfile must be generated on a networked development or CI machine with:

```bash
uv lock --upgrade
uv sync --frozen --all-groups
```

A lockfile change must be reviewed together with the dependency diff and vulnerability scan.
