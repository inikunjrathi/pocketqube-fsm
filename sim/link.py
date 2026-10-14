from __future__ import annotations

from dataclasses import dataclass

from sim.scenario import (
    LINK_MARGIN_CALIBRATION_DB,
    LINK_MARGIN_CALIBRATION_ELEVATION_DEG,
    LINK_MARGIN_DB_PER_DEG,
)

@dataclass(frozen=True)
class LinkState:
    elevation_deg: float
    is_up: bool
    margin_db: float
    meets_fade_margin: bool

def link_state(
    elevation_deg: float, min_elevation_deg: float, fade_margin_db: float
) -> LinkState:
    is_up = elevation_deg >= min_elevation_deg
    margin_db = LINK_MARGIN_CALIBRATION_DB + (
        elevation_deg - LINK_MARGIN_CALIBRATION_ELEVATION_DEG
    ) * LINK_MARGIN_DB_PER_DEG
    meets_fade_margin = margin_db >= fade_margin_db
    return LinkState(
        elevation_deg=elevation_deg,
        is_up=is_up,
        margin_db=margin_db,
        meets_fade_margin=meets_fade_margin,
    )
