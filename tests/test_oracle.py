from __future__ import annotations

from datetime import timedelta

import pytest

from engine.config_loader import load_config
from engine.persistence import PersistenceLayer
from engine.scheduler import Item
from policy.base import DecisionContext
from policy.oracle import OraclePolicy, _rollout
from sim.driver import _epoch_datetime, _run_bootstrap
from sim.event_mapping import build_event_map
from sim.orbit import load_satellite
from sim.power import BatteryState
from sim.scenario import DRAW_W_COMMS_TTC, LINK_DATA_RATE_BPS
from engine.decision_log import DecisionLogger

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_A = REPO_ROOT / "config" / "config-a.yaml"

_ROLLOUT_NOW_IN_FIRST_PASS_S = 30000.0

def _bootstrapped_context() -> DecisionContext:
    cfg = load_config(CONFIG_A)
    sat = load_satellite()
    start_time = _epoch_datetime(sat)
    persistence = PersistenceLayer()
    logger = DecisionLogger()
    state, fsm_context = _run_bootstrap(cfg, persistence, logger)
    event_map = build_event_map(cfg)
    battery = BatteryState(soc_pct=80.0)
    now = _ROLLOUT_NOW_IN_FIRST_PASS_S
    selected_item = Item(id="ttc-1", data_class="TTC", deadline=now + 200.0)
    return DecisionContext(
        cfg=cfg, sat=sat, start_time=start_time, state=state, fsm_context=fsm_context,
        battery=battery, remaining_items=[], selected_item=selected_item,
        arrivals=[], arrival_idx=0, event_map=event_map,
        min_elevation_deg=10.0, fade_margin_db=3.0, now=now, dt_s=30.0,
    )

def test_decide_returns_serve_or_hold():
    context = _bootstrapped_context()
    decision = OraclePolicy().decide(features=None, context=context)
    assert decision in ("serve", "hold")

def test_decide_picks_the_lower_scoring_action():
    context = _bootstrapped_context()
    serve_outcome = _rollout(context, action="serve")
    hold_outcome = _rollout(context, action="hold")
    decision = OraclePolicy().decide(features=None, context=context)
    chosen_score = serve_outcome.score() if decision == "serve" else hold_outcome.score()
    other_score = hold_outcome.score() if decision == "serve" else serve_outcome.score()
    assert chosen_score <= other_score

def test_rollout_counts_ttc_deadline_miss_when_item_is_never_served():
    context = _bootstrapped_context()
    stuck_item = Item(id="ttc-stuck", data_class="TTC", deadline=1.0)
    context_with_deadline = DecisionContext(
        **{**context.__dict__, "selected_item": stuck_item, "now": 30500.0}
    )
    hold_outcome = _rollout(context_with_deadline, action="hold")
    assert hold_outcome.ttc_deadline_misses >= 1

def test_rollout_serves_multiple_small_items_in_one_tick():
    base_context = _bootstrapped_context()
    queued_items = [
        Item(id=f"q-{i}", data_class="TTC", size_bytes=256, deadline=base_context.now + 800.0)
        for i in range(5)
    ]
    context = DecisionContext(
        **{**base_context.__dict__, "remaining_items": queued_items}
    )
    outcome = _rollout(context, action="hold")
    assert outcome.latency_s == pytest.approx(180.0)

def test_rollout_energy_scales_with_item_transmit_time_not_whole_tick():
    base_context = _bootstrapped_context()
    queued_items = [
        Item(id=f"q-{i}", data_class="TTC", size_bytes=256, deadline=base_context.now + 800.0)
        for i in range(5)
    ]
    context = DecisionContext(
        **{**base_context.__dict__, "remaining_items": queued_items}
    )
    outcome = _rollout(context, action="hold")

    item_transmit_time_s = 256 * 8 / LINK_DATA_RATE_BPS
    expected_energy_wh = 5 * (DRAW_W_COMMS_TTC * item_transmit_time_s / 3600.0)
    assert outcome.energy_wh == pytest.approx(expected_energy_wh)

    tick_budget_wh = DRAW_W_COMMS_TTC * context.dt_s / 3600.0
    assert outcome.energy_wh < tick_budget_wh / 10.0

def test_rollout_oversized_item_requeues_without_skipping_ahead():
    base_context = _bootstrapped_context()
    now = base_context.now
    item1 = Item(id="big-1", data_class="TTC", size_bytes=32400, deadline=now + 100.0)
    item2 = Item(id="big-2", data_class="TTC", size_bytes=4800, deadline=now + 200.0)
    acted_item = Item(id="acted", data_class="TTC", size_bytes=256, deadline=now + 1000.0)
    context = DecisionContext(
        **{
            **base_context.__dict__,
            "selected_item": acted_item,
            "remaining_items": [item1, item2],
        }
    )
    outcome = _rollout(context, action="hold")

    assert outcome.latency_s == pytest.approx(150.0)
    assert outcome.ttc_deadline_misses == 0
