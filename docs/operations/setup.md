# Setup guide

This guide prepares a development workstation for the complete Sections 00–31 platform. The project supports Python 3.13 and 3.14 and uses `uv` for dependency locking, virtual environments, and command execution.

## 1. Prerequisites

Required for native development:

- Git
- Python 3.13 or 3.14
- `uv`
- a terminal with PowerShell 7 on Windows or Bash on Linux/macOS

Recommended:

- Visual Studio Code with the repository recommendations
- Docker Desktop or Docker Engine with Compose v2
- PostgreSQL client tools

Needed only for deployment work:

- `kubectl`
- Terraform
- authenticated access to the selected cloud and Kubernetes environment

Never install a broker credential or real trading credential in this repository. The platform is research and paper-trading only.

## 2. Extract or clone the repository

```bash
git clone <repository-url> stock-forecasting-platform
cd stock-forecasting-platform
```

For the delivered ZIP, extract it and open the `stock-forecasting-platform` directory.

## 3. Verify Python and uv

```bash
python --version
uv --version
```

Install the project-managed Python runtime when necessary:

```bash
uv python install 3.13
```

On Windows PowerShell, the commands are the same.

## 4. Resolve and install dependencies

Use the platform bootstrap script:

```bash
./scripts/bootstrap.sh
```

```powershell
./scripts/bootstrap.ps1
```

When `uv.lock` exists, bootstrap verifies it and installs exactly the locked dependency set. When the source bundle has no lockfile, bootstrap performs one networked resolution with Python 3.13, creates `uv.lock`, verifies it, installs all groups, and installs the Git hooks. Review the generated dependency diff and commit `uv.lock` before running CI, building containers, or producing a release. Ordinary setup must not regenerate an existing lockfile.

The equivalent explicit commands are:

```bash
test -f uv.lock || uv lock --python 3.13
uv lock --check
uv sync --locked --all-groups
uv run --locked pre-commit install --install-hooks
```

## 5. Create local configuration

Linux/macOS:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

The default `.env.example` uses SQLite for native execution. Change only values required by the selected runtime. Never commit `.env`.

## 6. Generate development-only identity material

Linux/macOS:

```bash
./scripts/generate-dev-credentials.sh
```

Windows PowerShell:

```powershell
./scripts/generate-dev-credentials.ps1
```

The command creates:

- `.local/secrets/jwt-private.pem`
- `.local/secrets/jwt-public.pem`
- `.local/secrets/operator-token`
- `.local/secrets/prometheus-token`

These credentials are local-only, ignored by Git, and expire. Regenerate them when they expire or are exposed.

For native API execution, set the public-key path in the current shell:

```bash
export SP_API__JWT_VERIFICATION_KEY_PATH=.local/secrets/jwt-public.pem
```

```powershell
$env:SP_API__JWT_VERIFICATION_KEY_PATH = ".local/secrets/jwt-public.pem"
```

## 7. Initialize the database

```bash
uv run --locked stock-predictor db-upgrade
uv run --locked stock-predictor db-current
```

The expected revision is the latest packaged Alembic revision. Migration commands are idempotent and should run before the API or worker starts.

## 8. Verify the installation

```bash
uv run --locked stock-predictor doctor
uv run --locked python scripts/validate-repository.py
uv run --locked pytest -q
```

Run the complete quality gate before submitting a change:

```bash
./scripts/check.sh
```

```powershell
./scripts/check.ps1
```

## 9. Docker setup

Docker requires the committed lockfile and local `.env` values. Set strong local-only values for at least:

```dotenv
POSTGRES_PASSWORD=<long-random-value>
MINIO_ROOT_USER=<local-user>
MINIO_ROOT_PASSWORD=<long-random-value>
GRAFANA_ADMIN_USER=<local-admin>
GRAFANA_ADMIN_PASSWORD=<long-random-value>
```

Then run:

```bash
./scripts/dev-up.sh
```

```powershell
./scripts/dev-up.ps1
```

The base stack starts PostgreSQL, database migration, the API, and the outbox worker. Optional profiles are documented in [Running the platform](running.md).

## 10. Setup failures

- **`uv.lock` missing:** run the bootstrap script on a network-connected workstation. It generates the resolver-owned file once.
- **`uv.lock` stale:** use `uv lock --check` to confirm the mismatch, then update it only as part of a reviewed dependency change.
- **Python version rejected:** use Python 3.13 or 3.14.
- **JWT key missing:** rerun the credential generator and set `SP_API__JWT_VERIFICATION_KEY_PATH`.
- **Migration failure:** inspect the database URL and run `uv run --locked alembic history` followed by `uv run --locked stock-predictor db-current`.
- **Docker build cannot find `uv.lock`:** confirm the repository root is the build context.
- **Windows path issue:** run PowerShell from the repository root and use the provided `.ps1` scripts.
