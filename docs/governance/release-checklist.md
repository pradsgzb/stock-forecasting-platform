# Release checklist

## Source and dependencies

- [ ] Exact Git commit reviewed and protected.
- [ ] `uv.lock` present and unchanged except in an approved dependency update.
- [ ] Build is reproducible from a clean checkout.
- [ ] Licenses and dependency audit reviewed.

## Quality

- [ ] Formatting and linting pass.
- [ ] Strict type checking passes.
- [ ] Unit, contract, integration, security, and end-to-end tests pass.
- [ ] Branch coverage meets the repository gate.
- [ ] Reference scenario passes.
- [ ] Repository and infrastructure validation pass.

## Security

- [ ] CodeQL, Bandit, dependency review, secret scan, and container scan pass.
- [ ] SBOM and build provenance generated.
- [ ] Container and package artifacts are checksummed and attested.
- [ ] No credentials or sensitive data are present in source or artifacts.

## Deployment

- [ ] Release manifest fingerprint recorded.
- [ ] OCI image is pinned by digest.
- [ ] Migration is backward compatible.
- [ ] Readiness and rollback procedures tested.
- [ ] Previous approved image digest available.
- [ ] Production environment approval obtained.
