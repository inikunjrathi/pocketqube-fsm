# R-19

from __future__ import annotations

from pathlib import Path

import pytest

from engine.arbitration import (
    ArbitrationError,
    PendingEvent,
    arbitrate,
    describe,
    event_static_keys,
    merge_pending,
    step_many,
)
from engine.config_loader import load_config
from engine.decision_log import DecisionLogger
from test_fsm import EVENTS, STATES, make_config

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
CFG_A = load_config(CONFIG_DIR / "config-a.yaml")
CFG_B = load_config(CONFIG_DIR / "config-b.yaml")
CFG_C = load_config(CONFIG_DIR / "config-c.yaml")
TLM = {"elevation": 45.0, "battery_soc": 90.0, "fault_count": 0}

pytestmark = pytest.mark.requirement("R-19")

def order(cfg, *pairs):
    return [p.event_id for p in arbitrate(cfg, [PendingEvent(e, t) for e, t in pairs])]

def test_lower_rank_number_always_first_regardless_of_timestamp():
    assert order(CFG_A, ("E-07", 0.0), ("E-11", 99.0)) == ["E-11", "E-07"]
    assert order(CFG_A, ("E-18", 0), ("E-06", 0), ("E-03", 0), ("E-12", 0), ("E-13", 0)) == [
        "E-13", "E-12", "E-03", "E-06", "E-18"]

def test_rank1_earliest_timestamp_wins():
    assert order(CFG_A, ("E-13", 5.0), ("E-14", 3.0)) == ["E-14", "E-13"]

def test_rank1_reset_wins_timestamp_tie_against_ground_commands():
    assert order(CFG_A, ("E-13", 7.0), ("E-14", 7.0), ("E-16", 7.0)) == ["E-16", "E-13", "E-14"]
    assert order(CFG_A, ("E-16", 8.0), ("E-13", 7.0)) == ["E-13", "E-16"]
    assert order(CFG_B, ("E-10", 1.0), ("E-12", 1.0)) == ["E-12", "E-10"]

def test_rank2_timestamp_then_event_id():
    assert order(CFG_A, ("E-11", 2.0), ("E-17", 1.0)) == ["E-17", "E-11"]
    assert order(CFG_A, ("E-20", 1.0), ("E-12", 1.0), ("E-11", 1.0)) == ["E-11", "E-12", "E-20"]

def test_rank3_timestamp():
    assert order(CFG_A, ("E-03", 2.0), ("E-04", 1.0)) == ["E-04", "E-03"]
    assert order(CFG_A, ("E-04", 1.0), ("E-03", 1.0)) == ["E-03", "E-04"]

def test_rank5_timestamp():
    assert order(CFG_A, ("E-05", 9.0), ("E-18", 4.0)) == ["E-18", "E-05"]

def test_rank4_pass_end_before_any_select_even_if_raised_later():
    assert order(CFG_A, ("E-06", 0.0), ("E-10", 50.0)) == ["E-10", "E-06"]
    assert order(CFG_B, ("E-04", 0.0), ("E-05", 0.0), ("E-06", 50.0)) == ["E-06", "E-04", "E-05"]

def test_rank4_selects_follow_data_class_priority_not_timestamp():
    assert order(CFG_A, ("E-09", 0), ("E-08", 1), ("E-07", 2), ("E-06", 3)) == [
        "E-06", "E-07", "E-08", "E-09"]
    assert order(CFG_C, ("E-05", 0.0), ("E-04", 1.0)) == ["E-04", "E-05"]

def test_static_keys_cover_every_event_once():
    for cfg in (CFG_A, CFG_B, CFG_C):
        assert set(event_static_keys(cfg)) == set(cfg.events)

