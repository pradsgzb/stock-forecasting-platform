# GCP reference deployment

This configuration provisions a private VPC, private Cloud SQL for PostgreSQL, a versioned
Cloud Storage bucket, Artifact Registry, Secret Manager values, an internal Cloud Run API, and
a separately invoked migration job. The application image must be supplied by immutable OCI
digest. Terraform state contains sensitive generated values and therefore must use an encrypted,
access-controlled remote backend with locking and audit logs.

```bash
terraform init
terraform fmt -check
terraform validate
terraform plan \
  -var='project_id=YOUR_PROJECT' \
  -var='app_image=REGION-docker.pkg.dev/PROJECT/REPO/app@sha256:...' \
  -var-file=environment.tfvars
```

Do not apply directly from a developer laptop for production. Use the reviewed delivery
workflow, protected environment approval, workload identity, and a remote state backend.
