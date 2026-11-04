from datetime import UTC, datetime

import pytest

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.delivery.models import (
    ArtifactKind,
    DeploymentEnvironment,
    DeploymentPlan,
    QualityGate,
    ReleaseArtifact,
    ReleaseManifest,
)

NOW = UtcInstant(datetime(2026, 11, 4, 2, 30, tzinfo=UTC))
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _artifact() -> ReleaseArtifact:
    return ReleaseArtifact(
        name="package.whl",
        kind=ArtifactKind.PYTHON_WHEEL,
        location="dist/package.whl",
        digest_sha256=DIGEST_A,
        size_bytes=42,
        media_type="application/zip",
    )


def _manifest(*, gate_passed: bool = True) -> ReleaseManifest:
    return ReleaseManifest(
        schema_version="1.0.0",
        release_version="0.6.0",
        git_commit="abcdef1234567",
        source_tree_sha256=DIGEST_B,
        build_run_id="run-1",
        created_at=NOW,
        artifacts=(_artifact(),),
        quality_gates=(QualityGate("tests", gate_passed, "report.xml", NOW),),
    )


def test_release_manifest_is_ordered_fingerprinted_and_ready() -> None:
    second = ReleaseArtifact(
        name="a-source.tar.gz",
        kind=ArtifactKind.SOURCE_DISTRIBUTION,
        location="dist/a-source.tar.gz",
        digest_sha256="c" * 64,
        size_bytes=73,
        media_type="application/gzip",
    )
    manifest = ReleaseManifest(
        schema_version="1.0.0",
        release_version="0.6.0",
        git_commit="ABCDEF1234567",
        source_tree_sha256=DIGEST_B,
        build_run_id="run-1",
        created_at=NOW,
        artifacts=(_artifact(), second),
        quality_gates=(
            QualityGate("typing", True, "pyright.txt", NOW),
            QualityGate("tests", True, "pytest.xml", NOW),
        ),
    )

    assert tuple(item.name for item in manifest.artifacts) == (
        "a-source.tar.gz",
        "package.whl",
    )
    assert manifest.git_commit == "abcdef1234567"
    assert manifest.ready is True
    assert len(manifest.fingerprint) == 64


def test_failed_gate_blocks_release() -> None:
    manifest = _manifest(gate_passed=False)

    assert manifest.ready is False
    with pytest.raises(DomainValidationError, match="quality gates failed"):
        manifest.require_ready()


def test_release_models_reject_invalid_values() -> None:
    with pytest.raises(DomainValidationError, match="SHA-256"):
        ReleaseArtifact(
            name="bad",
            kind=ArtifactKind.CHECKSUMS,
            location="bad",
            digest_sha256="not-a-digest",
            size_bytes=1,
            media_type="text/plain",
        )
    with pytest.raises(DomainValidationError, match="size cannot be negative"):
        ReleaseArtifact(
            name="bad",
            kind=ArtifactKind.CHECKSUMS,
            location="bad",
            digest_sha256=DIGEST_A,
            size_bytes=-1,
            media_type="text/plain",
        )
    with pytest.raises(DomainValidationError, match="unique"):
        ReleaseManifest(
            schema_version="1",
            release_version="1",
            git_commit="abcdef1",
            source_tree_sha256=DIGEST_A,
            build_run_id="run",
            created_at=NOW,
            artifacts=(_artifact(), _artifact()),
            quality_gates=(QualityGate("tests", True, "a", NOW),),
        )


def test_deployment_plan_enforces_adjacent_promotion_and_production_approval() -> None:
    integration = DeploymentPlan(
        release_fingerprint=DIGEST_A,
        source=None,
        target=DeploymentEnvironment.INTEGRATION,
        image_digest_sha256=DIGEST_B,
        rollback_release_fingerprint=None,
        approval_required=False,
        requested_by="release-bot",
        requested_at=NOW,
    )
    assert integration.target is DeploymentEnvironment.INTEGRATION

    with pytest.raises(DomainValidationError, match="adjacent"):
        DeploymentPlan(
            release_fingerprint=DIGEST_A,
            source=DeploymentEnvironment.INTEGRATION,
            target=DeploymentEnvironment.PRODUCTION,
            image_digest_sha256=DIGEST_B,
            rollback_release_fingerprint=None,
            approval_required=True,
            requested_by="release-bot",
            requested_at=NOW,
        )
    with pytest.raises(DomainValidationError, match="explicit approval"):
        DeploymentPlan(
            release_fingerprint=DIGEST_A,
            source=DeploymentEnvironment.STAGING,
            target=DeploymentEnvironment.PRODUCTION,
            image_digest_sha256=DIGEST_B,
            rollback_release_fingerprint=None,
            approval_required=False,
            requested_by="release-bot",
            requested_at=NOW,
        )
    with pytest.raises(DomainValidationError, match="must differ"):
        DeploymentPlan(
            release_fingerprint=DIGEST_A,
            source=None,
            target=DeploymentEnvironment.INTEGRATION,
            image_digest_sha256=DIGEST_B,
            rollback_release_fingerprint=DIGEST_A,
            approval_required=False,
            requested_by="release-bot",
            requested_at=NOW,
        )