def test_unknown_tie_break_text_is_an_error(tmp_path):
    cfg = make_config(tmp_path, states=STATES, events=EVENTS,
                      transitions=[{"id": "T-01", "from": ["S-01"], "event": "E-01", "to": "S-02"}])
    bad = cfg.conflict_resolution[0].__class__(rank=1, category="x", member_events=("E-01",), tie_break="coin flip")
    cfg = cfg.__class__(**{**cfg.__dict__, "conflict_resolution": (bad, *cfg.conflict_resolution[1:])})
    with pytest.raises(ArbitrationError):
        arbitrate(cfg, [PendingEvent("E-01", 0)])

def test_ground_safe_mode_and_pass_end_together_log_a_ground_override():
    # R-31
    pending = [PendingEvent("E-10", 100.0), PendingEvent("E-13", 100.0)]
    tlm = {**TLM, "elevation": 2.0}
    arb = step_many(CFG_A, "S-06", pending, {}, telemetry=tlm, now=100.0)
    assert arb.serviced.event_id == "E-13"
    assert arb.result.transition_id == "T-17" and arb.result.new_state == "S-10"
    assert [p.event_id for p in arb.remaining] == ["E-10"]

    logger = DecisionLogger()
    entry = logger.record_transition(now=100.0, from_state="S-06", event="E-13", result=arb.result,
                                     rationale=describe(CFG_A, arb))
    assert "GROUND_SAFE_MODE_CMD (rank 1 ground_override_reset) via T-17" in entry.rationale
    assert entry.details["event"] == "E-13" and "log_rationale" in entry.details["actions"]

    nxt = step_many(CFG_A, "S-10", arb.remaining, arb.result.context, telemetry=tlm, now=110.0)
    assert nxt.serviced is None and [p.event_id for p in nxt.dropped] == ["E-10"]

def test_reset_beats_scheduler_event():
    arb = step_many(CFG_A, "S-06", [PendingEvent("E-07", 0.0), PendingEvent("E-16", 0.0)], {},
                    telemetry=TLM, now=0.0)
    assert arb.serviced.event_id == "E-16" and arb.result.transition_id == "T-22"

def test_higher_ranked_event_without_legal_transition_is_dropped_not_blocking():
    arb = step_many(CFG_A, "S-06", [PendingEvent("E-12", 0.0), PendingEvent("E-10", 0.0)], {},
                    telemetry={**TLM, "elevation": 2.0}, now=0.0)
    assert [p.event_id for p in arb.dropped] == ["E-12"]
    assert arb.serviced.event_id == "E-10" and arb.remaining == ()

def test_only_one_event_serviced_per_call():
    arb = step_many(CFG_A, "S-06", [PendingEvent("E-07", 0.0), PendingEvent("E-06", 0.0)], {},
                    telemetry=TLM, now=0.0)
    assert arb.serviced.event_id == "E-06" and [p.event_id for p in arb.remaining] == ["E-07"]

def test_merge_pending_keeps_earliest_copy():
    merged = merge_pending([PendingEvent("E-10", 5.0)], [PendingEvent("E-10", 9.0), PendingEvent("E-12", 9.0)])
    assert sorted((p.event_id, p.timestamp) for p in merged) == [("E-10", 5.0), ("E-12", 9.0)]

def test_driver_services_ground_override_before_autonomous_recovery():
    from engine.persistence import PersistenceLayer
    from sim.driver import _raise_tick_events, _service_pending
    from sim.event_mapping import build_event_map

    event_map = build_event_map(CFG_A)
    params = {p.name: p.value for p in CFG_A.parameters.values()}
    tlm = {"elevation": 45.0, "battery_soc": 90.0, "fault_count": 0}
    raised = _raise_tick_events(CFG_A, event_map, "S-10", tlm, 0.0, params, 10.0)
    assert sorted(p.event_id for p in raised) == ["E-14", "E-15"]
    logger = DecisionLogger()
    state, _, queued = _service_pending(
        CFG_A, event_map, raised, "S-10", {"deployment_confirmed": True}, tlm, 0.0,
        PersistenceLayer(), logger,
    )
    assert state == "S-05" and logger.entries[-1].details["transition_id"] == "T-21"
    assert [p.event_id for p in queued] == ["E-15"]
