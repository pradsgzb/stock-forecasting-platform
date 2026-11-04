from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from stock_predictor.adapters.models.artifact_codec import TrustedJoblibArtifactCodec
from stock_predictor.adapters.repositories.in_memory_model_registry import (
    InMemoryModelRegistryRepository,
)
from stock_predictor.adapters.repositories.in_memory_monitoring_repository import (
    InMemoryMonitoringRepository,
)
from stock_predictor.adapters.repositories.in_memory_outcome_repository import (
    InMemoryOutcomeRepository,
)
from stock_predictor.adapters.repositories.in_memory_prediction_ledger import (
    InMemoryPredictionLedger,
)
from stock_predictor.adapters.repositories.in_memory_retraining_repository import (
    InMemoryRetrainingRepository,
)
from stock_predictor.application.continuous_training.service import (
    ContinuousTrainingService,
)
from stock_predictor.application.feedback.service import (
    FeedbackService,
    OutcomeCollectionService,
)
from stock_predictor.application.inference.service import (
    BatchInferenceRequest,
    ModelInferenceService,
)
from stock_predictor.application.monitoring.service import (
    ModelMonitoringService,
    PerformancePolicy,
)
from stock_predictor.application.registry.service import ModelRegistryService
from stock_predictor.domain.common.identifiers import InstrumentId, MonitoringAlertId
from stock_predictor.domain.common.temporal import InstantInterval
from stock_predictor.domain.mlops.continuous_training import RetrainingTrigger
from stock_predictor.domain.mlops.feedback import FeedbackMetric, FeedbackSummary
from stock_predictor.domain.mlops.monitoring import MonitoringAlert, MonitoringSeverity
from stock_predictor.domain.mlops.registry import (
    ApprovalRole,
    PromotionPolicy,
    RegistryAlias,
)
from stock_predictor.domain.modeling.evaluation import MetricDirection
from tests.helpers.mlops import (
    DEFAULT_GATES,
    StubFeaturePipeline,
    StubLabelService,
    StubTrainingService,
    feature_set,
    fixed_clock,
    promotion_evidence,
    scope,
    training_result,
)
from tests.helpers.modeling import regression_target


def _deploy_initial_champion(registry, result, now) -> None:
    candidate = registry.register_candidate(result, scope(), actor="trainer")
    validated, _ = registry.validate_candidate(
        candidate.model_version_id,
        promotion_evidence(now),
        actor="validator",
    )
    registry.stage(validated.model_version_id, actor="release-manager")
    registry.deploy_challenger(
        validated.model_version_id,
        actor="release-manager",
        reason="shadow validation",
    )
    registry.promote_challenger(
        validated.model_version_id,
        promotion_evidence(now),
        actor="deployment-approver",
        reason="initial production champion",
    )


def _feedback(now, model_id, value: str) -> FeedbackSummary:
    return FeedbackSummary(
        model_version_id=model_id,
        target_key=scope().target_key,
        window=InstantInterval(now.plus(-timedelta(days=1)), now),
        sample_count=2,
        metrics=(FeedbackMetric("mae", value),),
        generated_at=now,
        outcome_fingerprints=("1" * 64, "2" * 64),
    )


