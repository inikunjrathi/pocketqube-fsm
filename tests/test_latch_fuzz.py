from __future__ import annotations

import random

import pytest

from engine.fsm import step
from engine.persistence import PersistenceLayer
from tests.fixtures.transition_cases import ALL_CONFIGS, FixtureMissingError, fixture_for

SEEDS = tuple(range(20))
WALK_LENGTH = 60

ELAPSED_TIMER_KEYS: dict[tuple[str, str], str] = {
    ("config-a", "T-02"): "rf_inhibit_timer",
    ("config-a", "T-24"): "ground_contact_timer",
    ("config-b", "T-02"): "switch_debounce_timer",
    ("config-b", "T-15"): "ground_contact_timer",
    ("config-c", "T-02"): "switch_debounce_timer",
    ("config-c", "T-15"): "ground_contact_timer",
}

def _available_transitions(cfg, state_id):
    seen_ids: set[str] = set()
    available = []
    for event_id in cfg.events:
        for t in cfg.transitions_for(state_id, event_id):
            if t.id in seen_ids:
                continue
            seen_ids.add(t.id)
            try:
                fixture = fixture_for(cfg, t)
            except FixtureMissingError:
                continue
            available.append((t, fixture))
    return available

def _apply_fixture(cfg, t, now, context, fixture):
    new_context = dict(context)
    new_context.update(fixture.context)
    timer_key = ELAPSED_TIMER_KEYS.get((cfg.config_id, t.id))
    if timer_key is None:
        return now + 1, new_context
    new_context[timer_key] = now
    return now + fixture.now, new_context

def _run_walk(cfg, seed):
    rng = random.Random(seed)
    persistence = PersistenceLayer()
    state, context, now = cfg.initial_state, {}, 0
    latch_ever_true = False
    reset_event = next(e.id for e in cfg.events.values() if e.name == "RESET")

    def _check_latch(where):
        nonlocal latch_ever_true
        if context.get("deployment_confirmed") is True:
            latch_ever_true = True
        elif latch_ever_true:
            pytest.fail(f"seed {seed}: deployment_confirmed reverted to falsy {where}")

    for _ in range(WALK_LENGTH):
        choices = _available_transitions(cfg, state)
        if not choices:
            break
        t, fixture = rng.choice(choices)
        now, merged_context = _apply_fixture(cfg, t, now, context, fixture)

        result = step(
            cfg, state, t.event, merged_context, telemetry=dict(fixture.telemetry),
            now=now, persisted=persistence.load(),
        )
        assert result.legal, f"seed {seed}: expected {t.id} to be legal from {state}"
        state, context = result.new_state, result.context
        persistence.save(state, context)
        _check_latch(f"after {t.id} from {state}")

        if rng.random() < 0.2:
            if rng.random() < 0.5:
                persistence.save(state, context)
                persistence.corrupt(persistence.last_written_bank)
            reset_result = step(cfg, state, reset_event, {}, now=now + 1, persisted=persistence.load())
            assert reset_result.legal
            state, context = reset_result.new_state, reset_result.context
            now += 1
            persistence.save(state, context)
            _check_latch("after a random RESET injection")

@pytest.mark.parametrize("cfg", ALL_CONFIGS, ids=lambda c: c.config_id)
@pytest.mark.parametrize("seed", SEEDS)
def test_latch_never_reverts_across_a_random_walk_with_resets(cfg, seed):
    _run_walk(cfg, seed)
