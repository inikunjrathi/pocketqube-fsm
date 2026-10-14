from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

from engine.config_loader import load_config
from engine.guards import evaluate_guard
from sim.power import (
    BatteryState,
    draw_for_state_category,
    is_illuminated,
    step_battery,
)
from sim.scenario import BATTERY_CAPACITY_WH, COMMS_BURST_DURATION_S, SOLAR_GEN_W

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_A = REPO_ROOT / "config" / "config-a.yaml"

REFERENCE_POSITION_ECI_KM = (6903.0, 0.0, 0.0)
REFERENCE_WHEN = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

def test_soc_stays_in_bounds():
    battery = BatteryState(soc_pct=5.0)
    high_draw = draw_for_state_category("COMMS_SSTV")
    for _ in range(1000):
        battery = step_battery(
            battery,
            illuminated=False,
            draw_w=high_draw,
            dt_s=600.0,
            capacity_wh=BATTERY_CAPACITY_WH,
            solar_gen_w=SOLAR_GEN_W,
        )
        assert battery.soc_pct >= 0.0

    battery = BatteryState(soc_pct=95.0)
    idle_draw = draw_for_state_category("IDLE")
    for _ in range(1000):
        battery = step_battery(
            battery,
            illuminated=True,
            draw_w=idle_draw,
            dt_s=600.0,
            capacity_wh=BATTERY_CAPACITY_WH,
            solar_gen_w=SOLAR_GEN_W,
        )
        assert battery.soc_pct <= 100.0

def test_illuminated_charges_more_than_eclipsed():
    start = BatteryState(soc_pct=50.0)
    draw_w = draw_for_state_category("IDLE")

    illuminated_result = step_battery(
        start,
        illuminated=True,
        draw_w=draw_w,
        dt_s=600.0,
        capacity_wh=BATTERY_CAPACITY_WH,
        solar_gen_w=SOLAR_GEN_W,
    )
    eclipsed_result = step_battery(
        start,
        illuminated=False,
        draw_w=draw_w,
        dt_s=600.0,
        capacity_wh=BATTERY_CAPACITY_WH,
        solar_gen_w=SOLAR_GEN_W,
    )

    assert illuminated_result.soc_pct >= eclipsed_result.soc_pct
    assert start.soc_pct == 50.0

def test_comms_mode_draws_more_than_idle():
    assert draw_for_state_category("COMMS_SSTV") > draw_for_state_category("IDLE")

def test_comms_burst_draw_active_at_mode_entry():
    from sim.scenario import DRAW_W_COMMS_TTC

    assert draw_for_state_category("COMMS_TTC", time_in_state_s=0.0) == DRAW_W_COMMS_TTC

def test_comms_burst_draw_still_active_just_before_burst_ends():
    from sim.scenario import DRAW_W_COMMS_TTC

    assert (
        draw_for_state_category("COMMS_TTC", time_in_state_s=COMMS_BURST_DURATION_S - 1.0)
        == DRAW_W_COMMS_TTC
    )

def test_comms_draw_falls_back_to_idle_after_burst_window_elapses():
    from sim.scenario import DRAW_W_IDLE

    assert (
        draw_for_state_category("COMMS_TTC", time_in_state_s=COMMS_BURST_DURATION_S)
        == DRAW_W_IDLE
    )
    assert (
        draw_for_state_category("COMMS_TTC", time_in_state_s=COMMS_BURST_DURATION_S + 500.0)
        == DRAW_W_IDLE
    )

def test_idle_category_ignores_time_in_state():
    from sim.scenario import DRAW_W_IDLE

    assert draw_for_state_category("IDLE", time_in_state_s=0.0) == DRAW_W_IDLE
    assert draw_for_state_category("IDLE", time_in_state_s=1_000_000.0) == DRAW_W_IDLE

def test_draw_for_state_category_defaults_to_burst_active():
    from sim.scenario import DRAW_W_COMMS_TTC

    assert draw_for_state_category("COMMS_TTC") == DRAW_W_COMMS_TTC

def test_low_power_scenario_crosses_guard_threshold():
    cfg_a = load_config(CONFIG_A)
    threshold_pct = cfg_a.param_value("P-013")

    guard_expr = next(t.guard for t in cfg_a.transitions if t.id == "T-15")
    assert guard_expr is not None
    assert "battery_soc" in guard_expr and "P-013" in guard_expr

    params = {pid: pdef.value for pid, pdef in cfg_a.parameters.items()}

    battery = BatteryState(soc_pct=100.0)
    high_draw = draw_for_state_category("COMMS_SSTV")
    max_steps = 10_000
    steps = 0
    while battery.soc_pct > threshold_pct and steps < max_steps:
        battery = step_battery(
            battery,
            illuminated=False,
            draw_w=high_draw,
            dt_s=600.0,
            capacity_wh=BATTERY_CAPACITY_WH,
            solar_gen_w=SOLAR_GEN_W,
        )
        steps += 1

    assert steps < max_steps, "battery never crossed the P-013 threshold"
    assert battery.soc_pct <= threshold_pct

    result = evaluate_guard(
        guard_expr,
        context={},
        telemetry={"battery_soc": battery.soc_pct},
        params=params,
        now=0.0,
    )
    assert result is True

