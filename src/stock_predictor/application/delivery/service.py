"""Build, verify, serialize, and promote immutable release evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from stock_predictor.domain.common.clock import Clock
from stock_predictor.domain.common.errors import DomainConflictError, DomainValidationError
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.delivery.models import (
    ArtifactKind,
    DeploymentEnvironment,
    DeploymentPlan,
    QualityGate,
    ReleaseArtifact,
    ReleaseManifest,
)

_IGNORED_PARTS = frozenset({".git", ".venv", ".local", "build", "dist", "__pycache__"})


@dataclass(frozen=True, slots=True)
class ArtifactInput:
    """Filesystem input used to construct release-artifact evidence."""

    path: Path
    kind: ArtifactKind
    media_type: str
    location: str | None = None


class ReleaseManifestService:
    """Produces deterministic manifests and verifies artifact integrity before promotion."""

    __slots__ = ("_clock",)

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def create(
        self,
        *,
        release_version: str,
        git_commit: str,
        source_root: Path,
        build_run_id: str,
        artifacts: tuple[ArtifactInput, ...],
        gate_results: tuple[tuple[str, bool, str], ...],
    ) -> ReleaseManifest:
        if not artifacts:
            raise DomainValidationError("At least one release artifact input is required")
        created_at = self._clock.now()
        manifest = ReleaseManifest(
            schema_version="1.0.0",
            release_version=release_version,
            git_commit=git_commit,
            source_tree_sha256=self.source_tree_digest(source_root),
            build_run_id=build_run_id,
            created_at=created_at,
            artifacts=tuple(self._artifact(item) for item in artifacts),
            quality_gates=tuple(
                QualityGate(name, passed, evidence, created_at)
                for name, passed, evidence in gate_results
            ),
        )
        return manifest

    def verify(self, manifest: ReleaseManifest, artifact_root: Path | None = None) -> None:
        """Verify gates and any local artifacts referenced by the manifest."""
        manifest.require_ready()
        for artifact in manifest.artifacts:
            location = Path(artifact.location)
            candidate = location if location.is_absolute() else (artifact_root or Path()) / location
            if candidate.exists():
                if not candidate.is_file():
                    raise DomainValidationError(f"Artifact is not a file: {candidate}")
                digest, size = self.file_digest(candidate)
                if digest != artifact.digest_sha256 or size != artifact.size_bytes:
                    raise DomainConflictError(
                        f"Artifact integrity verification failed for {artifact.name}"
                    )
            elif "://" not in artifact.location and not artifact.location.startswith("sha256:"):
                raise DomainValidationError(f"Local release artifact does not exist: {candidate}")

    def plan_promotion(
        self,
        manifest: ReleaseManifest,
        *,
        source: DeploymentEnvironment | None,
        target: DeploymentEnvironment,
        image_digest_sha256: str,
        rollback_release_fingerprint: str | None,
        requested_by: str,
    ) -> DeploymentPlan:
        manifest.require_ready()
        return DeploymentPlan(
            release_fingerprint=manifest.fingerprint,
            source=source,
            target=target,
            image_digest_sha256=image_digest_sha256,
            rollback_release_fingerprint=rollback_release_fingerprint,
            approval_required=target is DeploymentEnvironment.PRODUCTION,
            requested_by=requested_by,
            requested_at=self._clock.now(),
        )

    @staticmethod
    def source_tree_digest(root: Path) -> str:
        """Hash relevant repository bytes and relative paths in deterministic order."""
        resolved = root.resolve()
        if not resolved.is_dir():
            raise DomainValidationError(f"Source root does not exist: {root}")
        digest = hashlib.sha256()
        files = tuple(
            sorted(
                (
                    item
                    for item in resolved.rglob("*")
                    if item.is_file()
                    and not any(part in _IGNORED_PARTS for part in item.relative_to(resolved).parts)
                ),
                key=lambda item: item.relative_to(resolved).as_posix(),
            )
        )
        if not files:
            raise DomainValidationError("Source root contains no releasable files")
        for item in files:
            relative = item.relative_to(resolved).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            data = item.read_bytes()
            digest.update(len(data).to_bytes(8, "big"))
            digest.update(data)
        return digest.hexdigest()

    @staticmethod
    def file_digest(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
                size += len(block)
        return digest.hexdigest(), size

    @classmethod
    def to_dict(cls, manifest: ReleaseManifest) -> dict[str, object]:
        return {
            "schema_version": manifest.schema_version,
            "release_version": manifest.release_version,
            "git_commit": manifest.git_commit,
            "source_tree_sha256": manifest.source_tree_sha256,
            "build_run_id": manifest.build_run_id,
            "created_at": manifest.created_at.isoformat(),
            "fingerprint": manifest.fingerprint,
            "ready": manifest.ready,
            "artifacts": [
                {
                    "name": item.name,
                    "kind": item.kind.value,
                    "location": item.location,
                    "digest_sha256": item.digest_sha256,
                    "size_bytes": item.size_bytes,
                    "media_type": item.media_type,
                }
                for item in manifest.artifacts
            ],
            "quality_gates": [
                {
                    "name": item.name,
                    "passed": item.passed,
                    "evidence_reference": item.evidence_reference,
                    "checked_at": item.checked_at.isoformat(),
                }
                for item in manifest.quality_gates
            ],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> ReleaseManifest:
        """Rehydrate and revalidate a serialized release manifest."""
        artifact_items = cls._object_list(payload.get("artifacts"), "artifacts")
        gate_items = cls._object_list(payload.get("quality_gates"), "quality_gates")
        try:
            artifacts = tuple(
                ReleaseArtifact(
                    name=cls._required_string(item, "name"),
                    kind=ArtifactKind(cls._required_string(item, "kind")),
                    location=cls._required_string(item, "location"),
                    digest_sha256=cls._required_string(item, "digest_sha256"),
                    size_bytes=cls._required_int(item, "size_bytes"),
                    media_type=cls._required_string(item, "media_type"),
                )
                for item in artifact_items
            )
            gates = tuple(
                QualityGate(
                    name=cls._required_string(item, "name"),
                    passed=cls._required_bool(item, "passed"),
                    evidence_reference=cls._required_string(item, "evidence_reference"),
                    checked_at=UtcInstant.parse(cls._required_string(item, "checked_at")),
                )
                for item in gate_items
            )
            manifest = ReleaseManifest(
                schema_version=cls._required_string(payload, "schema_version"),
                release_version=cls._required_string(payload, "release_version"),
                git_commit=cls._required_string(payload, "git_commit"),
                source_tree_sha256=cls._required_string(payload, "source_tree_sha256"),
                build_run_id=cls._required_string(payload, "build_run_id"),
                created_at=UtcInstant.parse(cls._required_string(payload, "created_at")),
                artifacts=artifacts,
                quality_gates=gates,
            )
        except DomainValidationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise DomainValidationError("Release manifest JSON is invalid") from exc
        recorded = payload.get("fingerprint")
        if recorded is not None:
            if not isinstance(recorded, str):
                raise DomainValidationError("Release manifest fingerprint must be a string")
            if recorded != manifest.fingerprint:
                raise DomainConflictError(
                    "Release manifest fingerprint does not match its content"
                )
        return manifest

    @staticmethod
    def _object_list(value: object, field_name: str) -> tuple[dict[str, object], ...]:
        if not isinstance(value, list):
            raise DomainValidationError(
                f"Release manifest {field_name} must be a list of objects"
            )
        result: list[dict[str, object]] = []
        for item in value:
            if not isinstance(item, dict) or any(not isinstance(key, str) for key in item):
                raise DomainValidationError(
                    f"Release manifest {field_name} must contain only objects"
                )
            result.append(cast(dict[str, object], item))
        return tuple(result)

    @staticmethod
    def _required_string(payload: dict[str, object], name: str) -> str:
        value = payload.get(name)
        if not isinstance(value, str) or not value.strip():
            raise DomainValidationError(
                f"Release manifest field {name} must be a non-empty string"
            )
        return value

    @staticmethod
    def _required_int(payload: dict[str, object], name: str) -> int:
        value = payload.get(name)
        if not isinstance(value, int) or isinstance(value, bool):
            raise DomainValidationError(f"Release manifest field {name} must be an integer")
        return value

    @staticmethod
    def _required_bool(payload: dict[str, object], name: str) -> bool:
        value = payload.get(name)
        if not isinstance(value, bool):
            raise DomainValidationError(f"Release manifest field {name} must be a boolean")
        return value

    @classmethod
    def read(cls, path: Path) -> ReleaseManifest:
        if not path.is_file():
            raise DomainValidationError(f"Release manifest does not exist: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DomainValidationError("Release manifest is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise DomainValidationError("Release manifest root must be an object")
        return cls.from_dict(cast(dict[str, object], payload))

    @staticmethod
    def write(path: Path, manifest: ReleaseManifest) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                ReleaseManifestService.to_dict(manifest),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _artifact(self, item: ArtifactInput) -> ReleaseArtifact:
        path = item.path.resolve()
        if not path.is_file():
            raise DomainValidationError(f"Release artifact does not exist: {item.path}")
        digest, size = self.file_digest(path)
        return ReleaseArtifact(
            name=path.name,
            kind=item.kind,
            location=item.location or str(item.path),
            digest_sha256=digest,
            size_bytes=size,
            media_type=item.media_type,
        )
