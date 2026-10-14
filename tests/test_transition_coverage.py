from __future__ import annotations

import pytest

from engine.fsm import step
from tests.fixtures.transition_cases import (
    ALL_CONFIGS,
    fixture_for,
    illegal_pairs,
    legal_cases,
)

def _legal_case_id(case) -> str:
    return f"{case.config.config_id}:{case.transition.id}:{case.origin_state}"

def _legal_case_param(case):
    return pytest.param(
        case,
        id=_legal_case_id(case),
        marks=pytest.mark.requirement(*case.transition.requirements),
    )

LEGAL_PARAMS = [
    _legal_case_param(case) for cfg in ALL_CONFIGS for case in legal_cases(cfg)
]

def _illegal_pair_id(pair) -> str:
    cfg, state_id, event_id = pair
    return f"{cfg.config_id}:{state_id}:{event_id}"

ILLEGAL_PARAMS = [
    pytest.param(pair, id=_illegal_pair_id(pair))
    for cfg in ALL_CONFIGS
    for pair in illegal_pairs(cfg)
]

@pytest.mark.parametrize("case", LEGAL_PARAMS)
def test_every_transition_row_fires_legally_from_every_origin(case):
    cfg, t, origin, fixture = case.config, case.transition, case.origin_state, case.fixture
    result = step(
        cfg, origin, t.event, dict(fixture.context),
        telemetry=dict(fixture.telemetry), now=fixture.now,
    )
    assert result.legal is True
    assert result.transition_id == t.id

    if t.to == "reload_from_persistence":
        assert result.new_state == cfg.initial_state
        assert result.actions == t.actions
    else:
        expected_state = origin if t.to is None else t.to
        assert result.new_state == expected_state
        assert result.actions == t.actions

@pytest.mark.parametrize("pair", ILLEGAL_PARAMS)
def test_every_illegal_state_event_pair_is_a_noop(pair):
    cfg, state_id, event_id = pair
    context = {"sentinel": "unchanged"}
    result = step(cfg, state_id, event_id, context, now=0)
    assert result.legal is False
    assert result.new_state == state_id
    assert result.context == context
    assert result.actions == ()
    assert result.transition_id is None

@pytest.mark.parametrize("cfg", ALL_CONFIGS, ids=lambda c: c.config_id)
def test_legal_and_illegal_pairs_exactly_partition_all_state_event_combinations(cfg):
    all_pairs = {(s, e) for s in cfg.states for e in cfg.events}
    illegal = {(state_id, event_id) for _, state_id, event_id in illegal_pairs(cfg)}
    legal = {(case.origin_state, case.transition.event) for case in legal_cases(cfg)}
    assert illegal.isdisjoint(legal)
    assert illegal | legal == all_pairs

@pytest.mark.parametrize("cfg", ALL_CONFIGS, ids=lambda c: c.config_id)
def test_every_real_transition_has_a_fixture_entry(cfg):
    for t in cfg.transitions:
        fixture_for(cfg, t)
