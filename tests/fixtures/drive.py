# R-29

from __future__ import annotations

from engine.fsm import step

def _drive(cfg, events, persistence):
    # R-29
    state, context = cfg.initial_state, {}
    now = 0
    for event, now in events:
        result = step(cfg, state, event, context, now=now, persisted=persistence.load())
        assert result.legal, f"unexpected no-op on {event} from {state}"
        state, context = result.new_state, result.context
        persistence.save(state, context)
    return state, context
