# Runbook: suspected secret exposure

## Immediate actions

1. Treat the credential as compromised; do not wait for proof of misuse.
2. Revoke or rotate the credential at its issuing authority.
3. Remove affected sessions and workload tokens.
4. Restrict access to the incident evidence.
5. Search source history, build logs, artifacts, container layers, telemetry, and external forks.
6. Notify security and the data-provider or platform owner.

## Recovery

1. Issue a new least-privilege credential through the approved secret manager.
2. Redeploy or restart workloads that cache the credential.
3. Verify no secret appears in logs, manifests, Terraform variables, `.env`, model artifacts, or release bundles.
4. Review audit events and provider access for unauthorized use.
5. Add a regression control, scanner rule, or process correction.

Development JWT private keys and tokens are disposable. Regenerate them and remove the entire `.local/secrets` directory when exposure is suspected.
