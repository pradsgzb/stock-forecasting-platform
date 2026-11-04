from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest

from stock_predictor.adapters.models.baselines import (
    FeatureEchoRegressorPlugin,
    HistoricalMeanRegressorPlugin,
    LogisticRegressionPlugin,
    MajorityClassifierPlugin,
    RandomForestClassifierPlugin,
    RandomForestRegressorPlugin,
    RidgeRegressionPlugin,
    ZeroReturnRegressorPlugin,
)
from stock_predictor.domain.common.errors import ModelContractError
from stock_predictor.domain.modeling.models import (
    LearningTask,
    ModelFamily,
    ModelSpec,
)
from tests.helpers.modeling import signature


def spec(plugin_key, *, task=LearningTask.REGRESSION, parameters=()):
    return ModelSpec(
        plugin_key.replace(".", "_"),
        "1",
        (
            ModelFamily.TREE_ENSEMBLE
            if plugin_key.startswith("tree")
            else ModelFamily.LINEAR
            if plugin_key.startswith("linear")
            else ModelFamily.BASELINE
        ),
        task,
        plugin_key,
        7,
        parameters,
    )


def regression_data():
    features = np.asarray(
        [[-2.0, 0.0], [-1.0, 0.5], [0.0, 1.0], [1.0, 1.5], [2.0, 2.0]],
        dtype=np.float64,
    )
    target = np.asarray([-1.0, -0.5, 0.0, 0.5, 1.0], dtype=np.float64)
    weights = np.asarray([1.0, 1.0, 1.0, 2.0, 2.0], dtype=np.float64)
    return features, target, weights


def classification_data():
    features = np.asarray(
        [[-2.0, 0.0], [-1.0, 0.5], [0.0, 1.0], [1.0, 1.5], [2.0, 2.0], [3.0, 2.5]],
        dtype=np.float64,
    )
    target = np.asarray([0.0, 0.0, 0.0, 1.0, 1.0, 1.0], dtype=np.float64)
    return features, target


def test_regression_baselines_and_linear_models_follow_contract() -> None:
    features, target, weights = regression_data()
    model_signature = signature()

    zero = ZeroReturnRegressorPlugin().fit(
        spec("baseline.zero_return"),
        model_signature,
        features,
        target,
    )
    mean = HistoricalMeanRegressorPlugin().fit(
        spec("baseline.historical_mean"),
        model_signature,
        features,
        target,
        weights,
    )
    echo = FeatureEchoRegressorPlugin().fit(
        spec(
            "baseline.feature_echo",
            parameters=(
                ("feature_name", "momentum@1.0.0"),
                ("multiplier", Decimal("2")),
            ),
        ),
        model_signature,
        features,
        target,
    )
    ridge = RidgeRegressionPlugin().fit(
        spec("linear.ridge", parameters=(("alpha", Decimal("0.1")),)),
        model_signature,
        features,
        target,
        weights,
    )

    assert np.all(zero.predict(features) == 0)
    assert np.allclose(mean.predict(features), np.average(target, weights=weights))
    assert np.allclose(echo.predict(features), features[:, 0] * 2)
    assert ridge.predict(features).shape == target.shape
    assert ridge.native_feature_importance().shape == (2,)
    assert ridge.predict_positive_probability(features) is None
    ridge.health_check()


def test_tree_regressor_and_classifiers_return_finite_outputs() -> None:
    features, target, _ = regression_data()
    regressor = RandomForestRegressorPlugin().fit(
        spec(
            "tree.random_forest_regressor",
            parameters=(
                ("n_estimators", 10),
                ("max_depth", 3),
                ("min_samples_leaf", 1),
            ),
        ),
        signature(),
        features,
        target,
    )
    assert np.isfinite(regressor.predict(features)).all()
    assert regressor.native_feature_importance().shape == (2,)

    classification_features, classification_target = classification_data()
    logistic = LogisticRegressionPlugin().fit(
        spec(
            "linear.logistic",
            task=LearningTask.BINARY_CLASSIFICATION,
            parameters=(("c", Decimal("1")), ("max_iter", 200)),
        ),
        signature(classification=True),
        classification_features,
        classification_target,
    )
    forest = RandomForestClassifierPlugin().fit(
        spec(
            "tree.random_forest_classifier",
            task=LearningTask.BINARY_CLASSIFICATION,
            parameters=(
                ("n_estimators", 10),
                ("max_depth", "none"),
                ("min_samples_leaf", 1),
            ),
        ),
        signature(classification=True),
        classification_features,
        classification_target,
    )
    for model in (logistic, forest):
        probabilities = model.predict_positive_probability(classification_features)
        assert probabilities.shape == classification_target.shape
        assert np.all((probabilities >= 0) & (probabilities <= 1))
        assert model.predict(classification_features).shape == classification_target.shape


def test_majority_classifier_returns_empirical_probability() -> None:
    features, target = classification_data()
    model = MajorityClassifierPlugin().fit(
        spec(
            "baseline.majority_classifier",
            task=LearningTask.BINARY_CLASSIFICATION,
        ),
        signature(classification=True),
        features,
        target,
    )
    assert np.allclose(model.predict_positive_probability(features), 0.5)
    assert np.allclose(model.predict(features), 0.5)


def test_model_plugins_reject_invalid_contracts_and_parameters() -> None:
    features, target, _ = regression_data()
    with pytest.raises(ModelContractError, match="plugin is"):
        ZeroReturnRegressorPlugin().fit(
            spec("baseline.historical_mean"),
            signature(),
            features,
            target,
        )
    with pytest.raises(ModelContractError, match="2D"):
        ZeroReturnRegressorPlugin().fit(
            spec("baseline.zero_return"),
            signature(),
            features[:, 0],
            target,
        )
    with pytest.raises(ModelContractError, match="feature_name"):
        FeatureEchoRegressorPlugin().fit(
            spec(
                "baseline.feature_echo",
                parameters=(("feature_name", "missing"),),
            ),
            signature(),
            features,
            target,
        )
    with pytest.raises(ModelContractError, match="alpha"):
        RidgeRegressionPlugin().fit(
            spec("linear.ridge", parameters=(("alpha", Decimal("-1")),)),
            signature(),
            features,
            target,
        )
    classification_features, _ = classification_data()
    with pytest.raises(ModelContractError, match="both binary"):
        LogisticRegressionPlugin().fit(
            spec("linear.logistic", task=LearningTask.BINARY_CLASSIFICATION),
            signature(classification=True),
            classification_features,
            np.zeros(classification_features.shape[0], dtype=np.float64),
        )
    with pytest.raises(ModelContractError, match="max_depth"):
        RandomForestRegressorPlugin().fit(
            spec(
                "tree.random_forest_regressor",
                parameters=(("max_depth", 0),),
            ),
            signature(),
            features,
            target,
        )
    with pytest.raises(ModelContractError, match="must be positive"):
        RandomForestRegressorPlugin().fit(
            spec(
                "tree.random_forest_regressor",
                parameters=(("n_estimators", 0),),
            ),
            signature(),
            features,
            target,
        )


def test_fitted_models_reject_invalid_inference_matrices() -> None:
    features, target, _ = regression_data()
    model = ZeroReturnRegressorPlugin().fit(
        spec("baseline.zero_return"),
        signature(),
        features,
        target,
    )
    with pytest.raises(ModelContractError, match="signature"):
        model.predict(np.zeros((2, 1), dtype=np.float64))
    invalid = features.copy()
    invalid[0, 0] = np.nan
    with pytest.raises(ModelContractError, match="finite"):
        model.predict(invalid)
