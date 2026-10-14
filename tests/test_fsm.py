from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from engine.auth import sign_command
from engine.config_loader import load_config
from engine.fsm import FSMError, step

def make_config(tmp_path: Path, *, states, events, transitions, parameters=None, latches=None) -> "Config":
    conflict_resolution = [
        {"rank": i + 1, "category": f"cat-{e['id']}", "member_events": [e["id"]]}
        for i, e in enumerate(events)
    ]
    raw = {
        "meta": {"config_id": "fixture", "name": "Fixture", "description": "", "version": "0.0.1"},
        "states": states,
        "events": events,
        "transitions": transitions,
        "parameters": parameters or [],
        "latches": latches or [],
        "conflict_resolution": conflict_resolution,
    }
    path = tmp_path / "fixture.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return load_config(path)

STATES = [
    {"id": "S-01", "name": "A", "is_initial": True},
    {"id": "S-02", "name": "B", "is_initial": False},
]
STATES3 = STATES + [{"id": "S-03", "name": "C", "is_initial": False}]
STATES1 = [{"id": "S-01", "name": "A", "is_initial": True}]
EVENTS = [
    {"id": "E-01", "name": "GO", "source": "onboard"},
    {"id": "E-02", "name": "GENERIC", "source": "ground"},
    {"id": "E-03", "name": "ADVANCE", "source": "onboard"},
    {"id": "E-16", "name": "RESET", "source": "harness"},
]

def test_unconditional_transition_changes_state_and_applies_context_action(tmp_path):
    cfg = make_config(
        tmp_path,
        states=STATES,
        events=EVENTS,
        transitions=[
            {"id": "T-01", "from": ["S-01"], "event": "E-01", "to": "S-02",
             "actions": ["set context.flag = true"]},
        ],
    )
    result = step(cfg, "S-01", "E-01", {}, now=0)
    assert result.legal is True
    assert result.new_state == "S-02"
    assert result.context == {"flag": True}
    assert result.transition_id == "T-01"
    assert result.actions == ("set context.flag = true",)

def test_guarded_transition_uses_telemetry_and_param(tmp_path):
    cfg = make_config(
        tmp_path,
        states=STATES,
        events=EVENTS,
        transitions=[
            {"id": "T-01", "from": ["S-01"], "event": "E-01", "to": "S-02",
             "guard": "battery_soc <= P-013"},
        ],
        parameters=[{"id": "P-013", "name": "thresh", "value": 25}],
    )
    ok = step(cfg, "S-01", "E-01", {}, telemetry={"battery_soc": 20}, now=0)
    assert ok.legal is True and ok.new_state == "S-02"
    assert ok.guard_values == {"battery_soc": 20, "P-013": 25}

    blocked = step(cfg, "S-01", "E-01", {}, telemetry={"battery_soc": 30}, now=0)
    assert blocked.legal is False
    assert blocked.guard_values is None

def test_unconditional_transition_has_no_guard_values(tmp_path):
    cfg = make_config(
        tmp_path,
        states=STATES,
        events=EVENTS,
        transitions=[
            {"id": "T-01", "from": ["S-01"], "event": "E-01", "to": "S-02"},
        ],
    )
    result = step(cfg, "S-01", "E-01", {}, now=0)
    assert result.guard_values is None

def test_null_target_is_self_loop_but_still_fires_actions(tmp_path):
    cfg = make_config(
        tmp_path,
        states=STATES1,
        events=EVENTS,
        transitions=[
            {"id": "T-01", "from": "*", "event": "E-02", "to": None,
             "actions": ["log_command_received"]},
        ],
    )
    result = step(cfg, "S-01", "E-02", {"x": 1}, now=0)
    assert result.legal is True
    assert result.new_state == "S-01"
    assert result.context == {"x": 1}
    assert result.actions == ("log_command_received",)

def test_illegal_state_event_pair_is_closed_world_noop(tmp_path):
    cfg = make_config(
        tmp_path,
        states=STATES,
        events=EVENTS,
        transitions=[
            {"id": "T-01", "from": ["S-01"], "event": "E-01", "to": "S-02"},
        ],
    )
    result = step(cfg, "S-02", "E-01", {"x": 1}, now=0)
    assert result.legal is False
    assert result.new_state == "S-02"
    assert result.context == {"x": 1}
    assert result.actions == ()
    assert result.transition_id is None

