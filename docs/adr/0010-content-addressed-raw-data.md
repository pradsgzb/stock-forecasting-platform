# ADR-0010: Store Raw Provider Payloads by Content Digest

- Status: Accepted
- Date: 2026-11-03

## Context

Reproducible validation, correction analysis, and audit require the exact source bytes. Mutable
file names or overwrite-in-place ingestion cannot prove what a prior run consumed.

## Decision

Store non-empty raw payloads under SHA-256-derived keys. Publish objects once, verify checksum
and byte count on read, and reference them through immutable page manifests. Keep resumable
checkpoints operationally mutable, but make completed manifests write-once.

## Consequences

Identical content is deduplicated and every downstream record can cite immutable evidence.
Production adapters must add retention, encryption, object lock, and disaster-recovery controls;
those controls do not alter the domain or port contracts.
