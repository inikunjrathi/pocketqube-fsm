from __future__ import annotations

import math

from engine.scheduler import Item
from policy.base import FeatureVector

_QUEUE_DATA_CLASSES = ("TTC", "SSTV", "CODEC2_M17")

def build_features(
    *,
    priority_order: list[str],
    candidate_classes: list[str],
    selected_item: Item,
    now: float,
    battery_soc_pct: float,
    elevation_deg: float,
    is_illuminated: bool,
    ticks_since_last_service: int,
) -> FeatureVector:
    counts = {cls: candidate_classes.count(cls) for cls in _QUEUE_DATA_CLASSES}
    top_class_rank = priority_order.index(selected_item.data_class)
    deadline_slack = (
        selected_item.deadline - now if selected_item.deadline is not None else math.inf
    )
    return FeatureVector(
        battery_soc_pct=battery_soc_pct,
        elevation_deg=elevation_deg,
        is_illuminated=is_illuminated,
        ttc_queue_depth=counts["TTC"],
        sstv_queue_depth=counts["SSTV"],
        codec2_m17_queue_depth=counts["CODEC2_M17"],
        top_class_rank=top_class_rank,
        top_class_deadline_slack_s=deadline_slack,
        ticks_since_last_service=ticks_since_last_service,
    )