def test_prediction_feedback_retraining_promotion_and_rollback(fixed_instant) -> None:
    target = regression_target()
    features = feature_set()
    registry_repository = InMemoryModelRegistryRepository()
    registry = ModelRegistryService(
        registry_repository,
        fixed_clock(fixed_instant),
        PromotionPolicy(DEFAULT_GATES, tuple(ApprovalRole)),
    )
    initial_result = training_result(fixed_instant, target=target, features=features)
    _deploy_initial_champion(registry, initial_result, fixed_instant)

    ledger = InMemoryPredictionLedger()
    instruments = (InstrumentId.new(), InstrumentId.new())
    inference = ModelInferenceService(
        registry_repository,
        TrustedJoblibArtifactCodec(allow_deserialization=True),
        StubFeaturePipeline(
            features,
            fixed_instant,
            values={instruments[0]: Decimal("100"), instruments[1]: Decimal("105")},
        ),
        ledger,
        fixed_clock(fixed_instant),
    )
    batch = inference.predict_batch(
        BatchInferenceRequest(
            scope=scope(target),
            target=target,
            feature_set=features,
            instrument_ids=instruments,
            as_of=date(2026, 1, 2),
            decision_cutoff=fixed_instant,
            idempotency_key="daily-2026-01-02",
        )
    )
    assert len(batch.predictions) == 2
    assert inference.predict_batch(
        BatchInferenceRequest(
            scope=scope(target),
            target=target,
            feature_set=features,
            instrument_ids=instruments,
            as_of=date(2026, 1, 2),
            decision_cutoff=fixed_instant,
            idempotency_key="daily-2026-01-02",
        )
    ) == batch

    outcomes = InMemoryOutcomeRepository()
    collected_at = fixed_instant.plus(-timedelta(seconds=30))
    collection = OutcomeCollectionService(
        ledger,
        outcomes,
        StubLabelService(target, Decimal("0.10")),
        fixed_clock(collected_at),
    ).collect(target, fixed_instant)
    assert len(collection.collected) == 2
    feedback = FeedbackService(outcomes, fixed_clock(fixed_instant)).summarize(
        initial_result.model_version_id,
        target.key,
        InstantInterval(fixed_instant.plus(-timedelta(minutes=1)), fixed_instant),
    )
    assert feedback.sample_count == 2

    monitoring_repository = InMemoryMonitoringRepository()
    monitoring = ModelMonitoringService(
        monitoring_repository,
        fixed_clock(fixed_instant),
        performance_policy=PerformancePolicy(minimum_samples=2),
    )
    snapshot = monitoring.record_performance(feedback)
    assert snapshot.severity is MonitoringSeverity.CRITICAL
    assert monitoring_repository.alerts()[0].model_version_id == (
        initial_result.model_version_id
    )

    challenger_result = training_result(fixed_instant, target=target, features=features)
    continuous = ContinuousTrainingService(
        InMemoryRetrainingRepository(),
        StubTrainingService(challenger_result),
        registry,
        registry_repository,
        fixed_clock(fixed_instant),
        minimum_outcomes=2,
        minimum_improvement=Decimal("0.01"),
    )
    retraining = continuous.request_retraining(
        scope=scope(target),
        trigger=RetrainingTrigger.PERFORMANCE_DEGRADATION,
        evidence_references=(snapshot.fingerprint,),
        requested_by="monitoring-service",
        idempotency_key="performance-2026-01-02",
    )
    completed = continuous.run(
        retraining.request_id,
        object(),
        promotion_evidence(fixed_instant),
        actor="ml-operator",
    )
    assert completed.challenger_deployment is not None

    comparison, deployment = continuous.compare_and_promote(
        scope=scope(target),
        champion_summary=_feedback(
            fixed_instant, initial_result.model_version_id, "0.20"
        ),
        challenger_summary=_feedback(
            fixed_instant, challenger_result.model_version_id, "0.10"
        ),
        metric_name="mae",
        direction=MetricDirection.MINIMIZE,
        promotion_evidence=promotion_evidence(fixed_instant),
        actor="deployment-approver",
        human_approved=True,
    )
    assert comparison.accepted
    assert deployment is not None
    assert registry_repository.resolve_alias(
        scope(target), RegistryAlias.CHAMPION
    ).model_version_id == challenger_result.model_version_id

    critical = MonitoringAlert(
        alert_id=MonitoringAlertId.new(),
        model_version_id=challenger_result.model_version_id,
        severity=MonitoringSeverity.CRITICAL,
        category="performance_degradation",
        title="Critical challenger degradation",
        detail="Production rollback threshold crossed.",
        evidence_reference="post-promotion-monitoring",
        raised_at=fixed_instant,
    )
    restored = continuous.rollback_on_alert(
        scope(target), critical, actor="incident-commander"
    )
    assert restored.model_version_id == initial_result.model_version_id
    assert registry_repository.resolve_alias(
        scope(target), RegistryAlias.CHAMPION
    ).model_version_id == initial_result.model_version_id
