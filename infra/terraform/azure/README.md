# Azure reference deployment

This module is a production-oriented reference for an internal Azure deployment. It creates:

- an isolated virtual network;
- an internal Azure Container Apps environment;
- an API app and a manually executed migration job;
- a private, zone-redundant Azure Database for PostgreSQL Flexible Server;
- a private, versioned storage account;
- Azure Container Registry;
- a user-assigned managed identity and least-privilege role assignments;
- Azure Key Vault-backed runtime secrets; and
- Log Analytics integration.

## Preconditions

1. Store Terraform state in an encrypted, access-controlled remote backend.
2. Authenticate using workload identity or another short-lived administrative identity.
3. Push a signed application image and provide its immutable `@sha256:` reference.
4. Supply the JWT verification public key through an approved secret-delivery channel.
5. Review regional availability, networking, DNS, backup, retention, and recovery settings.

## Plan

```bash
terraform init
terraform fmt -check -recursive
terraform validate
terraform plan \
  -var='subscription_id=<subscription-id>' \
  -var='app_image=<registry>/stock-forecasting-platform@sha256:<digest>' \
  -var='jwt_public_key=<PEM-value>'
```

Do not apply this reference module unchanged to a regulated or capital-bearing environment. Complete a threat model, cost review, recovery exercise, and organization-specific policy review first.
