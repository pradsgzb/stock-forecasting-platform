# Extend a cloud deployment module

**Exercise ID:** `cloud-deployment-module`
**Track:** `cloud-devops`
**Difficulty:** `advanced`
**Expected focused sessions:** 12

## Objective

Extend one cloud reference deployment while preserving private networking and managed identity.

## Prerequisites

- python-domain-extension

## Extension points

- `infra/terraform/gcp`
- `infra/terraform/azure`
- `deploy/kubernetes`

## Acceptance criteria

- Store no credentials in Terraform state inputs or source code.
- Expose only documented outputs.
- Run formatting, validation, and infrastructure security checks.

## Verification

- `./scripts/validate-infrastructure.sh`
- docker compose config --quiet

## Deliverables

- Infrastructure changes
- Threat-model update
- Rollback procedure

## Review questions

- Which invariant does the change introduce or preserve?
- How does the implementation prevent future-data leakage or silent mutation?
- What happens when an input, dependency, or external provider fails?
- Which evidence proves the result is reproducible?
- What limitation remains after this exercise?
