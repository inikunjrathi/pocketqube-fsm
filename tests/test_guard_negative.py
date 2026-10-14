from __future__ import annotations

from pathlib import Path

import pytest

from engine.config_loader import load_config
from engine.fsm import step

REPO_ROOT = Path(__file__).resolve().parents[1]
CFG = {c: load_config(REPO_ROOT / "config" / f"{c}.yaml") for c in ("config-a", "config-b", "config-c")}

_TIMER_RF = ("RF_INHIBIT_TIMER_EXPIRED", "timer:rf_inhibit_timer", "rf_inhibit_silence_timer_s", 0, -1)
_DEBOUNCE = ("SWITCH_DEBOUNCE_ELAPSED", "timer:switch_debounce_timer", "deploy_confirm_debounce_s", 0, -1)
_COMMON = [
    ("PASS_END", "elevation", "link_quality_min_elevation_deg", -1, 0),
    ("FAULT_DETECTED", "fault_count", "fault_count_threshold_for_latched_fault", 0, -1),
    ("POWER_LOW", "battery_soc", "battery_soc_safe_mode_entry_threshold_pct", 0, 1),
    ("COMMS_LOSS_TIMEOUT", "timer:ground_contact_timer", "comms_loss_reset_timer_s", 0, -1),
]
BOUNDARIES = {
    "config-a": [_TIMER_RF, *_COMMON],
    "config-b": [_DEBOUNCE, *_COMMON],
    "config-c": [_DEBOUNCE, *_COMMON,
                 ("AUTONOMOUS_RECOVERY_CONDITIONS_MET", "battery_soc",
                  "battery_soc_safe_mode_recovery_threshold_pct", 0, -1)],
}

def _cases():
    for config_id, rows in BOUNDARIES.items():
        cfg = CFG[config_id]
        for event_name, operand, param_name, fire, nofire in rows:
            event = next(e.id for e in cfg.events.values() if e.name == event_name)
            origins = sorted({s for s in cfg.states if cfg.transitions_for(s, event)})
            for origin in origins:
                yield pytest.param(
                    config_id, event, origin, operand, param_name, fire, nofire,
                    id=f"{config_id}:{event_name}:{origin}",
                )

def _env(cfg, operand, param_name, offset):
    threshold = next(p.value for p in cfg.parameters.values() if p.name == param_name)
    value = threshold + offset
    if operand.startswith("timer:"):
        return {operand[6:]: 0}, {}, value
    return {}, {operand: value}, 0

@pytest.mark.parametrize("config_id,event,origin,operand,param_name,fire,nofire", list(_cases()))
def test_guard_threshold_inclusive_side_fires_and_other_side_blocks(
    config_id, event, origin, operand, param_name, fire, nofire
):
    cfg = CFG[config_id]
    ctx, tel, now = _env(cfg, operand, param_name, fire)
    assert step(cfg, origin, event, ctx, telemetry=tel, now=now).legal is True

    ctx, tel, now = _env(cfg, operand, param_name, nofire)
    blocked = step(cfg, origin, event, ctx, telemetry=tel, now=now)
    assert blocked.legal is False
    assert blocked.new_state == origin
    assert blocked.context == ctx

@pytest.mark.parametrize("config_id", sorted(CFG))
def test_unarmed_timer_never_satisfies_an_elapsed_guard(config_id):
    cfg = CFG[config_id]
    for t in cfg.transitions:
        if t.guard and t.guard.startswith("elapsed("):
            for origin in t.from_states:
                assert step(cfg, origin, t.event, {}, now=10**9).legal is False, (t.id, origin)

@pytest.mark.parametrize("config_id", sorted(CFG))
def test_every_guarded_row_is_covered_by_a_negative_case(config_id):
    cfg = CFG[config_id]
    covered = {name for name, *_ in BOUNDARIES[config_id]}
    if config_id == "config-a":
        covered |= {"DEPLOY_CONFIRM_PATH_A", "DEPLOY_CONFIRM_PATH_B",
                    "GROUND_OVERRIDE_EXIT_SAFE", "AUTONOMOUS_RECOVERY_CONDITIONS_MET"}
    guarded = {cfg.events[t.event].name for t in cfg.transitions if t.guard}
    assert guarded <= covered

# R-03
@pytest.mark.parametrize("first,second", [("DEPLOY_CONFIRM_PATH_A", "DEPLOY_CONFIRM_PATH_B"),
                                          ("DEPLOY_CONFIRM_PATH_B", "DEPLOY_CONFIRM_PATH_A")])
def test_config_a_single_confirmation_path_never_sets_the_latch(first, second):
    cfg = CFG["config-a"]
    by_name = {e.name: e.id for e in cfg.events.values()}
    pending = next(s.id for s in cfg.states.values() if s.name == "DEPLOY_CONFIRM_PENDING")
    r1 = step(cfg, pending, by_name[first], {})
    assert r1.new_state == pending
    assert r1.context.get("deployment_confirmed", False) is False
    r1b = step(cfg, pending, by_name[first], r1.context)
    assert r1b.new_state == pending
    assert r1b.context.get("deployment_confirmed", False) is False
    r2 = step(cfg, pending, by_name[second], r1b.context)
    assert cfg.states[r2.new_state].name == "DEPLOYED_CONFIRMED"
    assert r2.context["deployment_confirmed"] is True

# R-05
@pytest.mark.parametrize("exit_event", ["AUTONOMOUS_RECOVERY_CONDITIONS_MET", "GROUND_OVERRIDE_EXIT_SAFE"])
@pytest.mark.parametrize("latch,expected", [(True, "COMMISSIONING"), (False, "DEPLOY_CONFIRM_PENDING"),
                                            (None, "DEPLOY_CONFIRM_PENDING")])
def test_config_a_safe_mode_exit_target_depends_on_the_latch(exit_event, latch, expected):
    cfg = CFG["config-a"]
    by_name = {e.name: e.id for e in cfg.events.values()}
    safe = next(s.id for s in cfg.states.values() if s.name == "SAFE_MODE")
    ctx = {} if latch is None else {"deployment_confirmed": latch}
    r = step(cfg, safe, by_name[exit_event], ctx, telemetry={"battery_soc": 100})
    assert r.legal
    assert cfg.states[r.new_state].name == expected
