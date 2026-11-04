# Infrastructure as Code

The repository provides two cloud reference deployments:

- [`gcp/`](gcp/README.md): private Cloud SQL, Cloud Storage, Artifact Registry, Secret Manager, internal Cloud Run, and a migration job.
- [`azure/`](azure/README.md): private PostgreSQL, Blob Storage, Container Registry, Key Vault, internal Container Apps, and a migration job.

Both modules require immutable container-image digests and are intentionally independent of the Python domain layer. They are reference modules, not a substitute for an organization-specific architecture, security review, cost model, and disaster-recovery exercise.

## State

Never keep production Terraform state on a developer workstation. Configure an encrypted remote backend with locking, versioning, narrowly scoped access, audit logs, and recovery procedures before applying either module.

## Validation

```bash
terraform -chdir=infra/terraform/gcp init -backend=false
terraform -chdir=infra/terraform/gcp fmt -check -recursive
terraform -chdir=infra/terraform/gcp validate

terraform -chdir=infra/terraform/azure init -backend=false
terraform -chdir=infra/terraform/azure fmt -check -recursive
terraform -chdir=infra/terraform/azure validate
```
