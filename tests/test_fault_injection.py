# R-27 R-28 RB-02 RC-02

from __future__ import annotations

import re

import pytest

from engine.config_loader import Config
from engine.fsm import step
from engine.persistence import PersistenceLayer
from tests.fixtures.event_chains import ALL_CHAINS
from tests.fixtures.transition_cases import ALL_CONFIGS, legal_cases

def _reset_event_for(cfg: Config) -> str:
    return next(e.id for e in cfg.events.values() if e.name == "RESET")

_START_TIMER_RE = re.compile(r"^start_(\w+)$")

def _reset_transition_for(cfg: Config):
    reset_event = _reset_event_for(cfg)
    matches = [t for t in cfg.transitions if t.to == "reload_from_persistence" and t.event == reset_event]
    assert len(matches) == 1, f"expected exactly one RESET transition targeting reload_from_persistence in {cfg.config_id}"
    return matches[0]

def _rearmed_timer_keys(actions) -> frozenset[str]:
    return frozenset(m.group(1) for a in actions if (m := _START_TIMER_RE.match(a)))

def _legal_case_id(case) -> str:
    return f"{case.config.config_id}:{case.transition.id}:{case.origin_state}"

LEGAL_PARAMS = [
    pytest.param(case, id=_legal_case_id(case))
    for cfg in ALL_CONFIGS
    for case in legal_cases(cfg)
]

@pytest.mark.parametrize("case", LEGAL_PARAMS)
def test_reset_at_every_transition_boundary_round_trips_state_and_context(case):
    cfg, t, origin, fixture = case.config, case.transition, case.origin_state, case.fixture
    persistence = PersistenceLayer()
    result = step(
        cfg, origin, t.event, dict(fixture.context),
        telemetry=dict(fixture.telemetry), now=fixture.now,
    )
    assert result.legal is True
    persistence.save(result.new_state, result.context)

    reset_event = _reset_event_for(cfg)
    reset_now = fixture.now + 1
    reset_result = step(
        cfg, result.new_state, reset_event, {"garbage": "discarded"},
        now=reset_now, persisted=persistence.load(),
    )
    assert reset_result.legal is True
    assert reset_result.new_state == result.new_state

    rearmed = _rearmed_timer_keys(_reset_transition_for(cfg).actions)
    assert {k: v for k, v in reset_result.context.items() if k not in rearmed} == \
        {k: v for k, v in result.context.items() if k not in rearmed}
    for key in rearmed:
        assert reset_result.context[key] == reset_now

def _run_corruption_sweep(chain):
    cfg = {c.config_id: c for c in ALL_CONFIGS}[chain.config_id]
    reset_event = _reset_event_for(cfg)
    persistence = PersistenceLayer()

    state, context = cfg.initial_state, {}
    for index, (event, now) in enumerate(chain.events):
        result = step(cfg, state, event, context, now=now, persisted=persistence.load())
        assert result.legal, f"unexpected no-op on {event} from {state}"
        state, context = result.new_state, result.context
        persistence.save(state, context)

        if index < chain.latch_set_at_index:
            continue

        assert context["deployment_confirmed"] is True

        # R-29
        persistence.save(state, context)
        persistence.corrupt(persistence.last_written_bank)

        reset_result = step(cfg, state, reset_event, {}, now=now + 1, persisted=persistence.load())
        assert reset_result.legal is True
        assert reset_result.new_state == state

        rearmed = _rearmed_timer_keys(_reset_transition_for(cfg).actions)
        assert {k: v for k, v in reset_result.context.items() if k not in rearmed} == \
            {k: v for k, v in context.items() if k not in rearmed}
        for key in rearmed:
            assert reset_result.context[key] == now + 1
        assert reset_result.context["deployment_confirmed"] is True

        persistence.save(reset_result.new_state, reset_result.context)

@pytest.mark.parametrize("chain", ALL_CHAINS, ids=lambda c: c.label)
def test_latch_survives_corruption_at_every_boundary_after_it_is_set(chain):
    _run_corruption_sweep(chain)