def test_start_timer_action_arms_context_and_elapsed_guard_reads_it(tmp_path):
    cfg = make_config(
        tmp_path,
        states=STATES3,
        events=EVENTS,
        transitions=[
            {"id": "T-01", "from": ["S-01"], "event": "E-01", "to": "S-02",
             "actions": ["start_my_timer"]},
            {"id": "T-02", "from": ["S-02"], "event": "E-03", "to": "S-03",
             "guard": "elapsed(my_timer) >= P-010"},
        ],
        parameters=[{"id": "P-010", "name": "timer", "value": 50}],
    )
    after_start = step(cfg, "S-01", "E-01", {}, now=100)
    assert after_start.context == {"my_timer": 100}

    too_soon = step(cfg, "S-02", "E-03", after_start.context, now=120)
    assert too_soon.legal is False

    enough_time = step(cfg, "S-02", "E-03", after_start.context, now=200)
    assert enough_time.legal is True
    assert enough_time.new_state == "S-03"

def test_reload_from_persistence_restores_persisted_state_and_context(tmp_path):
    cfg = make_config(
        tmp_path,
        states=STATES,
        events=EVENTS,
        transitions=[
            {"id": "T-00", "from": ["S-01"], "event": "E-03", "to": "S-02"},
            {"id": "T-16", "from": "*", "event": "E-16", "to": "reload_from_persistence",
             "actions": ["reload_from_nvm"]},
        ],
    )
    result = step(
        cfg, "S-02", "E-16", {"garbage": 1}, now=0,
        persisted={"state": "S-01", "context": {"deployment_confirmed": True}},
    )
    assert result.new_state == "S-01"
    assert result.context == {"deployment_confirmed": True}
    assert result.actions == ("reload_from_nvm",)

def test_reload_from_persistence_action_can_restart_a_stale_timer(tmp_path):
    cfg = make_config(
        tmp_path,
        states=STATES,
        events=EVENTS,
        transitions=[
            {"id": "T-00", "from": ["S-01"], "event": "E-03", "to": "S-02"},
            {"id": "T-16", "from": "*", "event": "E-16", "to": "reload_from_persistence",
             "actions": ["reload_from_nvm", "start_my_timer"]},
        ],
    )
    result = step(
        cfg, "S-02", "E-16", {"garbage": 1}, now=500,
        persisted={"state": "S-01", "context": {"deployment_confirmed": True, "my_timer": 10}},
    )
    assert result.new_state == "S-01"
    assert result.context["deployment_confirmed"] is True
    assert result.context["my_timer"] == 500

def test_reload_from_persistence_with_no_snapshot_falls_back_to_initial_state(tmp_path):
    cfg = make_config(
        tmp_path,
        states=STATES,
        events=EVENTS,
        transitions=[
            {"id": "T-00", "from": ["S-01"], "event": "E-03", "to": "S-02"},
            {"id": "T-16", "from": "*", "event": "E-16", "to": "reload_from_persistence"},
        ],
    )
    result = step(cfg, "S-02", "E-16", {"garbage": 1}, now=0, persisted=None)
    assert result.new_state == cfg.initial_state == "S-01"
    assert result.context == {}

def test_first_matching_guard_wins_in_table_order(tmp_path):
    cfg = make_config(
        tmp_path,
        states=STATES,
        events=EVENTS,
        transitions=[
            {"id": "T-01", "from": ["S-01"], "event": "E-01",
             "guard": "context.confirmed == false", "to": "S-01"},
            {"id": "T-02", "from": ["S-01"], "event": "E-01",
             "guard": "context.confirmed == true", "to": "S-02"},
        ],
    )
    stays = step(cfg, "S-01", "E-01", {"confirmed": False}, now=0)
    assert stays.transition_id == "T-01" and stays.new_state == "S-01"

    moves = step(cfg, "S-01", "E-01", {"confirmed": True}, now=0)
    assert moves.transition_id == "T-02" and moves.new_state == "S-02"

