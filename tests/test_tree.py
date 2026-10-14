from __future__ import annotations

import random

import pytest

from policy.base import FEATURE_NAMES
from policy.tree import MAX_DEPTH, export_if_else, fit, predict

def test_fit_predict_on_separable_data():
    rows = [
        ((0.0, 0.0), "hold"), ((0.0, 1.0), "hold"), ((1.0, 0.0), "hold"),
        ((10.0, 0.0), "serve"), ((10.0, 1.0), "serve"), ((11.0, 0.0), "serve"),
    ] * 2
    tree = fit(rows)
    assert predict(tree, (0.0, 0.0)) == "hold"
    assert predict(tree, (10.0, 1.0)) == "serve"
    assert predict(tree, (10.5, 0.5)) == "serve"

def test_max_depth_is_respected():
    def depth_of(node, d=0):
        if node.prediction is not None:
            return d
        return max(depth_of(node.left, d + 1), depth_of(node.right, d + 1))

    rng = random.Random(1)
    rows = [
        ((rng.random(), rng.random()), "serve" if rng.random() > 0.5 else "hold")
        for _ in range(200)
    ]
    tree = fit(rows)
    assert depth_of(tree) <= MAX_DEPTH

def test_export_if_else_matches_predict():
    n = len(FEATURE_NAMES)

    def row(battery: float, label: str):
        return ((battery,) + (0.0,) * (n - 1), label)

    rows = [row(5.0, "hold")] * 5 + [row(90.0, "serve")] * 5
    tree = fit(rows)
    source = export_if_else(tree)

    namespace: dict = {}
    exec(compile(source, "<export>", "exec"), namespace)
    predict_exported = namespace["predict_exported"]

    for battery, expected in [(5.0, "hold"), (90.0, "serve")]:
        features = (battery,) + (0.0,) * (n - 1)
        feature_dict = dict(zip(FEATURE_NAMES, features))
        assert predict(tree, features) == expected
        assert predict_exported(feature_dict) == expected

def test_fit_on_single_class_returns_a_leaf():
    rows = [((0.0,), "serve")] * 6
    tree = fit(rows)
    assert tree.prediction == "serve"
    assert tree.feature_index is None

def test_fit_on_empty_rows_raises_value_error():
    with pytest.raises(ValueError):
        fit([])

def test_train_produces_a_policy_matching_predict():
    from policy.dataset import TrainingRow
    from policy.base import FeatureVector
    from policy.tree import predict, train

    def fv(battery: float) -> FeatureVector:
        return FeatureVector(
            battery_soc_pct=battery, elevation_deg=0.0, is_illuminated=False,
            ttc_queue_depth=0, sstv_queue_depth=0, codec2_m17_queue_depth=0,
            top_class_rank=0, top_class_deadline_slack_s=0.0, ticks_since_last_service=0,
        )

    rows = (
        [TrainingRow(features=fv(5.0), label="hold")] * 5
        + [TrainingRow(features=fv(90.0), label="serve")] * 5
    )
    policy = train(rows)
    decision_low = policy.decide(fv(5.0), context=None)
    decision_high = policy.decide(fv(90.0), context=None)
    assert decision_low == "hold"
    assert decision_high == "serve"
    assert decision_low == predict(policy._root, fv(5.0).as_tuple())

def test_sweep_best_split_matches_brute_force_rescan():
    from policy.tree import MIN_SAMPLES_LEAF, _best_split, _gini

    def brute(rows):
        parent = _gini([label for _, label in rows])
        best = None
        for fi in range(len(rows[0][0])):
            values = sorted({f[fi] for f, _ in rows})
            for a, b in zip(values, values[1:]):
                thr = (a + b) / 2.0
                left = [lab for f, lab in rows if f[fi] <= thr]
                right = [lab for f, lab in rows if f[fi] > thr]
                if len(left) < MIN_SAMPLES_LEAF or len(right) < MIN_SAMPLES_LEAF:
                    continue
                w = len(left) / len(rows) * _gini(left) + len(right) / len(rows) * _gini(right)
                if w < parent and (best is None or w < best[2]):
                    best = (fi, thr, w)
        return best

    rng = random.Random(7)
    for _ in range(20):
        rows = [
            ((float(rng.randint(0, 9)), rng.random(), float(rng.randint(0, 1))),
             "hold" if rng.random() < 0.3 else "serve")
            for _ in range(60)
        ]
        fast, slow = _best_split(rows), brute(rows)
        assert (fast is None) == (slow is None)
        if fast is not None:
            assert fast[:2] == slow[:2]
            assert fast[2] == pytest.approx(slow[2])
