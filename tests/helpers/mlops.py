from __future__ import annotations

from datetime import date
from decimal import Decimal

import numpy as np

from stock_predictor.adapters.models.artifact_codec import TrustedJoblibArtifactCodec
from stock_predictor.adapters.models.baselines import ZeroReturnRegressorPlugin
from stock_predictor.application.training.service import TrainingRequest
from stock_predictor.domain.common.clock import FixedClock
from stock_predictor.domain.common.identifiers import (
    FeatureSetVersionId,
    FeatureSnapshotId,
    InstrumentId,
    LabelId,
    ModelVersionId,
    PriceBarId,
)
from stock_predictor.domain.common.temporal import UtcInstant
from stock_predictor.domain.market_data.features import (
    FeatureDefinition,
    FeatureObservation,
    FeatureSet,
    FeatureSnapshot,
    MissingValuePolicy,
)
from stock_predictor.domain.mlops.registry import (
    ApprovalDecision,
    ApprovalRole,
    GateResult,
    ModelApproval,
    ModelDeploymentScope,
    PromotionEvidence,
)
from stock_predictor.domain.modeling.evaluation import (
    EvaluationReport,
    MetricDirection,
    MetricValue,
)
from stock_predictor.domain.modeling.models import (
    LearningTask,
    ModelCard,
    ModelFamily,
    ModelSignature,
    ModelSpec,
)
from stock_predictor.domain.modeling.targets import LabelObservation, TargetDefinition
from stock_predictor.domain.modeling.training import (
    TrainingResult,
    TrialStatus,
    TrialSummary,
)
from tests.helpers.modeling import regression_target


DEFAULT_GATES = (
    "artifact_verified",
    "dataset_lineage_verified",
    "baseline_outperformed",
    "backtest_passed",
    "risk_limits_passed",
    "security_checks_passed",
)


def feature_set() -> FeatureSet:
    return FeatureSet(
        FeatureSetVersionId.new(),
        "serving-features",
        "1.0.0",
        (
            FeatureDefinition(
                "close_price",
                "1.0.0",
                "Latest point-in-time close.",
                0,
                1,
                missing_value_policy=MissingValuePolicy.FAIL,
            ),
        ),
    )


def scope(target: TargetDefinition | None = None, environment: str = "staging"):
    resolved = target or regression_target()
    return ModelDeploymentScope(environment, resolved.key, LearningTask.REGRESSION)


def training_result(
    now: UtcInstant,
    *,
    target: TargetDefinition | None = None,
    features: FeatureSet | None = None,
) -> TrainingResult:
    resolved_target = target or regression_target()
    resolved_features = features or feature_set()
    signature = ModelSignature(
        tuple(item.key for item in resolved_features.definitions),
        resolved_target.key,
        LearningTask.REGRESSION,
    )
    spec = ModelSpec(
        "zero-return",
        "1.0.0",
        ModelFamily.BASELINE,
        LearningTask.REGRESSION,
        "baseline.zero_return",
        7,
    )
    fitted = ZeroReturnRegressorPlugin().fit(
        spec,
        signature,
        np.asarray([[1.0], [2.0]], dtype=np.float64),
        np.asarray([0.0, 0.1], dtype=np.float64),
    )
    model_version_id = ModelVersionId.new()
    codec = TrustedJoblibArtifactCodec(allow_deserialization=True)
    artifact = codec.serialize(fitted, model_version_id, now)
    report = EvaluationReport(
        task=LearningTask.REGRESSION,
        sample_count=2,
        metrics=(MetricValue("mae", "0.05", MetricDirection.MINIMIZE),),
        calibration=(),
        slices=(),
        generated_at=now,
    )
    card = ModelCard.create(
        model_version_id=model_version_id,
        spec=spec,
        intended_use="Research batch prediction.",
        prohibited_uses=("Live autonomous trading",),
        training_dataset_fingerprint="a" * 64,
        split_plan_fingerprint="b" * 64,
        primary_metric="mae",
        cross_validation_score="0.06",
        holdout_score="0.05",
        limitations=("Historical behavior may not persist.",),
        generated_at=now,
    )
    trial = TrialSummary(
        trial_number=1,
        spec=spec,
        status=TrialStatus.COMPLETED,
        fold_scores=(Decimal("0.06"),),
        mean_score=Decimal("0.06"),
        metric_name="mae",
        metric_direction=MetricDirection.MINIMIZE,
    )
    from stock_predictor.domain.common.identifiers import ExperimentRunId

    return TrainingResult(
        run_id=ExperimentRunId.new(),
        model_version_id=model_version_id,
        selected_spec=spec,
        primary_metric="mae",
        cross_validation_score=Decimal("0.06"),
        holdout_report=report,
        artifact=artifact,
        model_card=card,
        trials=(trial,),
    )


