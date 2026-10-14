from __future__ import annotations

import math

from policy.base import FEATURE_NAMES, AlwaysServePolicy, BASELINE_POLICY, FeatureVector

def test_feature_vector_as_tuple_matches_feature_names_order():
    fv = FeatureVector(
        battery_soc_pct=80.0, elevation_deg=45.0, is_illuminated=True,
        ttc_queue_depth=1, sstv_queue_depth=2, codec2_m17_queue_depth=0,
        top_class_rank=0, top_class_deadline_slack_s=50.0, ticks_since_last_service=3,
    )
    assert len(fv.as_tuple()) == len(FEATURE_NAMES)
    assert fv.as_tuple() == (80.0, 45.0, 1.0, 1.0, 2.0, 0.0, 0.0, 50.0, 3.0)

def test_feature_vector_is_illuminated_encodes_as_zero_one():
    fv = FeatureVector(
        battery_soc_pct=0.0, elevation_deg=0.0, is_illuminated=False,
        ttc_queue_depth=0, sstv_queue_depth=0, codec2_m17_queue_depth=0,
        top_class_rank=0, top_class_deadline_slack_s=math.inf, ticks_since_last_service=0,
    )
    assert fv.as_tuple()[2] == 0.0

def test_always_serve_policy_always_serves():
    decision = AlwaysServePolicy().decide(features=None, context=None)
    assert decision == "serve"
    assert BASELINE_POLICY.decide(features=None, context=None) == "serve"
