from datetime import date
from decimal import Decimal

import pytest

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import (
    FeatureSetVersionId,
    FeatureSnapshotId,
    IngestionRunId,
    InstrumentId,
    PriceBarId,
    ValidationReportId,
)
from stock_predictor.domain.market.identifiers import ProviderName, TickerSymbol
from stock_predictor.domain.market_data.contracts import PriceBarRequest
from stock_predictor.domain.market_data.features import (
    FeatureDefinition,
    FeatureInputBar,
    FeatureObservation,
    FeatureSet,
    FeatureSnapshot,
    FeatureValueType,
)
from stock_predictor.domain.market_data.ingestion import (
    IngestionCheckpoint,
    IngestionManifest,
    IngestionPageManifest,
    IngestionStatus,
    RawObjectDescriptor,
    Sha256Digest,
)
from stock_predictor.domain.market_data.quality import (
    QualityDimension,
    QualityFinding,
    QualityScore,
    ReconciliationReport,
    RuleOutcome,
    RuleSeverity,
    ValidationReport,
    ValidationStatus,
)


def _request(provider, xnys) -> PriceBarRequest:
    return PriceBarRequest(
        provider,
        xnys,
        (TickerSymbol("AAA"),),
        date(2025, 1, 1),
        date(2025, 1, 2),
    )


def _page(fixed_instant) -> IngestionPageManifest:
    return IngestionPageManifest(
        1,
        None,
        None,
        "provider-request",
        "v1",
        "application/json",
        1,
        RawObjectDescriptor(Sha256Digest("a" * 64), "raw/sha256/aa/aa/value.blob", 2),
        fixed_instant,
    )


def test_sha256_and_raw_descriptor_validation() -> None:
    digest = Sha256Digest.from_bytes(b"payload")
    assert len(str(digest)) == 64
    with pytest.raises(DomainValidationError, match="SHA-256"):
        Sha256Digest("bad")
    with pytest.raises(DomainValidationError, match="safe relative"):
        RawObjectDescriptor(digest, "../escape", 1)


def test_manifest_and_checkpoint_invariants(fixed_instant, synthetic_provider_name, xnys) -> None:
    request = _request(synthetic_provider_name, xnys)
    page = _page(fixed_instant)
    manifest = IngestionManifest(
        IngestionRunId.new(),
        "key",
        synthetic_provider_name,
        request,
        fixed_instant,
        fixed_instant,
        IngestionStatus.COMPLETED,
        (page,),
    )

    assert manifest.advertised_record_count == 1
    assert len(manifest.manifest_fingerprint) == 64
    checkpoint = IngestionCheckpoint(
        manifest.run_id,
        "key",
        request.request_fingerprint,
        2,
        None,
        (page,),
        fixed_instant,
        fixed_instant,
    )
    assert checkpoint.next_page_number == 2
    with pytest.raises(DomainValidationError, match="page number"):
        IngestionCheckpoint(
            manifest.run_id,
            "key",
            request.request_fingerprint,
            3,
            None,
            (page,),
            fixed_instant,
            fixed_instant,
        )


def test_quality_report_and_reconciliation(fixed_instant) -> None:
    finding = QualityFinding(
        "rule",
        QualityDimension.VALIDITY,
        RuleSeverity.WARNING,
        RuleOutcome.FAILED,
        "warning",
    )
    reconciliation = ReconciliationReport(1, 1, 1, True)
    report = ValidationReport(
        ValidationReportId.new(),
        IngestionRunId.new(),
        fixed_instant,
        ValidationStatus.PASSED_WITH_WARNINGS,
        QualityScore("98"),
        1,
        (finding,),
        reconciliation,
        "v1",
    )

    assert report.accepted
    assert reconciliation.reconciled
    assert len(report.report_fingerprint) == 64
    with pytest.raises(DomainValidationError, match="between"):
        QualityScore("101")


def test_feature_definitions_set_and_observations(fixed_instant) -> None:
    definition = FeatureDefinition("close_price", "1", "Close", 0, 1)
    feature_set = FeatureSet(FeatureSetVersionId.new(), "Basic", "1", (definition,))
    bar_id = PriceBarId.new()
    observation = FeatureObservation(definition, "100.5", None, (bar_id,))
    snapshot = FeatureSnapshot(
        FeatureSnapshotId.new(),
        feature_set,
        InstrumentId.new(),
        date(2026, 1, 2),
        fixed_instant,
        fixed_instant,
        (observation,),
        "a" * 64,
    )

    assert observation.value == Decimal("100.5")
    assert feature_set.maximum_lookback == 0
    assert len(snapshot.fingerprint) == 64


def test_feature_value_types_are_enforced() -> None:
    boolean = FeatureDefinition(
        "is_positive", "1", "Boolean", 0, 1, value_type=FeatureValueType.BOOLEAN
    )
    integer = FeatureDefinition(
        "count_value", "1", "Integer", 0, 1, value_type=FeatureValueType.INTEGER
    )
    assert FeatureObservation(boolean, True, None, ()).value is True
    assert FeatureObservation(integer, "2", None, ()).value == 2
    with pytest.raises(DomainValidationError, match="bool"):
        FeatureObservation(boolean, "true", None, ())
    with pytest.raises(DomainValidationError, match="fractional"):
        FeatureObservation(integer, "1.5", None, ())
    with pytest.raises(DomainValidationError, match="reason"):
        FeatureObservation(integer, None, None, ())


def test_feature_input_bar_validates_market_values(fixed_instant) -> None:
    item = FeatureInputBar(
        PriceBarId.new(),
        date(2026, 1, 2),
        Decimal("10"),
        Decimal("12"),
        Decimal("9"),
        Decimal("11"),
        Decimal("100"),
        fixed_instant,
        "a" * 64,
    )
    assert item.close_price == Decimal("11")
    with pytest.raises(DomainValidationError, match="positive"):
        FeatureInputBar(
            PriceBarId.new(),
            date(2026, 1, 2),
            Decimal("0"),
            Decimal("12"),
            Decimal("9"),
            Decimal("11"),
            Decimal("100"),
            fixed_instant,
            "a" * 64,
        )


def test_raw_descriptor_rejects_windows_and_noncanonical_paths() -> None:
    digest = Sha256Digest("a" * 64)
    for unsafe in (r"raw\..\escape", "raw//object", "./raw/object"):
        with pytest.raises(DomainValidationError, match="safe relative"):
            RawObjectDescriptor(digest, unsafe, 1)


def test_checkpoint_rejects_invalid_fingerprint_and_cursor(
    fixed_instant, synthetic_provider_name, xnys
) -> None:
    page = _page(fixed_instant)
    with pytest.raises(DomainValidationError, match="SHA-256"):
        IngestionCheckpoint(
            IngestionRunId.new(),
            "key",
            "not-a-digest",
            1,
            None,
            (),
            fixed_instant,
            fixed_instant,
        )
    with pytest.raises(DomainValidationError, match="next cursor"):
        IngestionCheckpoint(
            IngestionRunId.new(),
            "key",
            _request(synthetic_provider_name, xnys).request_fingerprint,
            2,
            "unexpected",
            (page,),
            fixed_instant,
            fixed_instant,
        )


def test_feature_fingerprints_require_hexadecimal_sha256(fixed_instant) -> None:
    with pytest.raises(DomainValidationError, match="SHA-256"):
        FeatureInputBar(
            PriceBarId.new(),
            date(2026, 1, 2),
            Decimal("10"),
            Decimal("12"),
            Decimal("9"),
            Decimal("11"),
            Decimal("100"),
            fixed_instant,
            "z" * 64,
        )
