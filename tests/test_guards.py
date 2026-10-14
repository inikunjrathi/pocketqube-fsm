from __future__ import annotations

import pytest

from engine.guards import GuardError, evaluate_guard, resolve_operands

def ev(guard, *, context=None, telemetry=None, params=None, now=0):
    return evaluate_guard(
        guard,
        context=context or {},
        telemetry=telemetry or {},
        params=params or {},
        now=now,
    )

def test_telemetry_vs_param_le_true():
    assert ev("battery_soc <= P-013", telemetry={"battery_soc": 20}, params={"P-013": 25}) is True

def test_telemetry_vs_param_le_false():
    assert ev("battery_soc <= P-013", telemetry={"battery_soc": 30}, params={"P-013": 25}) is False

def test_telemetry_vs_param_lt():
    assert ev("elevation < P-015", telemetry={"elevation": 5}, params={"P-015": 10}) is True
    assert ev("elevation < P-015", telemetry={"elevation": 15}, params={"P-015": 10}) is False

def test_telemetry_vs_param_ge():
    assert ev("fault_count >= P-019", telemetry={"fault_count": 3}, params={"P-019": 3}) is True
    assert ev("fault_count >= P-019", telemetry={"fault_count": 2}, params={"P-019": 3}) is False

def test_context_bool_equality_true_branch():
    assert ev("context.path_b_confirmed == true", context={"path_b_confirmed": True}) is True
    assert ev("context.path_b_confirmed == true", context={"path_b_confirmed": False}) is False

def test_context_bool_equality_false_branch():
    assert ev("context.path_b_confirmed == false", context={"path_b_confirmed": False}) is True
    assert ev("context.path_b_confirmed == false", context={"path_b_confirmed": True}) is False

def test_context_missing_key_defaults_to_false():
    assert ev("context.path_a_confirmed == true", context={}) is False
    assert ev("context.path_b_confirmed == false", context={}) is True

def test_not_equal_operator():
    assert ev("context.mode != 'idle'", context={"mode": "active"}) is True
    assert ev("context.mode != 'idle'", context={"mode": "idle"}) is False

def test_elapsed_call_true_when_enough_time_passed():
    assert ev(
        "elapsed(rf_inhibit_timer) >= P-010",
        context={"rf_inhibit_timer": 100},
        params={"P-010": 1800},
        now=2000,
    ) is True

def test_elapsed_call_false_when_not_enough_time_passed():
    assert ev(
        "elapsed(rf_inhibit_timer) >= P-010",
        context={"rf_inhibit_timer": 100},
        params={"P-010": 1800},
        now=1000,
    ) is False

def test_elapsed_call_on_unarmed_timer_is_false_not_error():
    assert ev(
        "elapsed(rf_inhibit_timer) >= P-010",
        context={},
        params={"P-010": 1800},
        now=2000,
    ) is False

def test_unknown_param_id_raises_guard_error():
    with pytest.raises(GuardError, match="P-999"):
        ev("battery_soc <= P-999", telemetry={"battery_soc": 20}, params={})

def test_multi_letter_param_prefix_resolves_like_single_letter():
    assert ev("battery_soc >= PC-012", telemetry={"battery_soc": 40}, params={"PC-012": 35}) is True

def test_two_digit_state_like_token_is_not_treated_as_param_ref():
    with pytest.raises(GuardError, match="malformed guard operand"):
        ev("context.flag == S-01", context={"flag": True}, params={})

def test_unknown_telemetry_field_raises_guard_error():
    with pytest.raises(GuardError, match="battery_soc"):
        ev("battery_soc <= P-013", telemetry={}, params={"P-013": 25})

def test_malformed_guard_raises_guard_error():
    with pytest.raises(GuardError):
        ev("this is not a guard")

def test_resolve_operands_reports_tokens_and_resolved_values():
    resolved = resolve_operands(
        "battery_soc <= P-013",
        context={},
        telemetry={"battery_soc": 20},
        params={"P-013": 25},
        now=0,
    )
    assert resolved == {
        "operator": "<=",
        "lhs": {"token": "battery_soc", "value": 20},
        "rhs": {"token": "P-013", "value": 25},
    }

def test_resolve_operands_matches_evaluate_guard_result():
    guard = "elapsed(rf_inhibit_timer) >= P-010"
    context = {"rf_inhibit_timer": 100}
    params = {"P-010": 1800}
    resolved = resolve_operands(guard, context=context, telemetry={}, params=params, now=2000)
    assert resolved["lhs"]["value"] == 1900
    assert resolved["rhs"]["value"] == 1800
    assert evaluate_guard(guard, context=context, telemetry={}, params=params, now=2000) is True
