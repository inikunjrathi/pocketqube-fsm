from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from sgp4.api import jday

from engine.config_loader import Config
from sim.event_mapping import build_event_map, scheduler_select_event_names
from sim.scenario import (
    COMMS_BURST_DURATION_S,
    DRAW_W_COMMS_SSTV,
    DRAW_W_COMMS_TTC,
    DRAW_W_COMMS_VOICE,
    DRAW_W_IDLE,
    EARTH_RADIUS_KM,
)

_OBLIQUITY_DEG = 23.439

_COMMS_BURST_DRAW_W_BY_CATEGORY = {
    "COMMS_TTC": DRAW_W_COMMS_TTC,
    "COMMS_SSTV": DRAW_W_COMMS_SSTV,
    "COMMS_VOICE": DRAW_W_COMMS_VOICE,
}

TRANSMIT_CATEGORY_BY_DATA_CLASS = {
    "TTC": "COMMS_TTC",
    "SSTV": "COMMS_SSTV",
    "CODEC2_M17": "COMMS_VOICE",
}

SERVED_CLASS = "<served>"

STATE_TRANSMIT_CLASS: dict[str, dict[str, str | None]] = {
    "config-a": {"S-06": "TTC", "S-07": "SSTV", "S-08": "CODEC2_M17", "S-09": None},
    "config-b": {"S-05": SERVED_CLASS, "S-06": None},
    "config-c": {"S-05": SERVED_CLASS, "S-06": None},
}

class PowerModelError(ValueError):
    pass

def transmit_class_map(cfg: Config) -> dict[str, str | None]:
    table = STATE_TRANSMIT_CLASS.get(cfg.config_id)
    if table is None:
        raise PowerModelError(
            f"no transmit-class row for {cfg.config_id!r} in sim.power.STATE_TRANSMIT_CLASS"
        )
    comms = {sid for sid, st in cfg.states.items() if st.category == "comms-mode"}
    if set(table) != comms:
        raise PowerModelError(
            f"{cfg.config_id}: transmit-class table states {sorted(table)} != "
            f"comms-mode states {sorted(comms)}"
        )

    event_map = build_event_map(cfg)
    classes = list(cfg.data_class_priority)
    targets_by_class: dict[str, set[str]] = {}
    for dc in classes:
        names = scheduler_select_event_names(event_map, dc)
        if not names:
            raise PowerModelError(f"{cfg.config_id}: no scheduler-select event for {dc}")
        ev = event_map.by_name[names[0]]
        targets_by_class[dc] = {t.to for t in cfg.transitions if t.event == ev and t.to}

    for sid, tx in table.items():
        hit = {dc for dc, tg in targets_by_class.items() if sid in tg}
        if tx is None:
            ok = not hit
        elif tx == SERVED_CLASS:
            ok = hit == set(classes)
        else:
            ok = tx in TRANSMIT_CATEGORY_BY_DATA_CLASS and hit == {tx}
        if not ok:
            raise PowerModelError(
                f"{cfg.config_id}: state {sid} mapped to {tx!r} but config routes "
                f"data classes {sorted(hit)} into it"
            )
    return dict(table)

def resolve_transmit_class(
    table: dict[str, str | None], state_id: str, served_class: str | None
) -> str | None:
    tx = table.get(state_id)
    return served_class if tx == SERVED_CLASS else tx

def transmit_draw_w(transmit_class: str | None, time_in_mode_s: float = 0.0) -> float:
    if transmit_class is None or time_in_mode_s >= COMMS_BURST_DURATION_S:
        return DRAW_W_IDLE
    return _COMMS_BURST_DRAW_W_BY_CATEGORY[TRANSMIT_CATEGORY_BY_DATA_CLASS[transmit_class]]

def _sun_unit_vector_eci(when: datetime) -> tuple[float, float, float]:
    jd, fr = jday(
        when.year,
        when.month,
        when.day,
        when.hour,
        when.minute,
        when.second + when.microsecond / 1e6,
    )
    days_since_j2000 = (jd + fr) - 2451545.0

    mean_longitude_deg = (280.460 + 0.9856474 * days_since_j2000) % 360.0
    mean_anomaly_deg = (357.528 + 0.9856003 * days_since_j2000) % 360.0
    mean_anomaly_rad = math.radians(mean_anomaly_deg)

    ecliptic_longitude_deg = (
        mean_longitude_deg
        + 1.915 * math.sin(mean_anomaly_rad)
        + 0.020 * math.sin(2.0 * mean_anomaly_rad)
    )
    lam = math.radians(ecliptic_longitude_deg)
    eps = math.radians(_OBLIQUITY_DEG)

    return (
        math.cos(lam),
        math.cos(eps) * math.sin(lam),
        math.sin(eps) * math.sin(lam),
    )

def is_illuminated(
    position_eci_km: tuple[float, float, float], when: datetime
) -> bool:
    sun_dir = _sun_unit_vector_eci(when)
    x, y, z = position_eci_km

    projection_km = x * sun_dir[0] + y * sun_dir[1] + z * sun_dir[2]
    if projection_km >= 0.0:
        return True

    perp_x = x - projection_km * sun_dir[0]
    perp_y = y - projection_km * sun_dir[1]
    perp_z = z - projection_km * sun_dir[2]
    perp_distance_km = math.sqrt(perp_x * perp_x + perp_y * perp_y + perp_z * perp_z)

    return perp_distance_km > EARTH_RADIUS_KM

@dataclass
class BatteryState:

    soc_pct: float

def step_battery(
    battery: BatteryState,
    illuminated: bool,
    draw_w: float,
    dt_s: float,
    *,
    capacity_wh: float,
    solar_gen_w: float,
) -> BatteryState:
    net_power_w = (solar_gen_w if illuminated else 0.0) - draw_w
    energy_delta_wh = net_power_w * dt_s / 3600.0
    new_soc_pct = battery.soc_pct + energy_delta_wh / capacity_wh * 100.0
    new_soc_pct = max(0.0, min(100.0, new_soc_pct))
    return BatteryState(soc_pct=new_soc_pct)

def draw_for_state_category(category: str, time_in_state_s: float = 0.0) -> float:
    burst_draw_w = _COMMS_BURST_DRAW_W_BY_CATEGORY.get(category)
    if burst_draw_w is None:
        return DRAW_W_IDLE
    if time_in_state_s < COMMS_BURST_DURATION_S:
        return burst_draw_w
    return DRAW_W_IDLE
