# Controlled deployment

## Delivery invariants

- Build once and promote the same immutable image digest.
- Run migrations before workload rollout.
- Separate software delivery from model promotion.
- Require GitHub Environment approval for production.
- Keep a previously approved image digest available for rollback.
- Never deploy an unverified tag such as `latest`.
- Keep automatic model promotion disabled.

## Release evidence

A release manifest records source-tree digest, Git commit, build run, artifacts, checksums, quality gates, and evidence references.

```bash
uv run --locked stock-predictor release-manifest create --help
uv run --locked stock-predictor release-manifest verify --help
uv run --locked stock-predictor release-manifest plan --help
```

The manifest is content-derived. Editing a serialized manifest invalidates its fingerprint.

## GitHub delivery workflow

The **Controlled Delivery** workflow:

1. checks out the exact commit;
2. performs all locked release checks;
3. validates repository and deployment references;
4. builds wheel, source distribution, SBOM, deployment bundle, and container image;
5. pushes the image and resolves its registry digest;
6. generates a release manifest and deployment plan;
7. attests and retains release evidence; and
8. optionally promotes through a protected GitHub Environment.

Configure GitHub Environments named `integration`, `staging`, and `production`. Require independent reviewers for production. Supply cluster access through the environment secret `KUBECONFIG_B64`, preferably as short-lived credentials issued by workload identity rather than a permanent administrator configuration.

By default, workflow dispatch validates and packages only. Set `execute=true` deliberately to apply a deployment.

## Kubernetes order of operations

`scripts/deploy-kubernetes.sh` and its PowerShell equivalent:

1. verify the target environment and immutable image format;
2. render Kustomize;
3. pin API, worker, and migration containers to the same digest;
4. apply the namespace and non-workload prerequisites server-side;
5. recreate and wait for the migration Job;
6. apply the API and worker Deployments only after migration succeeds;
7. wait for both workload rollouts; and
8. return failure when any step fails.

Before execution, provision these namespaced secrets through an external secret controller or approved platform process:

- `stock-predictor-runtime-secrets`, including `SP_DATABASE__URL`, JWT issuer, and JWT audience;
- `stock-predictor-identity`, containing `jwt-public.pem`.

Do not commit secret manifests.

## Rollback

Rollback uses a previously approved image digest, not a mutable tag. It does not run the older
image's migration code against a newer schema:

```bash
./scripts/deploy-kubernetes.sh \
  production \
  registry.example/stock-forecasting-platform@sha256:<approved-previous-digest> \
  --skip-migration
```

PowerShell uses `-SkipMigration`.

Database migrations must follow expand-and-contract design. A software rollback must not assume that a destructive schema downgrade is safe. When a migration is incompatible, restore service through a forward correction or the documented database recovery plan.

Model rollback is separate from software rollback and is handled through the model registry and continuous-training policy.

## Cloud references

- [GCP module](../../infra/terraform/gcp/README.md)
- [Azure module](../../infra/terraform/azure/README.md)
- [Infrastructure overview](../../infra/terraform/README.md)

These modules require organization-specific networking, identity, cost, recovery, compliance, and security review before use.
