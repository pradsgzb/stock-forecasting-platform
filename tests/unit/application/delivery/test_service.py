import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from stock_predictor.application.delivery.service import ArtifactInput, ReleaseManifestService
from stock_predictor.domain.common.clock import FixedClock
from stock_predictor.domain.common.errors import DomainConflictError, DomainValidationError
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.delivery.models import ArtifactKind, DeploymentEnvironment

NOW = UtcInstant(datetime(2026, 11, 4, 3, 0, tzinfo=UTC))


def _service() -> ReleaseManifestService:
    return ReleaseManifestService(FixedClock(NOW))


def _manifest(tmp_path: Path):
    artifact = tmp_path / "artifact.whl"
    artifact.write_bytes(b"wheel-content")
    source = tmp_path / "source"
    source.mkdir()
    (source / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    return _service().create(
        release_version="0.6.0",
        git_commit="abcdef1234567",
        source_root=source,
        build_run_id="build-17",
        artifacts=(
            ArtifactInput(
                artifact,
                ArtifactKind.PYTHON_WHEEL,
                "application/zip",
                "artifact.whl",
            ),
        ),
        gate_results=(
            ("tests", True, "test-results.xml"),
            ("security", True, "security.sarif"),
        ),
    )


def test_manifest_round_trip_integrity_and_promotion(tmp_path: Path) -> None:
    service = _service()
    manifest = _manifest(tmp_path)
    path = tmp_path / "release.json"

    service.write(path, manifest)
    loaded = service.read(path)
    service.verify(loaded, tmp_path)
    plan = service.plan_promotion(
        loaded,
        source=DeploymentEnvironment.STAGING,
        target=DeploymentEnvironment.PRODUCTION,
        image_digest_sha256="d" * 64,
        rollback_release_fingerprint="e" * 64,
        requested_by="release-manager",
    )

    assert loaded == manifest
    assert plan.release_fingerprint == manifest.fingerprint
    assert plan.approval_required is True


def test_manifest_detects_artifact_and_json_tampering(tmp_path: Path) -> None:
    service = _service()
    manifest = _manifest(tmp_path)
    path = tmp_path / "release.json"
    service.write(path, manifest)

    (tmp_path / "artifact.whl").write_bytes(b"tampered")
    with pytest.raises(DomainConflictError, match="integrity"):
        service.verify(manifest, tmp_path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["release_version"] = "99.0.0"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DomainConflictError, match="fingerprint"):
        service.read(path)


def test_manifest_rejects_bad_inputs_and_failed_gate(tmp_path: Path) -> None:
    service = _service()
    source = tmp_path / "source"
    source.mkdir()
    (source / "file").write_text("x", encoding="utf-8")

    with pytest.raises(DomainValidationError, match="At least one"):
        service.create(
            release_version="1",
            git_commit="abcdef1",
            source_root=source,
            build_run_id="run",
            artifacts=(),
            gate_results=(("tests", True, "evidence"),),
        )
    with pytest.raises(DomainValidationError, match="does not exist"):
        service.create(
            release_version="1",
            git_commit="abcdef1",
            source_root=source,
            build_run_id="run",
            artifacts=(
                ArtifactInput(
                    tmp_path / "missing",
                    ArtifactKind.CHECKSUMS,
                    "text/plain",
                ),
            ),
            gate_results=(("tests", True, "evidence"),),
        )

    artifact = tmp_path / "artifact"
    artifact.write_text("content", encoding="utf-8")
    failed = service.create(
        release_version="1",
        git_commit="abcdef1",
        source_root=source,
        build_run_id="run",
        artifacts=(ArtifactInput(artifact, ArtifactKind.CHECKSUMS, "text/plain"),),
        gate_results=(("tests", False, "failed.xml"),),
    )
    with pytest.raises(DomainValidationError, match="quality gates failed"):
        service.verify(failed)


def test_source_tree_digest_is_deterministic_and_ignores_build_state(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / "b.txt").write_text("b", encoding="utf-8")
    (root / "a.txt").write_text("a", encoding="utf-8")
    ignored = root / ".local"
    ignored.mkdir()
    (ignored / "runtime.db").write_bytes(b"one")

    first = ReleaseManifestService.source_tree_digest(root)
    (ignored / "runtime.db").write_bytes(b"two")
    second = ReleaseManifestService.source_tree_digest(root)
    (root / "a.txt").write_text("changed", encoding="utf-8")
    third = ReleaseManifestService.source_tree_digest(root)

    assert first == second
    assert first != third
    with pytest.raises(DomainValidationError, match="does not exist"):
        ReleaseManifestService.source_tree_digest(tmp_path / "missing")


def test_manifest_parser_rejects_non_object_and_wrong_scalar_types(tmp_path: Path) -> None:
    service = _service()
    manifest = _manifest(tmp_path)
    payload = service.to_dict(manifest)

    payload["artifacts"] = ["not-an-object"]
    with pytest.raises(DomainValidationError, match="contain only objects"):
        service.from_dict(payload)

    payload = service.to_dict(manifest)
    artifacts = payload["artifacts"]
    assert isinstance(artifacts, list)
    assert isinstance(artifacts[0], dict)
    artifacts[0]["size_bytes"] = "42"
    with pytest.raises(DomainValidationError, match="must be an integer"):
        service.from_dict(payload)

    payload = service.to_dict(manifest)
    payload["fingerprint"] = 123
    with pytest.raises(DomainValidationError, match="fingerprint must be a string"):
        service.from_dict(payload)
