from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

FEATURE_NAMES = (
    "battery_soc_pct",
    "elevation_deg",
    "is_illuminated",
    "ttc_queue_depth",
    "sstv_queue_depth",
    "codec2_m17_queue_depth",
    "top_class_rank",
    "top_class_deadline_slack_s",
    "ticks_since_last_service",
)

@dataclass(frozen=True)
class FeatureVector:
    battery_soc_pct: float
    elevation_deg: float
    is_illuminated: bool
    ttc_queue_depth: int
    sstv_queue_depth: int
    codec2_m17_queue_depth: int
    top_class_rank: int
    top_class_deadline_slack_s: float
    ticks_since_last_service: int

    def as_tuple(self) -> tuple[float, ...]:
        return (
            self.battery_soc_pct,
            self.elevation_deg,
            1.0 if self.is_illuminated else 0.0,
            float(self.ttc_queue_depth),
            float(self.sstv_queue_depth),
            float(self.codec2_m17_queue_depth),
            float(self.top_class_rank),
            self.top_class_deadline_slack_s,
            float(self.ticks_since_last_service),
        )

@dataclass(frozen=True)
class DecisionContext:

    cfg: Any
    sat: Any
    start_time: datetime
    state: str
    fsm_context: dict
    battery: Any
    remaining_items: list
    selected_item: Any
    arrivals: list
    arrival_idx: int
    event_map: Any
    min_elevation_deg: float
    fade_margin_db: float
    now: float
    dt_s: float

class Policy(Protocol):
    def decide(self, features: FeatureVector, context: DecisionContext) -> str:
        ...

class AlwaysServePolicy:

    def decide(self, features: FeatureVector, context: DecisionContext) -> str:
        return "serve"

BASELINE_POLICY = AlwaysServePolicy()
