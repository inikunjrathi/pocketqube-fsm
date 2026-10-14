# R-13 R-30 R-31 R-32

from __future__ import annotations

import pytest

from engine.decision_log import DecisionLogger
from engine.fsm import StepResult

@pytest.mark.requirement("R-30")
def test_illegal_transition_logs_default_noop_rationale():
    logger = DecisionLogger()
    result = StepResult(new_state="S-02", context={}, actions=(), transition_id=None, legal=False)
    entry = logger.record_transition(now=10, from_state="S-02", event="E-01", result=result)
    assert entry.kind == "transition"
    assert entry.details["legal"] is False
    assert "no-op" in entry.rationale
    assert "S-02" in entry.rationale and "E-01" in entry.rationale

def test_legal_transition_logs_default_rationale_with_from_event_to():
    logger = DecisionLogger()
    result = StepResult(
        new_state="S-07", context={}, actions=("switch_sstv_downlink",),
        transition_id="T-10", legal=True,
    )
    entry = logger.record_transition(now=5, from_state="S-06", event="E-07", result=result)
    assert entry.rationale == (
        "S-06 --E-07--> S-07 via T-10 (actions: switch_sstv_downlink)"
    )
    assert entry.details["transition_id"] == "T-10"

def test_explicit_rationale_overrides_default_for_safe_mode_style_logging():
    logger = DecisionLogger()
    result = StepResult(
        new_state="S-10", context={}, actions=("suspend_non_ttc_downlink", "log_rationale"),
        transition_id="T-15", legal=True,
    )
    entry = logger.record_transition(
        now=100, from_state="S-06", event="E-12", result=result,
        guard_values={"battery_soc": 20, "P-013": 25},
        rationale="safe-mode entry: battery_soc 20 <= threshold 25",
    )
    assert entry.rationale == "safe-mode entry: battery_soc 20 <= threshold 25"
    assert entry.details["guard_values"] == {"battery_soc": 20, "P-013": 25}

def test_guard_values_auto_populate_from_step_result_when_not_overridden():
    logger = DecisionLogger()
    result = StepResult(
        new_state="S-10", context={}, actions=("suspend_non_ttc_downlink",),
        transition_id="T-15", legal=True,
        guard_values={"battery_soc": 20, "P-013": 25},
    )
    entry = logger.record_transition(now=100, from_state="S-06", event="E-12", result=result)
    assert entry.details["guard_values"] == {"battery_soc": 20, "P-013": 25}

def test_explicit_guard_values_override_step_result_guard_values():
    logger = DecisionLogger()
    result = StepResult(
        new_state="S-10", context={}, actions=(), transition_id="T-15", legal=True,
        guard_values={"battery_soc": 20, "P-013": 25},
    )
    entry = logger.record_transition(
        now=100, from_state="S-06", event="E-12", result=result,
        guard_values={"overridden": True},
    )
    assert entry.details["guard_values"] == {"overridden": True}

def test_entries_accumulate_in_order():
    logger = DecisionLogger()
    ok = StepResult(new_state="S-02", context={}, actions=(), transition_id="T-01", legal=True)
    noop = StepResult(new_state="S-02", context={}, actions=(), transition_id=None, legal=False)
    logger.record_transition(now=1, from_state="S-01", event="E-01", result=ok)
    logger.record_transition(now=2, from_state="S-02", event="E-99", result=noop)
    assert [e.details.get("event") for e in logger.entries] == ["E-01", "E-99"]

def test_entries_is_immutable_snapshot():
    logger = DecisionLogger()
    ok = StepResult(new_state="S-02", context={}, actions=(), transition_id="T-01", legal=True)
    logger.record_transition(now=1, from_state="S-01", event="E-01", result=ok)
    entries = logger.entries
    assert isinstance(entries, tuple)

@pytest.mark.requirement("R-32")
def test_scheduler_decision_logs_rule_and_candidates():
    logger = DecisionLogger()
    entry = logger.record_scheduler_decision(
        now=50, selected="TTC", candidates=["TTC", "SSTV"], rule="data_class_priority",
    )
    assert entry.kind == "scheduler"
    assert entry.details["selected"] == "TTC"
    assert entry.details["candidates"] == ["TTC", "SSTV"]
    assert "TTC" in entry.rationale
