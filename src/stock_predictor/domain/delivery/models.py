"""Immutable release evidence and controlled environment-promotion models."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.temporal import UtcInstant

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{7,64}$")


def _sha256(value: str, *, field_name: str) -> str:
    normalized = value.strip().lower()
    if _SHA256.fullmatch(normalized) is None:
        raise DomainValidationError(f"{field_name} must be a lowercase SHA-256 digest")
    return normalized


def _non_empty(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DomainValidationError(f"{field_name} cannot be empty")
    return normalized


class ArtifactKind(StrEnum):
    """Supported release artifact families."""

    PYTHON_WHEEL = "python_wheel"
    SOURCE_DISTRIBUTION = "source_distribution"
    CONTAINER_IMAGE = "container_image"
    DEPENDENCY_SBOM = "dependency_sbom"
    CHECKSUMS = "checksums"
    MODEL_PACKAGE = "model_package"
    DEPLOYMENT_BUNDLE = "deployment_bundle"


class DeploymentEnvironment(StrEnum):
    """Ordered software-delivery environments."""

    INTEGRATION = "integration"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def rank(self) -> int:
        return {
            DeploymentEnvironment.INTEGRATION: 1,
            DeploymentEnvironment.STAGING: 2,
            DeploymentEnvironment.PRODUCTION: 3,
        }[self]


@dataclass(frozen=True, slots=True)
class ReleaseArtifact:
    """One immutable, content-addressed release artifact."""

    name: str
    kind: ArtifactKind
    location: str
    digest_sha256: str
    size_bytes: int
    media_type: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _non_empty(self.name, field_name="Artifact name"))
        object.__setattr__(
            self,
            "location",
            _non_empty(self.location, field_name="Artifact location"),
        )
        object.__setattr__(
            self,
            "digest_sha256",
            _sha256(self.digest_sha256, field_name="Artifact digest"),
        )
        object.__setattr__(
            self,
            "media_type",
            _non_empty(self.media_type, field_name="Artifact media type"),
        )
        if self.size_bytes < 0:
            raise DomainValidationError("Artifact size cannot be negative")


@dataclass(frozen=True, slots=True)
class QualityGate:
    """One auditable release gate and its evidence reference."""

    name: str
    passed: bool
    evidence_reference: str
    checked_at: UtcInstant

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _non_empty(self.name, field_name="Gate name"))
        object.__setattr__(
            self,
            "evidence_reference",
            _non_empty(self.evidence_reference, field_name="Gate evidence reference"),
        )


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    """Reproducible software release evidence independent of a deployment platform."""

    schema_version: str
    release_version: str
    git_commit: str
    source_tree_sha256: str
    build_run_id: str
    created_at: UtcInstant
    artifacts: tuple[ReleaseArtifact, ...]
    quality_gates: tuple[QualityGate, ...]
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        schema = _non_empty(self.schema_version, field_name="Manifest schema version")
        version = _non_empty(self.release_version, field_name="Release version")
        commit = self.git_commit.strip().lower()
        if _COMMIT.fullmatch(commit) is None:
            raise DomainValidationError("Git commit must contain 7 to 64 hexadecimal characters")
        source_digest = _sha256(self.source_tree_sha256, field_name="Source-tree digest")
        build_run = _non_empty(self.build_run_id, field_name="Build run ID")
        if not self.artifacts:
            raise DomainValidationError("Release manifest requires at least one artifact")
        if not self.quality_gates:
            raise DomainValidationError("Release manifest requires quality gates")
        artifact_names = tuple(item.name for item in self.artifacts)
        gate_names = tuple(item.name for item in self.quality_gates)
        if len(set(artifact_names)) != len(artifact_names):
            raise DomainValidationError("Release artifact names must be unique")
        if len(set(gate_names)) != len(gate_names):
            raise DomainValidationError("Release quality-gate names must be unique")
        ordered_artifacts = tuple(sorted(self.artifacts, key=lambda item: item.name))
        ordered_gates = tuple(sorted(self.quality_gates, key=lambda item: item.name))
        object.__setattr__(self, "schema_version", schema)
        object.__setattr__(self, "release_version", version)
        object.__setattr__(self, "git_commit", commit)
        object.__setattr__(self, "source_tree_sha256", source_digest)
        object.__setattr__(self, "build_run_id", build_run)
        object.__setattr__(self, "artifacts", ordered_artifacts)
        object.__setattr__(self, "quality_gates", ordered_gates)
        canonical = json.dumps(
            {
                "schema_version": schema,
                "release_version": version,
                "git_commit": commit,
                "source_tree_sha256": source_digest,
                "build_run_id": build_run,
                "created_at": self.created_at.isoformat(),
                "artifacts": [
                    {
                        "name": item.name,
                        "kind": item.kind.value,
                        "location": item.location,
                        "digest_sha256": item.digest_sha256,
                        "size_bytes": item.size_bytes,
                        "media_type": item.media_type,
                    }
                    for item in ordered_artifacts
                ],
                "quality_gates": [
                    {
                        "name": item.name,
                        "passed": item.passed,
                        "evidence_reference": item.evidence_reference,
                        "checked_at": item.checked_at.isoformat(),
                    }
                    for item in ordered_gates
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical).hexdigest())

    @property
    def ready(self) -> bool:
        """Return whether every recorded quality gate passed."""
        return all(item.passed for item in self.quality_gates)

    def require_ready(self) -> None:
        """Reject promotion when any quality gate failed."""
        failed = tuple(item.name for item in self.quality_gates if not item.passed)
        if failed:
            raise DomainValidationError(
                "Release quality gates failed: " + ", ".join(sorted(failed))
            )


@dataclass(frozen=True, slots=True)
class DeploymentPlan:
    """Controlled promotion of one immutable release between adjacent environments."""

    release_fingerprint: str
    source: DeploymentEnvironment | None
    target: DeploymentEnvironment
    image_digest_sha256: str
    rollback_release_fingerprint: str | None
    approval_required: bool
    requested_by: str
    requested_at: UtcInstant

    def __post_init__(self) -> None:
        release = _sha256(self.release_fingerprint, field_name="Release fingerprint")
        image = _sha256(self.image_digest_sha256, field_name="Image digest")
        actor = _non_empty(self.requested_by, field_name="Deployment requester")
        rollback = self.rollback_release_fingerprint
        if rollback is not None:
            rollback = _sha256(rollback, field_name="Rollback release fingerprint")
            if rollback == release:
                raise DomainValidationError("Rollback release must differ from the new release")
        if self.source is None and self.target is not DeploymentEnvironment.INTEGRATION:
            raise DomainValidationError("First deployment must target integration")
        if self.source is not None and self.target.rank != self.source.rank + 1:
            raise DomainValidationError("Deployments may promote only to the adjacent environment")
        if self.target is DeploymentEnvironment.PRODUCTION and not self.approval_required:
            raise DomainValidationError("Production promotion requires explicit approval")
        object.__setattr__(self, "release_fingerprint", release)
        object.__setattr__(self, "image_digest_sha256", image)
        object.__setattr__(self, "rollback_release_fingerprint", rollback)
        object.__setattr__(self, "requested_by", actor)