def test_latch_set_by_transition_id_lands_in_context_even_via_opaque_action(tmp_path):
    cfg = make_config(
        tmp_path,
        states=STATES,
        events=EVENTS,
        transitions=[
            {"id": "T-01", "from": ["S-01"], "event": "E-01", "to": "S-02",
             "actions": ["set_deployment_confirmed_latch"]},
        ],
        latches=[{"name": "deployment_confirmed", "set_by": ["T-01"]}],
    )
    result = step(cfg, "S-01", "E-01", {}, now=0)
    assert result.context == {"deployment_confirmed": True}

def test_latch_cannot_be_cleared_once_set(tmp_path):
    cfg = make_config(
        tmp_path,
        states=STATES,
        events=EVENTS,
        transitions=[
            {"id": "T-01", "from": ["S-01"], "event": "E-01", "to": "S-02",
             "actions": ["set context.deployment_confirmed = false"]},
            {"id": "T-02", "from": ["S-02"], "event": "E-02", "to": "S-01"},
        ],
        latches=[{"name": "deployment_confirmed", "set_by": ["T-02"]}],
    )
    result = step(cfg, "S-01", "E-01", {"deployment_confirmed": True}, now=0)
    assert result.context == {"deployment_confirmed": True}

def test_malformed_context_mutation_action_raises_fsm_error(tmp_path):
    cfg = make_config(
        tmp_path,
        states=STATES,
        events=EVENTS,
        transitions=[
            {"id": "T-01", "from": ["S-01"], "event": "E-01", "to": "S-02",
             "actions": ["set context.flag = not_a_literal"]},
        ],
    )
    with pytest.raises(FSMError):
        step(cfg, "S-01", "E-01", {}, now=0)

SECRET = b"test-secret-key-do-not-use-in-production"
WRONG_SECRET = b"a-wrong-secret-key"

def test_ground_event_fires_unchanged_when_no_secret_configured(tmp_path):
    cfg = make_config(
        tmp_path,
        states=STATES,
        events=EVENTS,
        transitions=[
            {"id": "T-01", "from": ["S-01"], "event": "E-02", "to": "S-02"},
        ],
    )
    result = step(cfg, "S-01", "E-02", {}, now=0)
    assert result.legal is True
    assert result.new_state == "S-02"

def test_ground_event_without_signature_is_rejected_when_secret_configured(tmp_path):
    cfg = make_config(
        tmp_path,
        states=STATES,
        events=EVENTS,
        transitions=[
            {"id": "T-01", "from": ["S-01"], "event": "E-02", "to": "S-02"},
        ],
    )
    result = step(cfg, "S-01", "E-02", {}, now=0, ground_auth_secret=SECRET)
    assert result.legal is False
    assert result.new_state == "S-01"

def test_ground_event_with_wrong_signature_is_rejected(tmp_path):
    cfg = make_config(
        tmp_path,
        states=STATES,
        events=EVENTS,
        transitions=[
            {"id": "T-01", "from": ["S-01"], "event": "E-02", "to": "S-02"},
        ],
    )
    forged = sign_command("E-02", 0, WRONG_SECRET)
    result = step(
        cfg, "S-01", "E-02", {}, now=0,
        ground_auth_secret=SECRET, command_signature=forged,
    )
    assert result.legal is False
    assert result.new_state == "S-01"

def test_ground_event_with_valid_signature_fires(tmp_path):
    cfg = make_config(
        tmp_path,
        states=STATES,
        events=EVENTS,
        transitions=[
            {"id": "T-01", "from": ["S-01"], "event": "E-02", "to": "S-02"},
        ],
    )
    valid_sig = sign_command("E-02", 0, SECRET)
    result = step(
        cfg, "S-01", "E-02", {}, now=0,
        ground_auth_secret=SECRET, command_signature=valid_sig,
    )
    assert result.legal is True
    assert result.new_state == "S-02"

def test_onboard_event_unaffected_by_auth_enforcement(tmp_path):
    cfg = make_config(
        tmp_path,
        states=STATES,
        events=EVENTS,
        transitions=[
            {"id": "T-01", "from": ["S-01"], "event": "E-01", "to": "S-02"},
        ],
    )
    result = step(cfg, "S-01", "E-01", {}, now=0, ground_auth_secret=SECRET)
    assert result.legal is True
    assert result.new_state == "S-02"
