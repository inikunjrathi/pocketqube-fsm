from __future__ import annotations

import ast
from pathlib import Path

import pytest

from engine.config_loader import load_config
from engine.decision_log import DecisionLogger
from engine.persistence import PersistenceLayer
from engine.scheduler import Item
from sim.driver import DeliveryRecord, SimulationResult, run_simulation
from sim.event_mapping import build_event_map
from sim.scenario import (
    COMMS_BURST_DURATION_S,
    DRAW_W_COMMS_SSTV,
    DRAW_W_COMMS_TTC,
    DRAW_W_IDLE,
    GROUND_STATIONS_DUAL,
    LINK_DATA_RATE_BPS,
    ORBITAL_PERIOD_S,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_A = REPO_ROOT / "config" / "config-a.yaml"
CONFIG_B = REPO_ROOT / "config" / "config-b.yaml"
CONFIG_C = REPO_ROOT / "config" / "config-c.yaml"

SHORT_DURATION_S = 6 * ORBITAL_PERIOD_S
DELIVERY_DURATION_S = 76000.0
SEED = 12345

FIRST_PASS_ANCHOR_S = 30120.0

def test_bootstrap_reaches_operational_state_config_a():
    cfg = load_config(CONFIG_A)
    result = run_simulation(cfg, duration_s=SHORT_DURATION_S, dt_s=60.0, seed=SEED)
    assert result.final_context.get("deployment_confirmed") is True

def test_bootstrap_reaches_operational_state_config_b():
    cfg = load_config(CONFIG_B)
    result = run_simulation(cfg, duration_s=SHORT_DURATION_S, dt_s=60.0, seed=SEED)
    assert result.final_context.get("deployment_confirmed") is True

def test_bootstrap_reaches_operational_state_config_c():
    cfg = load_config(CONFIG_C)
    result = run_simulation(cfg, duration_s=SHORT_DURATION_S, dt_s=60.0, seed=SEED)
    assert result.final_context.get("deployment_confirmed") is True

def test_decision_log_is_nonempty():
    cfg = load_config(CONFIG_A)
    result = run_simulation(cfg, duration_s=DELIVERY_DURATION_S, dt_s=30.0, seed=SEED)
    assert result.decision_log, "decision log should record bootstrap + comms decisions"

def test_deliveries_recorded():
    cfg = load_config(CONFIG_A)
    result = run_simulation(cfg, duration_s=DELIVERY_DURATION_S, dt_s=30.0, seed=SEED)
    assert result.deliveries, "expected DeliveryRecords for admitted arrivals"
    assert all(isinstance(d, DeliveryRecord) for d in result.deliveries)
    assert any(d.delivered for d in result.deliveries), "expected some delivered items"
    for d in result.deliveries:
        if d.delivered:
            assert d.delivery_time_s is not None
            assert d.latency_s is not None
            assert d.energy_wh is not None

def test_deterministic_given_seed():
    cfg = load_config(CONFIG_A)
    r1 = run_simulation(cfg, duration_s=SHORT_DURATION_S, dt_s=60.0, seed=SEED)
    r2 = run_simulation(cfg, duration_s=SHORT_DURATION_S, dt_s=60.0, seed=SEED)
    assert r1.config_id == r2.config_id
    assert len(r1.deliveries) == len(r2.deliveries)
    assert r1.deliveries == r2.deliveries
    assert r1.final_context == r2.final_context

def test_try_fire_applies_legal_transition_and_logs():
    from sim.driver import _try_fire, _PASS_END_EVENT_NAME

    cfg = load_config(CONFIG_A)
    event_map = build_event_map(cfg)
    persistence = PersistenceLayer()
    logger = DecisionLogger()
    telemetry = {"elevation": 5.0, "battery_soc": 100.0, "fault_count": 0}

    new_state, new_context, fired = _try_fire(
        cfg, event_map, _PASS_END_EVENT_NAME, "S-06", {}, telemetry, 0.0,
        persistence, logger,
    )
    assert fired is True
    assert new_state == "S-09"
    assert len(logger.entries) == 1

def test_try_fire_returns_unfired_when_guard_false():
    from sim.driver import _try_fire, _PASS_END_EVENT_NAME

    cfg = load_config(CONFIG_A)
    event_map = build_event_map(cfg)
    persistence = PersistenceLayer()
    logger = DecisionLogger()
    telemetry = {"elevation": 45.0, "battery_soc": 100.0, "fault_count": 0}

    new_state, new_context, fired = _try_fire(
        cfg, event_map, _PASS_END_EVENT_NAME, "S-06", {}, telemetry, 0.0,
        persistence, logger,
    )
    assert fired is False
    assert new_state == "S-06"
    assert logger.entries == ()

def test_maybe_recover_autonomous_config_a():
    from sim.driver import _maybe_recover_from_safe_mode

    cfg = load_config(CONFIG_A)
    event_map = build_event_map(cfg)
    persistence = PersistenceLayer()
    logger = DecisionLogger()
    params_by_name = {p.name: p.value for p in cfg.parameters.values()}
    telemetry = {"elevation": 5.0, "battery_soc": 45.0, "fault_count": 0}

    new_state, new_context, recovered = _maybe_recover_from_safe_mode(
        cfg, event_map, "S-10", {"deployment_confirmed": True}, telemetry, 0.0, persistence, logger,
        params_by_name, min_elevation_deg=10.0,
    )
    assert recovered is True
    assert new_state == "S-05"

def test_maybe_recover_autonomous_config_c():
    from sim.driver import _maybe_recover_from_safe_mode

    cfg = load_config(CONFIG_C)
    event_map = build_event_map(cfg)
    persistence = PersistenceLayer()
    logger = DecisionLogger()
    params_by_name = {p.name: p.value for p in cfg.parameters.values()}
    telemetry = {"elevation": 5.0, "battery_soc": 40.0, "fault_count": 0}

    new_state, new_context, recovered = _maybe_recover_from_safe_mode(
        cfg, event_map, "S-07", {}, telemetry, 0.0, persistence, logger,
        params_by_name, min_elevation_deg=10.0,
    )
    assert recovered is True
    assert new_state == "S-04"

def test_maybe_recover_ground_override_config_b_at_aos():
    from sim.driver import _maybe_recover_from_safe_mode

    cfg = load_config(CONFIG_B)
    event_map = build_event_map(cfg)
    persistence = PersistenceLayer()
    logger = DecisionLogger()
    params_by_name = {p.name: p.value for p in cfg.parameters.values()}
    telemetry = {"elevation": 15.0, "battery_soc": 10.0, "fault_count": 0}

    new_state, new_context, recovered = _maybe_recover_from_safe_mode(
        cfg, event_map, "S-07", {}, telemetry, 0.0, persistence, logger,
        params_by_name, min_elevation_deg=10.0,
    )
    assert recovered is True
    assert new_state == "S-04"

def test_maybe_recover_ground_override_still_recovers_with_correct_secret():
    from sim.driver import _maybe_recover_from_safe_mode

    cfg = load_config(CONFIG_B)
    event_map = build_event_map(cfg)
    persistence = PersistenceLayer()
    logger = DecisionLogger()
    params_by_name = {p.name: p.value for p in cfg.parameters.values()}
    telemetry = {"elevation": 15.0, "battery_soc": 10.0, "fault_count": 0}

    new_state, new_context, recovered = _maybe_recover_from_safe_mode(
        cfg, event_map, "S-07", {}, telemetry, 0.0, persistence, logger,
        params_by_name, min_elevation_deg=10.0,
        ground_auth_secret=b"the-real-ground-station-key",
    )
    assert recovered is True
    assert new_state == "S-04"

def test_maybe_recover_config_b_stays_safe_below_min_elevation():
    from sim.driver import _maybe_recover_from_safe_mode

    cfg = load_config(CONFIG_B)
    event_map = build_event_map(cfg)
    persistence = PersistenceLayer()
    logger = DecisionLogger()
    params_by_name = {p.name: p.value for p in cfg.parameters.values()}
    telemetry = {"elevation": 2.0, "battery_soc": 10.0, "fault_count": 0}

    new_state, new_context, recovered = _maybe_recover_from_safe_mode(
        cfg, event_map, "S-07", {}, telemetry, 0.0, persistence, logger,
        params_by_name, min_elevation_deg=10.0,
    )
    assert recovered is False
    assert new_state == "S-07"

def test_find_bootstrap_path_from_arbitrary_start_config_a():
    from sim.driver import _find_bootstrap_path

    cfg = load_config(CONFIG_A)
    path = _find_bootstrap_path(cfg, start_state="S-05")
    assert path == [("E-05", 0.0)]

def test_find_bootstrap_path_default_start_unchanged():
    from sim.driver import _find_bootstrap_path

    cfg = load_config(CONFIG_A)
    assert _find_bootstrap_path(cfg) == _find_bootstrap_path(cfg, start_state=cfg.initial_state)

def test_reenter_comms_mode_config_b():
    from sim.driver import _reenter_comms_mode

    cfg = load_config(CONFIG_B)
    persistence = PersistenceLayer()
    logger = DecisionLogger()
    state, context = _reenter_comms_mode(cfg, "S-04", {}, persistence, logger, 0.0)
    assert state == "S-05"

def test_no_config_id_branching():
    import sim.driver as driver_module

    source = Path(driver_module.__file__).read_text()
    tree = ast.parse(source)

    def references_config_id(node: ast.expr) -> bool:
        return (isinstance(node, ast.Attribute) and node.attr == "config_id") or (
            isinstance(node, ast.Name) and node.id == "config_id"
        )

    offending: list[ast.Compare] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            sides = [node.left, *node.comparators]
            if any(references_config_id(side) for side in sides):
                offending.append(node)

    assert not offending, (
        "sim/driver.py contains config_id branching -- Config B's collapsed "
        "scheduler-select events must be handled via sim.event_mapping's "
        "config-agnostic resolution, never a cfg.config_id check (see Global "
        "Constraints)"
    )

def test_baseline_policy_never_holds_matches_pre_phase5_delivery_count():
    cfg = load_config(CONFIG_A)
    result = run_simulation(cfg, duration_s=DELIVERY_DURATION_S, dt_s=30.0, seed=SEED)
    delivered_count = len([d for d in result.deliveries if d.delivered])
    assert delivered_count == 591

def _run_with_fixed_arrivals(monkeypatch, cfg, arrivals, *, duration_s, dt_s, seed=SEED):
    import sim.driver as driver_module

    monkeypatch.setattr(driver_module, "generate_arrivals", lambda *a, **k: list(arrivals))
    return driver_module.run_simulation(cfg, duration_s=duration_s, dt_s=dt_s, seed=seed)

def test_multiple_items_delivered_in_one_tick(monkeypatch):
    cfg = load_config(CONFIG_A)
    arrivals = [
        (
            FIRST_PASS_ANCHOR_S,
            Item(id=f"ARR-{i:06d}", data_class="TTC", size_bytes=256, deadline=FIRST_PASS_ANCHOR_S + 300.0),
        )
        for i in range(5)
    ]
    result = _run_with_fixed_arrivals(
        monkeypatch, cfg, arrivals, duration_s=FIRST_PASS_ANCHOR_S, dt_s=60.0,
    )
    delivered = [d for d in result.deliveries if d.delivered]
    assert len(delivered) == 5
    same_tick = [d for d in delivered if d.delivery_time_s == FIRST_PASS_ANCHOR_S]
    assert len(same_tick) > 1, (
        "expected more than one DeliveryRecord to share the arrival tick's "
        "delivery_time_s -- multiple items served within a single tick"
    )

def test_oversized_item_defers_to_later_tick(monkeypatch):
    cfg = load_config(CONFIG_A)
    t_arrival = FIRST_PASS_ANCHOR_S + 20.0
    item1 = Item(id="ARR-000000", data_class="TTC", size_bytes=1080, deadline=t_arrival + 100.0)
    item2 = Item(id="ARR-000001", data_class="TTC", size_bytes=360, deadline=t_arrival + 200.0)
    arrivals = [(t_arrival, item1), (t_arrival, item2)]
    result = _run_with_fixed_arrivals(
        monkeypatch, cfg, arrivals, duration_s=t_arrival + 1.0, dt_s=1.0,
    )
    by_id = {d.item_id: d for d in result.deliveries}

    assert by_id["ARR-000000"].delivered is True
    assert by_id["ARR-000000"].delivery_time_s == t_arrival

    assert by_id["ARR-000001"].delivered is True
    assert by_id["ARR-000001"].delivery_time_s == t_arrival + 1.0
    assert by_id["ARR-000001"].delivery_time_s > by_id["ARR-000000"].delivery_time_s

class _HoldOnceThenServePolicy:

    def __init__(self) -> None:
        self.calls = 0

    def decide(self, features, context):
        self.calls += 1
        return "hold" if self.calls == 1 else "serve"

def test_hold_breaks_tick_without_serving_item_behind_it(monkeypatch):
    cfg = load_config(CONFIG_A)
    item1 = Item(id="ARR-000000", data_class="TTC", size_bytes=256, deadline=FIRST_PASS_ANCHOR_S + 300.0)
    item2 = Item(id="ARR-000001", data_class="TTC", size_bytes=256, deadline=FIRST_PASS_ANCHOR_S + 400.0)
    arrivals = [(FIRST_PASS_ANCHOR_S, item1), (FIRST_PASS_ANCHOR_S, item2)]
    policy = _HoldOnceThenServePolicy()
    import sim.driver as driver_module

    monkeypatch.setattr(driver_module, "generate_arrivals", lambda *a, **k: list(arrivals))
    result = driver_module.run_simulation(
        cfg, duration_s=FIRST_PASS_ANCHOR_S, dt_s=60.0, seed=SEED, policy=policy,
    )
    by_id = {d.item_id: d for d in result.deliveries}

    assert policy.calls == 1
    assert by_id["ARR-000001"].delivered is False

def test_energy_never_double_counted_across_items_in_one_tick(monkeypatch):
    cfg = load_config(CONFIG_A)
    dt_s = 60.0
    arrivals = [
        (
            FIRST_PASS_ANCHOR_S,
            Item(id=f"ARR-{i:06d}", data_class="TTC", size_bytes=256, deadline=FIRST_PASS_ANCHOR_S + 300.0),
        )
        for i in range(5)
    ]
    result = _run_with_fixed_arrivals(
        monkeypatch, cfg, arrivals, duration_s=FIRST_PASS_ANCHOR_S, dt_s=dt_s,
    )
    delivered_this_tick = [d for d in result.deliveries if d.delivery_time_s == FIRST_PASS_ANCHOR_S]
    assert len(delivered_this_tick) == 5

    total_energy_wh = sum(d.energy_wh for d in delivered_this_tick)
    tick_budget_wh = DRAW_W_COMMS_TTC * dt_s / 3600.0
    assert total_energy_wh <= tick_budget_wh
    assert total_energy_wh < tick_budget_wh / 10.0

def test_within_tick_mode_switch_gives_second_item_fresh_dwell_time(monkeypatch):
    cfg = load_config(CONFIG_A)
    arrivals = [
        (
            FIRST_PASS_ANCHOR_S,
            Item(id="ARR-000000", data_class="SSTV", size_bytes=2048, deadline=FIRST_PASS_ANCHOR_S + 3600.0),
        ),
        (
            FIRST_PASS_ANCHOR_S,
            Item(id="ARR-000001", data_class="SSTV", size_bytes=2048, deadline=FIRST_PASS_ANCHOR_S + 3700.0),
        ),
    ]
    result = _run_with_fixed_arrivals(
        monkeypatch, cfg, arrivals, duration_s=FIRST_PASS_ANCHOR_S, dt_s=30.0,
    )
    by_id = {d.item_id: d for d in result.deliveries}

    assert by_id["ARR-000000"].delivered is True
    assert by_id["ARR-000001"].delivered is True
    assert by_id["ARR-000000"].delivery_time_s == FIRST_PASS_ANCHOR_S
    assert by_id["ARR-000001"].delivery_time_s == FIRST_PASS_ANCHOR_S

    item_transmit_time_s = 2048 * 8 / LINK_DATA_RATE_BPS
    burst_rate_energy_wh = DRAW_W_COMMS_SSTV * item_transmit_time_s / 3600.0
    idle_rate_energy_wh = DRAW_W_IDLE * item_transmit_time_s / 3600.0

    assert by_id["ARR-000000"].energy_wh == pytest.approx(burst_rate_energy_wh)
    assert by_id["ARR-000001"].energy_wh == pytest.approx(burst_rate_energy_wh)
    assert by_id["ARR-000001"].energy_wh != pytest.approx(idle_rate_energy_wh)
    assert COMMS_BURST_DURATION_S < FIRST_PASS_ANCHOR_S

def test_ticks_since_last_service_resets_to_zero_when_any_item_delivered(monkeypatch):
    cfg = load_config(CONFIG_A)
    t_batch = FIRST_PASS_ANCHOR_S
    t_fourth = FIRST_PASS_ANCHOR_S + 30.0
    arrivals = [
        (t_batch, Item(id=f"ARR-{i:06d}", data_class="TTC", size_bytes=256, deadline=t_batch + 300.0))
        for i in range(3)
    ] + [
        (t_fourth, Item(id="ARR-000003", data_class="TTC", size_bytes=256, deadline=t_batch + 300.0)),
    ]
    rows = []
    import sim.driver as driver_module

    monkeypatch.setattr(driver_module, "generate_arrivals", lambda *a, **k: list(arrivals))
    driver_module.run_simulation(
        cfg, duration_s=t_fourth, dt_s=30.0, seed=SEED,
        record_hook=lambda features, decision: rows.append(features),
    )
    assert len(rows) == 4
    quiet_ticks = int(t_batch // 30.0)
    assert rows[0].ticks_since_last_service == quiet_ticks
    assert rows[1].ticks_since_last_service == quiet_ticks
    assert rows[2].ticks_since_last_service == quiet_ticks
    assert rows[3].ticks_since_last_service == 0

def test_record_hook_is_called_with_features_and_decision():
    from policy.base import FeatureVector

    cfg = load_config(CONFIG_A)
    rows = []
    run_simulation(
        cfg, duration_s=DELIVERY_DURATION_S, dt_s=30.0, seed=SEED,
        record_hook=lambda features, decision: rows.append((features, decision)),
    )
    assert rows, "expected at least one recorded decision point"
    for features, decision in rows:
        assert isinstance(features, FeatureVector)
        assert decision in ("serve", "hold")
    assert all(decision == "serve" for _, decision in rows)

def test_tick_hook_is_called_once_per_tick_with_expected_keys():
    cfg = load_config(CONFIG_A)
    dt_s = 60.0
    ticks = []
    run_simulation(
        cfg, duration_s=SHORT_DURATION_S, dt_s=dt_s, seed=SEED,
        tick_hook=lambda t, snapshot: ticks.append((t, snapshot)),
    )
    expected_n_ticks = int(SHORT_DURATION_S // dt_s) + 1
    assert len(ticks) == expected_n_ticks
    expected_keys = {
        "elevation_deg", "is_illuminated", "link_is_up", "battery_soc_pct",
        "fsm_state_id", "fsm_state_category", "ttc_queue_depth",
        "sstv_queue_depth", "codec2_m17_queue_depth",
    }
    for t, snapshot in ticks:
        assert isinstance(t, float)
        assert set(snapshot.keys()) == expected_keys

def test_tick_hook_reflects_below_floor_at_epoch_then_a_real_pass_within_the_window():
    cfg = load_config(CONFIG_A)
    dt_s = 60.0
    snapshots = []

    def _hook(t, snapshot):
        snapshots.append((t, dict(snapshot)))

    run_simulation(cfg, duration_s=SHORT_DURATION_S, dt_s=dt_s, seed=SEED, tick_hook=_hook)

    first_t, first_snapshot = snapshots[0]
    assert first_t == 0.0
    assert first_snapshot["elevation_deg"] < 0.0
    assert first_snapshot["link_is_up"] is False

    assert any(
        snapshot["elevation_deg"] > 60.0
        and snapshot["link_is_up"] is True
        and snapshot["fsm_state_category"] == "comms-mode"
        for _t, snapshot in snapshots
    ), "expected at least one tick within the widened window to reflect the real first pass"

def test_tick_hook_none_does_not_change_existing_behavior():
    cfg = load_config(CONFIG_A)
    with_hook = run_simulation(
        cfg, duration_s=DELIVERY_DURATION_S, dt_s=30.0, seed=SEED,
        tick_hook=lambda t, snapshot: None,
    )
    without_hook = run_simulation(cfg, duration_s=DELIVERY_DURATION_S, dt_s=30.0, seed=SEED)
    assert len(with_hook.deliveries) == len(without_hook.deliveries)
    assert [d.delivered for d in with_hook.deliveries] == [d.delivered for d in without_hook.deliveries]
    assert [d.delivery_time_s for d in with_hook.deliveries] == [d.delivery_time_s for d in without_hook.deliveries]

def test_ground_stations_default_matches_pre_phase_b_behavior():
    cfg = load_config(CONFIG_A)
    default_run = run_simulation(cfg, duration_s=SHORT_DURATION_S, dt_s=60.0, seed=SEED)
    explicit_single = run_simulation(
        cfg, duration_s=SHORT_DURATION_S, dt_s=60.0, seed=SEED,
        ground_stations=(GROUND_STATIONS_DUAL[0],),
    )
    assert [d.delivered for d in default_run.deliveries] == [
        d.delivered for d in explicit_single.deliveries
    ]
    assert [d.delivery_time_s for d in default_run.deliveries] == [
        d.delivery_time_s for d in explicit_single.deliveries
    ]

def test_ground_stations_dual_elevation_is_never_below_single_station():
    cfg = load_config(CONFIG_A)
    single_snapshots = []
    dual_snapshots = []

    run_simulation(
        cfg, duration_s=SHORT_DURATION_S, dt_s=60.0, seed=SEED,
        tick_hook=lambda t, snapshot: single_snapshots.append(snapshot["elevation_deg"]),
    )
    run_simulation(
        cfg, duration_s=SHORT_DURATION_S, dt_s=60.0, seed=SEED,
        ground_stations=GROUND_STATIONS_DUAL,
        tick_hook=lambda t, snapshot: dual_snapshots.append(snapshot["elevation_deg"]),
    )

    assert len(single_snapshots) == len(dual_snapshots)
    for single_el, dual_el in zip(single_snapshots, dual_snapshots):
        assert dual_el >= single_el

def test_rate_per_class_per_hour_default_matches_pre_phase_b_behavior():
    cfg = load_config(CONFIG_A)
    default_run = run_simulation(cfg, duration_s=DELIVERY_DURATION_S, dt_s=30.0, seed=SEED)
    explicit_default = run_simulation(
        cfg, duration_s=DELIVERY_DURATION_S, dt_s=30.0, seed=SEED,
        rate_per_class_per_hour=None,
    )
    assert [d.delivered for d in default_run.deliveries] == [
        d.delivered for d in explicit_default.deliveries
    ]

def test_rate_per_class_per_hour_higher_rate_produces_more_arrivals():
    cfg = load_config(CONFIG_A)
    baseline = run_simulation(cfg, duration_s=DELIVERY_DURATION_S, dt_s=30.0, seed=SEED)
    storm = run_simulation(
        cfg, duration_s=DELIVERY_DURATION_S, dt_s=30.0, seed=SEED,
        rate_per_class_per_hour={"TTC": 200.0, "SSTV": 200.0, "CODEC2_M17": 200.0},
    )
    assert len(storm.deliveries) > len(baseline.deliveries)

def test_ground_auth_secret_default_matches_pre_phase_c_behavior():
    cfg = load_config(CONFIG_A)
    default_run = run_simulation(cfg, duration_s=DELIVERY_DURATION_S, dt_s=30.0, seed=SEED)
    explicit_none = run_simulation(
        cfg, duration_s=DELIVERY_DURATION_S, dt_s=30.0, seed=SEED, ground_auth_secret=None,
    )
    assert [d.delivered for d in default_run.deliveries] == [
        d.delivered for d in explicit_none.deliveries
    ]

def test_ground_auth_secret_with_correct_key_matches_unauthenticated_run():
    cfg = load_config(CONFIG_A)
    unauthenticated = run_simulation(cfg, duration_s=DELIVERY_DURATION_S, dt_s=30.0, seed=SEED)
    authenticated = run_simulation(
        cfg, duration_s=DELIVERY_DURATION_S, dt_s=30.0, seed=SEED,
        ground_auth_secret=b"the-real-ground-station-key",
    )
    assert [d.delivered for d in unauthenticated.deliveries] == [
        d.delivered for d in authenticated.deliveries
    ]
    assert [d.delivery_time_s for d in unauthenticated.deliveries] == [
        d.delivery_time_s for d in authenticated.deliveries
    ]

def test_no_network_access():
    import sim.driver as driver_module

    source = Path(driver_module.__file__).read_text()
    tree = ast.parse(source)

    banned = {"requests", "urllib", "socket"}
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module.split(".")[0])

    assert not (imported_modules & banned), (
        f"sim/driver.py imports network modules: {imported_modules & banned}"
    )

def _safe_transitions(cfg, result):
    safe = {sid for sid, s in cfg.states.items() if s.category == "safe"}
    ins = [e.now for e in result.decision_log if e.kind == "transition"
           and e.details["from_state"] not in safe and e.details["to_state"] in safe]
    outs = [e.now for e in result.decision_log if e.kind == "transition"
            and e.details["from_state"] in safe and e.details["to_state"] not in safe]
    return ins, outs

def test_injected_fault_enters_safe_mode_and_recovery_waits_for_fault_to_clear():
    cfg = load_config(CONFIG_A)
    start, end = 30_060.0, 31_860.0
    r = run_simulation(cfg, duration_s=36_000.0, dt_s=10.0, seed=42,
                       fault_episodes=((start, end, 3),))
    ins, outs = _safe_transitions(cfg, r)
    assert ins == [start]
    assert outs == [end]

def test_depleted_initial_soc_triggers_power_low_then_autonomous_recovery():
    cfg = load_config(CONFIG_C)
    r = run_simulation(cfg, duration_s=20_000.0, dt_s=10.0, seed=42, initial_soc_pct=25.2)
    ins, outs = _safe_transitions(cfg, r)
    assert len(ins) == 1 and len(outs) == 1 and outs[0] > ins[0]

def test_stress_knobs_default_to_reference_scenario():
    cfg = load_config(CONFIG_B)
    kw = dict(duration_s=3600.0, dt_s=10.0, seed=7)
    assert run_simulation(cfg, **kw) == run_simulation(
        cfg, **kw, battery_capacity_wh=4.5, solar_gen_w=0.4, initial_soc_pct=100.0,
        fault_episodes=(),
    )