def promotion_evidence(
    now: UtcInstant,
    *,
    passed: bool = True,
    include_approvals: bool = True,
    rejected_role: ApprovalRole | None = None,
) -> PromotionEvidence:
    gates = tuple(
        GateResult(name, passed, f"evidence:{name}", f"{name} evaluated")
        for name in DEFAULT_GATES
    )
    approvals = ()
    if include_approvals:
        approvals = tuple(
            ModelApproval(
                actor=f"reviewer-{role.value}",
                role=role,
                decision=(
                    ApprovalDecision.REJECTED
                    if rejected_role is role
                    else ApprovalDecision.APPROVED
                ),
                decided_at=now,
                comment="reviewed evidence",
            )
            for role in ApprovalRole
        )
    return PromotionEvidence(gates, approvals, now)


class StubFeaturePipeline:
    def __init__(
        self,
        features: FeatureSet,
        now: UtcInstant,
        values: dict[InstrumentId, Decimal] | None = None,
        failures: set[InstrumentId] | None = None,
    ) -> None:
        self.features = features
        self.now = now
        self.values = values or {}
        self.failures = failures or set()

    def materialize(
        self,
        feature_set: FeatureSet,
        instrument_id: InstrumentId,
        as_of: date,
        decision_cutoff: UtcInstant,
        *,
        adjusted: bool = True,
    ) -> FeatureSnapshot:
        del adjusted
        if instrument_id in self.failures:
            from stock_predictor.domain.common.errors import FeatureComputationError

            raise FeatureComputationError("synthetic feature failure")
        value = self.values.get(instrument_id, Decimal("100"))
        observation = FeatureObservation(
            feature_set.definitions[0],
            value,
            None,
            (PriceBarId.new(),),
        )
        return FeatureSnapshot(
            FeatureSnapshotId.new(),
            feature_set,
            instrument_id,
            as_of,
            decision_cutoff,
            self.now,
            (observation,),
            "c" * 64,
        )


class StubLabelService:
    def __init__(
        self,
        target: TargetDefinition,
        actual: Decimal = Decimal("0.10"),
        source_bar_id: PriceBarId | None = None,
    ) -> None:
        self.target = target
        self.actual = actual
        self.source_bar_id = source_bar_id or PriceBarId.new()
        self.fail = False

    def calculate(
        self,
        target: TargetDefinition,
        instrument_id: InstrumentId,
        as_of: date,
        outcome_cutoff: UtcInstant,
    ) -> LabelObservation:
        if self.fail:
            from stock_predictor.domain.common.errors import LabelComputationError

            raise LabelComputationError("outcome is not mature")
        from datetime import timedelta

        return LabelObservation(
            LabelId.new(),
            target,
            instrument_id,
            as_of,
            as_of + timedelta(days=1),
            outcome_cutoff,
            outcome_cutoff,
            self.actual,
            None,
            (self.source_bar_id,),
        )


class StubTrainingService:
    def __init__(self, result: TrainingResult, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def train(self, request: TrainingRequest) -> TrainingResult:
        del request
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def fixed_clock(now: UtcInstant) -> FixedClock:
    return FixedClock(now)
