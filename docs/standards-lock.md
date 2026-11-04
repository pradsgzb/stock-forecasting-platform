# Standards and Toolchain Lock

Last verified: **2026-11-03**

| Item | Selected baseline | Status | Rationale |
|---|---|---|---|
| Python | 3.14 preferred; 3.13 compatibility floor | Stable | Supported project runtime range; local verification uses 3.13.5. |
| Packaging metadata | PEP 621 `pyproject.toml` | Final | Standard project metadata and dependency declaration. |
| Dependency manager | uv 0.13.x | Active | Reproducible lock and environment management. |
| Numerical arrays | NumPy 2.3.x | Active | Typed, deterministic numeric matrix boundary for model adapters. |
| Classical ML | scikit-learn 1.8.x | Active | Reference linear, logistic, tree, metrics, and calibration implementation behind ports. |
| Model artifact codec | joblib 1.5.x | Active, trusted-only | Reference Python artifact serialization; deserialization disabled by default. |
| Tabular/calendar support | pandas 2.2.x | Active | Adapter dependency; excluded from the domain. |
| Validation | Pydantic 2.13.x | Active | Typed boundary validation; excluded from domain logic. |
| Settings | pydantic-settings 2.14.x | Active | Environment, dotenv, and secret-source support. |
| Exchange calendar adapter | exchange_calendars 4.13.x | Active | Venue calendars behind a replaceable port. |
| Tests | pytest 9.x | Stable | Fixtures, parametrization, and assertion introspection. |
| Lint/format | Ruff 0.17.x | CI baseline | Unified formatter and linter. |
| Type checking | Pyright 1.1.x strict | CI baseline | Strict static analysis. |
| Exchange identifiers | ISO 10383 MIC | Current | Stable venue identity independent of display name. |
| Time zones | IANA TZ database via `zoneinfo` | Current | Historical daylight-saving and regional rules. |

The latest published version is not automatically adopted. Dependency or standard upgrades
require compatibility, security, numerical-behavior, serialization, and reproducibility review,
followed by controlled CI evidence.
