"""Reference baseline, linear, and tree-ensemble model plugins."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, cast

import numpy as np
from numpy.typing import NDArray
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LogisticRegression, Ridge

from stock_predictor.domain.common.errors import ModelContractError
from stock_predictor.domain.modeling.models import (
    HyperParameterValue,
    LearningTask,
    ModelSignature,
    ModelSpec,
)
from stock_predictor.ports.model_plugin import (
    FittedModel,
    FloatMatrix,
    FloatVector,
)


class _Estimator(Protocol):
    def predict(self, features: FloatMatrix) -> NDArray[np.generic]:
        ...


class _ProbabilityEstimator(_Estimator, Protocol):
    def predict_proba(self, features: FloatMatrix) -> FloatMatrix:
        ...


def _validate_training_inputs(
    spec: ModelSpec,
    signature: ModelSignature,
    features: FloatMatrix,
    target: FloatVector,
    sample_weight: FloatVector | None,
    *,
    plugin_key: str,
    tasks: tuple[LearningTask, ...],
) -> None:
    if spec.plugin_key != plugin_key:
        raise ModelContractError(
            f"Spec requests {spec.plugin_key!r} but plugin is {plugin_key!r}"
        )
    if spec.task not in tasks or signature.task is not spec.task:
        raise ModelContractError("Model task is incompatible with plugin or signature")
    if features.ndim != 2 or target.ndim != 1:
        raise ModelContractError("Training features must be 2D and target must be 1D")
    if features.shape[0] != target.shape[0] or features.shape[1] != len(
        signature.feature_keys
    ):
        raise ModelContractError("Training matrix does not match model signature")
    if features.shape[0] == 0 or not np.isfinite(features).all() or not np.isfinite(target).all():
        raise ModelContractError("Training data must be non-empty and finite")
    if sample_weight is not None:
        if sample_weight.ndim != 1 or sample_weight.shape[0] != target.shape[0]:
            raise ModelContractError("Sample weights do not match training rows")
        if not np.isfinite(sample_weight).all() or np.any(sample_weight <= 0):
            raise ModelContractError("Sample weights must be finite and positive")


def _parameter(spec: ModelSpec, name: str, default: HyperParameterValue) -> HyperParameterValue:
    value = spec.parameter(name)
    return default if value is None else value


def _as_float(value: HyperParameterValue, *, name: str) -> float:
    if isinstance(value, bool) or isinstance(value, str):
        raise ModelContractError(f"Hyperparameter {name!r} must be numeric")
    return float(value)


def _as_int(value: HyperParameterValue, *, name: str) -> int:
    if isinstance(value, bool) or isinstance(value, str):
        raise ModelContractError(f"Hyperparameter {name!r} must be an integer")
    integer = int(value)
    if Decimal(str(value)) != Decimal(integer):
        raise ModelContractError(f"Hyperparameter {name!r} must be an integer")
    return integer


@dataclass(frozen=True, slots=True)
class ConstantFittedModel:
    spec: ModelSpec
    signature: ModelSignature
    constant: float

    def _validate(self, features: FloatMatrix) -> None:
        if features.ndim != 2 or features.shape[1] != len(self.signature.feature_keys):
            raise ModelContractError("Inference matrix does not match model signature")
        if not np.isfinite(features).all():
            raise ModelContractError("Inference features must be finite")

    def predict(self, features: FloatMatrix) -> FloatVector:
        self._validate(features)
        return np.full(features.shape[0], self.constant, dtype=np.float64)

    def predict_positive_probability(self, features: FloatMatrix) -> FloatVector | None:
        self._validate(features)
        if self.signature.task is LearningTask.BINARY_CLASSIFICATION:
            return np.full(features.shape[0], self.constant, dtype=np.float64)
        return None

    def native_feature_importance(self) -> FloatVector | None:
        return np.zeros(len(self.signature.feature_keys), dtype=np.float64)

    def health_check(self) -> None:
        result = self.predict(np.zeros((1, len(self.signature.feature_keys)), dtype=np.float64))
        if result.shape != (1,) or not np.isfinite(result).all():
            raise ModelContractError("Constant model health check failed")


@dataclass(frozen=True, slots=True)
class FeatureEchoFittedModel:
    spec: ModelSpec
    signature: ModelSignature
    feature_index: int
    multiplier: float

    def predict(self, features: FloatMatrix) -> FloatVector:
        if features.ndim != 2 or features.shape[1] != len(self.signature.feature_keys):
            raise ModelContractError("Inference matrix does not match model signature")
        if not np.isfinite(features).all():
            raise ModelContractError("Inference features must be finite")
        return np.asarray(features[:, self.feature_index] * self.multiplier, dtype=np.float64)

    def predict_positive_probability(self, features: FloatMatrix) -> FloatVector | None:
        self.predict(features)
        return None

    def native_feature_importance(self) -> FloatVector | None:
        values = np.zeros(len(self.signature.feature_keys), dtype=np.float64)
        values[self.feature_index] = abs(self.multiplier)
        return values

    def health_check(self) -> None:
        result = self.predict(np.zeros((1, len(self.signature.feature_keys)), dtype=np.float64))
        if result.shape != (1,):
            raise ModelContractError("Feature-echo model health check failed")


@dataclass(frozen=True, slots=True)
class SklearnFittedModel:
    spec: ModelSpec
    signature: ModelSignature
    estimator: _Estimator

    def _validate(self, features: FloatMatrix) -> None:
        if features.ndim != 2 or features.shape[1] != len(self.signature.feature_keys):
            raise ModelContractError("Inference matrix does not match model signature")
        if not np.isfinite(features).all():
            raise ModelContractError("Inference features must be finite")

    def predict(self, features: FloatMatrix) -> FloatVector:
        self._validate(features)
        raw = self.estimator.predict(features)
        result = np.asarray(raw, dtype=np.float64).reshape(-1)
        if result.shape[0] != features.shape[0] or not np.isfinite(result).all():
            raise ModelContractError("Estimator returned invalid predictions")
        return result

    def predict_positive_probability(self, features: FloatMatrix) -> FloatVector | None:
        self._validate(features)
        if not hasattr(self.estimator, "predict_proba"):
            return None
        estimator = cast(_ProbabilityEstimator, self.estimator)
        probabilities = np.asarray(estimator.predict_proba(features), dtype=np.float64)
        if probabilities.ndim != 2 or probabilities.shape != (features.shape[0], 2):
            raise ModelContractError("Binary classifier returned invalid probabilities")
        result = probabilities[:, 1]
        if not np.isfinite(result).all() or np.any((result < 0) | (result > 1)):
            raise ModelContractError("Classifier probabilities must be within [0, 1]")
        return result

    def native_feature_importance(self) -> FloatVector | None:
        estimator = self.estimator
        if hasattr(estimator, "feature_importances_"):
            result = np.asarray(
                getattr(estimator, "feature_importances_"),
                dtype=np.float64,
            ).reshape(-1)
            return result
        if hasattr(estimator, "coef_"):
            coefficients = np.asarray(getattr(estimator, "coef_"), dtype=np.float64)
            result = np.abs(coefficients).reshape(-1)
            if result.size == len(self.signature.feature_keys):
                return result
        return None

    def health_check(self) -> None:
        result = self.predict(np.zeros((1, len(self.signature.feature_keys)), dtype=np.float64))
        if result.shape != (1,):
            raise ModelContractError("Estimator health check failed")


class ZeroReturnRegressorPlugin:
    key = "baseline.zero_return"
    supported_tasks = (LearningTask.REGRESSION,)

    def fit(
        self,
        spec: ModelSpec,
        signature: ModelSignature,
        features: FloatMatrix,
        target: FloatVector,
        sample_weight: FloatVector | None = None,
    ) -> FittedModel:
        _validate_training_inputs(
            spec,
            signature,
            features,
            target,
            sample_weight,
            plugin_key=self.key,
            tasks=self.supported_tasks,
        )
        return ConstantFittedModel(spec, signature, 0.0)


class HistoricalMeanRegressorPlugin:
    key = "baseline.historical_mean"
    supported_tasks = (LearningTask.REGRESSION,)

    def fit(
        self,
        spec: ModelSpec,
        signature: ModelSignature,
        features: FloatMatrix,
        target: FloatVector,
        sample_weight: FloatVector | None = None,
    ) -> FittedModel:
        _validate_training_inputs(
            spec,
            signature,
            features,
            target,
            sample_weight,
            plugin_key=self.key,
            tasks=self.supported_tasks,
        )
        constant = float(
            np.average(target, weights=sample_weight)
            if sample_weight is not None
            else np.mean(target)
        )
        return ConstantFittedModel(spec, signature, constant)


class MajorityClassifierPlugin:
    key = "baseline.majority_classifier"
    supported_tasks = (LearningTask.BINARY_CLASSIFICATION,)

    def fit(
        self,
        spec: ModelSpec,
        signature: ModelSignature,
        features: FloatMatrix,
        target: FloatVector,
        sample_weight: FloatVector | None = None,
    ) -> FittedModel:
        _validate_training_inputs(
            spec,
            signature,
            features,
            target,
            sample_weight,
            plugin_key=self.key,
            tasks=self.supported_tasks,
        )
        if not np.isin(target, (0.0, 1.0)).all():
            raise ModelContractError("Binary-classification labels must be 0 or 1")
        probability = float(
            np.average(target, weights=sample_weight)
            if sample_weight is not None
            else np.mean(target)
        )
        return ConstantFittedModel(spec, signature, probability)


class FeatureEchoRegressorPlugin:
    """Momentum, market, or sector baseline that echoes a declared input feature."""

    key = "baseline.feature_echo"
    supported_tasks = (LearningTask.REGRESSION,)

    def fit(
        self,
        spec: ModelSpec,
        signature: ModelSignature,
        features: FloatMatrix,
        target: FloatVector,
        sample_weight: FloatVector | None = None,
    ) -> FittedModel:
        _validate_training_inputs(
            spec,
            signature,
            features,
            target,
            sample_weight,
            plugin_key=self.key,
            tasks=self.supported_tasks,
        )
        feature_name = _parameter(spec, "feature_name", "")
        if not isinstance(feature_name, str) or feature_name not in signature.feature_keys:
            raise ModelContractError(
                "feature_echo requires a feature_name present in the model signature"
            )
        multiplier = _as_float(_parameter(spec, "multiplier", Decimal(1)), name="multiplier")
        return FeatureEchoFittedModel(
            spec,
            signature,
            signature.feature_keys.index(feature_name),
            multiplier,
        )


class RidgeRegressionPlugin:
    key = "linear.ridge"
    supported_tasks = (LearningTask.REGRESSION,)

    def fit(
        self,
        spec: ModelSpec,
        signature: ModelSignature,
        features: FloatMatrix,
        target: FloatVector,
        sample_weight: FloatVector | None = None,
    ) -> FittedModel:
        _validate_training_inputs(
            spec,
            signature,
            features,
            target,
            sample_weight,
            plugin_key=self.key,
            tasks=self.supported_tasks,
        )
        alpha = _as_float(_parameter(spec, "alpha", Decimal(1)), name="alpha")
        if alpha < 0:
            raise ModelContractError("Ridge alpha cannot be negative")
        estimator = Ridge(alpha=alpha, random_state=spec.random_seed)
        estimator.fit(features, target, sample_weight=sample_weight)
        return SklearnFittedModel(spec, signature, estimator)


class LogisticRegressionPlugin:
    key = "linear.logistic"
    supported_tasks = (LearningTask.BINARY_CLASSIFICATION,)

    def fit(
        self,
        spec: ModelSpec,
        signature: ModelSignature,
        features: FloatMatrix,
        target: FloatVector,
        sample_weight: FloatVector | None = None,
    ) -> FittedModel:
        _validate_training_inputs(
            spec,
            signature,
            features,
            target,
            sample_weight,
            plugin_key=self.key,
            tasks=self.supported_tasks,
        )
        if set(np.unique(target)) != {0.0, 1.0}:
            raise ModelContractError("Logistic regression requires both binary classes")
        c_value = _as_float(_parameter(spec, "c", Decimal(1)), name="c")
        max_iter = _as_int(_parameter(spec, "max_iter", 1000), name="max_iter")
        if c_value <= 0 or max_iter <= 0:
            raise ModelContractError("Logistic C and max_iter must be positive")
        estimator = LogisticRegression(
            C=c_value,
            max_iter=max_iter,
            random_state=spec.random_seed,
            solver="lbfgs",
        )
        estimator.fit(features, target.astype(np.int64), sample_weight=sample_weight)
        return SklearnFittedModel(spec, signature, estimator)


class RandomForestRegressorPlugin:
    key = "tree.random_forest_regressor"
    supported_tasks = (LearningTask.REGRESSION,)

    def fit(
        self,
        spec: ModelSpec,
        signature: ModelSignature,
        features: FloatMatrix,
        target: FloatVector,
        sample_weight: FloatVector | None = None,
    ) -> FittedModel:
        _validate_training_inputs(
            spec,
            signature,
            features,
            target,
            sample_weight,
            plugin_key=self.key,
            tasks=self.supported_tasks,
        )
        n_estimators = _as_int(
            _parameter(spec, "n_estimators", 100), name="n_estimators"
        )
        minimum_leaf = _as_int(
            _parameter(spec, "min_samples_leaf", 1),
            name="min_samples_leaf",
        )
        self._validate_forest_shape(n_estimators, minimum_leaf)
        estimator = RandomForestRegressor(
            n_estimators=n_estimators,
            max_depth=self._optional_depth(spec),
            min_samples_leaf=minimum_leaf,
            random_state=spec.random_seed,
            n_jobs=1,
        )
        estimator.fit(features, target, sample_weight=sample_weight)
        return SklearnFittedModel(spec, signature, estimator)

    @staticmethod
    def _validate_forest_shape(n_estimators: int, minimum_leaf: int) -> None:
        if n_estimators <= 0 or minimum_leaf <= 0:
            raise ModelContractError(
                "Random-forest n_estimators and min_samples_leaf must be positive"
            )

    @staticmethod
    def _optional_depth(spec: ModelSpec) -> int | None:
        value = _parameter(spec, "max_depth", "none")
        if isinstance(value, str) and value.lower() == "none":
            return None
        depth = _as_int(value, name="max_depth")
        if depth <= 0:
            raise ModelContractError("Random-forest max_depth must be positive")
        return depth


class RandomForestClassifierPlugin:
    key = "tree.random_forest_classifier"
    supported_tasks = (LearningTask.BINARY_CLASSIFICATION,)

    def fit(
        self,
        spec: ModelSpec,
        signature: ModelSignature,
        features: FloatMatrix,
        target: FloatVector,
        sample_weight: FloatVector | None = None,
    ) -> FittedModel:
        _validate_training_inputs(
            spec,
            signature,
            features,
            target,
            sample_weight,
            plugin_key=self.key,
            tasks=self.supported_tasks,
        )
        if set(np.unique(target)) != {0.0, 1.0}:
            raise ModelContractError("Random-forest classifier requires both binary classes")
        n_estimators = _as_int(
            _parameter(spec, "n_estimators", 100), name="n_estimators"
        )
        minimum_leaf = _as_int(
            _parameter(spec, "min_samples_leaf", 1),
            name="min_samples_leaf",
        )
        RandomForestRegressorPlugin._validate_forest_shape(
            n_estimators,
            minimum_leaf,
        )
        estimator = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=RandomForestRegressorPlugin._optional_depth(spec),
            min_samples_leaf=minimum_leaf,
            random_state=spec.random_seed,
            n_jobs=1,
        )
        estimator.fit(features, target.astype(np.int64), sample_weight=sample_weight)
        return SklearnFittedModel(spec, signature, estimator)
