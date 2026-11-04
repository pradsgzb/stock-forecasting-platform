# Sections 26–31 Verification Results

Verified on 2026-11-04 with CPython 3.13.5.

## Functional and structural checks

| Check | Result |
|---|---:|
| Complete test suite | **415 passed** |
| Branch-aware coverage | **90.66%** |
| Required coverage threshold | 90% |
| Python compilation | Passed |
| Architecture import-boundary tests | Passed |
| Repository policy validation | Passed — 339 files checked |
| TOML, JSON, YAML, and Python syntax validation | Passed |
| Markdown local-link validation | Passed |
| Kustomize reference validation | Passed |
| Terraform static delimiter and policy validation | Passed |
| GitHub Action full-SHA pin validation | Passed |
| Bash syntax validation | Passed |
| Source/test/script maximum line length | Passed at 100 characters |
| Production function annotations | Passed |
| Git whitespace validation | Passed |
| Deterministic end-to-end reference scenario | Passed |
| Live brokerage interface | Absent by design |

The complete suite was executed twice, once normally and once with branch measurement:

```bash
PYTHONPATH=src pytest -q
PYTHONPATH=src pytest -q \
  --cov=stock_predictor \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report=xml:.local/coverage-final.xml
```

## End-to-end reference evidence

The final deterministic scenario produced:

| Evidence | Result |
|---|---:|
| Raw provider pages | 82 |
| Validated records | 82 |
| Point-in-time normalized bars | 82 |
| Immutable dataset rows | 75 |
| Paper-backtest trades | 8 |
| Immutable predictions | 2 |
| Realized outcomes | 2 |
| Challenger promotion | Passed |
| Critical-condition rollback | Restored the original champion |
| Paper-trading-only flag | `true` |

The selected model in this deterministic fixture was the historical-mean baseline. That result is
intentional: model selection follows evidence rather than assuming a complex model must win.

## Distribution and installed-package checks

Before final packaging, version `0.6.0` was built as:

- `stock_forecasting_platform-0.6.0-py3-none-any.whl`;
- `stock_forecasting_platform-0.6.0.tar.gz`.

The wheel was installed into a clean target directory and checked from outside the repository
source tree. The following passed:

- package import and version check;
- bundled learning-catalog access;
- composition-root construction;
- CLI `doctor` execution.

The distributions are rebuilt again after the final documentation and reports are generated and
are included inside the delivered source ZIP.

## Native external-tool qualification

The local execution environment did not contain Docker, `kubectl`, or Terraform. Their native
commands were therefore not represented as locally executed. Repository validation reported these
explicit skips while completing all static checks:

```text
SKIPPED terraform: executable not installed
SKIPPED kubectl: executable not installed
SKIPPED docker: executable not installed
```

The delivered CI and validation scripts run the native checks when those executables and required
provider/plugin access are available.

Ruff, Pyright, Bandit, `pip-audit`, and Trivy were also unavailable as local executables. They are
configured as required CI or release gates but are not falsely reported as locally passed. Local
substitute checks included Python compilation, complete annotations, line-length policy, import
boundaries, shell syntax, repository policy validation, test coverage, and Git whitespace.

## Dependency-lock qualification

No fabricated `uv.lock` is included. The local package cache could not resolve all declared
metadata offline, so a trustworthy lockfile could not be generated in the isolated environment.
The first workstation setup uses the documented networked bootstrap path:

```bash
./scripts/bootstrap.sh
```

When `uv.lock` already exists, bootstrap, CI, container, and release paths verify and consume it
with `--locked`; they do not silently rewrite it.

## Safety verification

Executable tests and repository inspection verify that:

- configuration rejects live trading;
- no broker or live-order port exists;
- model promotion remains governed and human-gated by default;
- automatic promotion and online inference remain disabled by default;
- reference execution is paper-only;
- release artifacts are checksum-addressed;
- production deployment requires immutable image digests;
- software rollback and model rollback remain separate controlled operations;
- deployed secrets are not committed in manifests;
- predictions, outcomes, audit events, and release evidence remain traceable.
