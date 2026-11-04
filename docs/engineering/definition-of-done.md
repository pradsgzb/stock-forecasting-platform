# Definition of Done

A change is complete only when all applicable conditions are satisfied:

- Requirements and acceptance criteria are identified.
- Domain behavior is covered by tests.
- External adapters have contract or integration tests.
- Formatting and linting pass without suppression-by-default.
- Strict type checking passes.
- Test coverage remains at or above the configured threshold.
- Architecture boundary tests pass.
- Security, dependency, secret, configuration, and container scans have no unresolved blocking
  finding.
- Documentation and ADRs are updated when behavior or architecture changes.
- Database migrations upgrade and downgrade successfully when persistence changes.
- The package builds successfully and packaged migration assets are present.
- The pull request is reviewed by an appropriate code owner.
- The change includes rollback or compatibility considerations where applicable.
