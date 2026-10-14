from __future__ import annotations

import math

from engine.scheduler import Item
from policy.features import build_features

PRIORITY = ["TTC", "SSTV", "CODEC2_M17"]

def test_build_features_basic_snapshot():
    item = Item(id="i1", data_class="SSTV", deadline=150.0)
    fv = build_features(
        priority_order=PRIORITY,
        candidate_classes=["SSTV", "SSTV", "CODEC2_M17"],
        selected_item=item,
        now=100.0,
        battery_soc_pct=80.0,
        elevation_deg=45.0,
        is_illuminated=True,
        ticks_since_last_service=3,
    )
    assert fv.battery_soc_pct == 80.0
    assert fv.elevation_deg == 45.0
    assert fv.is_illuminated is True
    assert fv.ttc_queue_depth == 0
    assert fv.sstv_queue_depth == 2
    assert fv.codec2_m17_queue_depth == 1
    assert fv.top_class_rank == 1
    assert fv.top_class_deadline_slack_s == 50.0
    assert fv.ticks_since_last_service == 3

def test_build_features_no_deadline_is_inf():
    item = Item(id="i1", data_class="TTC", deadline=None)
    fv = build_features(
        priority_order=PRIORITY, candidate_classes=["TTC"], selected_item=item, now=0.0,
        battery_soc_pct=100.0, elevation_deg=90.0, is_illuminated=True,
        ticks_since_last_service=0,
    )
    assert fv.top_class_deadline_slack_s == math.inf

def test_build_features_top_class_rank_for_ttc():
    item = Item(id="i1", data_class="TTC", deadline=None)
    fv = build_features(
        priority_order=PRIORITY, candidate_classes=["TTC"], selected_item=item, now=0.0,
        battery_soc_pct=100.0, elevation_deg=90.0, is_illuminated=False,
        ticks_since_last_service=0,
    )
    assert fv.top_class_rank == 0