def test_is_illuminated_is_deterministic():
    first = is_illuminated(REFERENCE_POSITION_ECI_KM, REFERENCE_WHEN)
    second = is_illuminated(REFERENCE_POSITION_ECI_KM, REFERENCE_WHEN)
    assert first == second
    assert isinstance(first, bool)

def test_no_network_access():
    import sim.power as power_module

    source = Path(power_module.__file__).read_text()
    tree = ast.parse(source)

    banned = {"requests", "urllib", "socket"}
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module.split(".")[0])

    assert not (imported_modules & banned), (
        f"sim/power.py imports network modules: {imported_modules & banned}"
    )

import dataclasses
import hashlib

import pytest

from sim.power import (
    SERVED_CLASS,
    STATE_TRANSMIT_CLASS,
    PowerModelError,
    resolve_transmit_class,
    transmit_class_map,
    transmit_draw_w,
)
from sim.scenario import DRAW_W_COMMS_TTC, DRAW_W_IDLE

def _cfg(letter):
    return load_config(REPO_ROOT / "config" / f"config-{letter}.yaml")

def test_transmit_class_map_matches_each_shipped_config():
    assert transmit_class_map(_cfg("a")) == {
        "S-06": "TTC", "S-07": "SSTV", "S-08": "CODEC2_M17", "S-09": None,
    }
    for letter in "bc":
        assert transmit_class_map(_cfg(letter)) == {"S-05": SERVED_CLASS, "S-06": None}

def test_transmit_class_map_rejects_unknown_config():
    cfg = dataclasses.replace(_cfg("b"), config_id="config-x")
    with pytest.raises(PowerModelError, match="no transmit-class row"):
        transmit_class_map(cfg)

@pytest.mark.parametrize("bad_row", [
    {"S-05": SERVED_CLASS},
    {"S-05": SERVED_CLASS, "S-06": None, "S-99": None},
    {"S-05": "TTC", "S-06": None},
    {"S-05": SERVED_CLASS, "S-06": "SSTV"},
])
def test_transmit_class_map_rejects_rows_that_contradict_the_config(monkeypatch, bad_row):
    monkeypatch.setitem(STATE_TRANSMIT_CLASS, "config-b", bad_row)
    with pytest.raises(PowerModelError):
        transmit_class_map(_cfg("b"))

def test_served_state_follows_served_class_and_burst_window():
    table = transmit_class_map(_cfg("b"))
    assert resolve_transmit_class(table, "S-05", "SSTV") == "SSTV"
    assert resolve_transmit_class(table, "S-05", None) is None
    assert resolve_transmit_class(table, "S-06", "TTC") is None
    assert resolve_transmit_class(table, "S-01", "TTC") is None
    assert transmit_draw_w("TTC", 0.0) == DRAW_W_COMMS_TTC
    assert transmit_draw_w("TTC", COMMS_BURST_DURATION_S) == DRAW_W_IDLE
    assert transmit_draw_w(None, 0.0) == DRAW_W_IDLE
    for name, dc in (("COMMS_TTC", "TTC"), ("COMMS_SSTV", "SSTV"), ("COMMS_VOICE", "CODEC2_M17")):
        assert draw_for_state_category(name) == transmit_draw_w(dc)

def _seed42_trace(letter):
    from sim.driver import run_simulation

    soc = []
    r = run_simulation(
        _cfg(letter), duration_s=172_800.0, dt_s=10.0, seed=42,
        tick_hook=lambda t, s: soc.append(s["battery_soc_pct"]),
    )
    return r, soc

def test_config_a_seed42_is_bit_identical_to_pre_0009_name_mapping():
    r, soc = _seed42_trace("a")
    digest = hashlib.sha256(repr((
        [(d.item_id, d.delivery_time_s, d.energy_wh) for d in r.deliveries], soc,
    )).encode()).hexdigest()
    assert digest == "6220aca3012f17815bd4a3a1fb2aaca293016b94beb1a0ca0266ad3c85dc144b"

def test_config_b_downlink_is_charged_transmit_draw_not_idle():
    a, _ = _seed42_trace("a")
    b, soc_b = _seed42_trace("b")
    assert [d.energy_wh for d in b.deliveries] == [d.energy_wh for d in a.deliveries]
    from sim.data_arrival import generate_arrivals
    from sim.scenario import LINK_DATA_RATE_BPS

    size = {it.id: it.size_bytes for _, it in generate_arrivals(["TTC", "SSTV", "CODEC2_M17"], 172_800.0, 42)}
    idle_only_wh = sum(
        DRAW_W_IDLE * size[d.item_id] * 8 / LINK_DATA_RATE_BPS / 3600.0
        for d in b.deliveries if d.delivered
    )
    assert sum(d.energy_wh for d in b.deliveries if d.delivered) > 10 * idle_only_wh
    assert min(soc_b) < 95.0
