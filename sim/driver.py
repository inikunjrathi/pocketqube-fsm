from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from engine.arbitration import PendingEvent, arbitrate, merge_pending
from engine.config_loader import Config
from engine.decision_log import DecisionLogger
from engine.fsm import step
from engine.persistence import PersistenceLayer
from engine.scheduler import Item, Scheduler
from policy.base import BASELINE_POLICY, DecisionContext, Policy
from policy.features import build_features
from sim.data_arrival import generate_arrivals
from sim.event_mapping import build_event_map, resolve, scheduler_select_event_names
from sim.link import link_state
from engine.auth import sign_command
from sim.orbit import elevation_deg, load_satellite, propagate
from sim.power import (
    BatteryState,
    draw_for_state_category,
    is_illuminated,
    resolve_transmit_class,
    step_battery,
    transmit_class_map,
    transmit_draw_w,
)
from sim.scenario import (
    BATTERY_CAPACITY_WH,
    GROUND_STATION_ALT_M,
    GROUND_STATION_LAT_DEG,
    GROUND_STATION_LON_DEG,
    LINK_DATA_RATE_BPS,
    SOLAR_GEN_W,
)

_NOMINAL_FAULT_COUNT = 0

_BOOTSTRAP_STEP_S = 3600.0

_BOOTSTRAP_TELEMETRY = {
    "elevation": 90.0,
    "battery_soc": 100.0,
    "fault_count": _NOMINAL_FAULT_COUNT,
}

_INITIAL_BATTERY_SOC_PCT = 100.0

_PASS_END_EVENT_NAME = "PASS_END"
_POWER_LOW_EVENT_NAME = "POWER_LOW"
_FAULT_DETECTED_EVENT_NAME = "FAULT_DETECTED"
_FAULT_THRESHOLD_PARAM_NAME = "fault_count_threshold_for_latched_fault"
_AUTONOMOUS_RECOVERY_EVENT_NAME = "AUTONOMOUS_RECOVERY_CONDITIONS_MET"
_GROUND_OVERRIDE_EXIT_EVENT_NAME = "GROUND_OVERRIDE_EXIT_SAFE"

_BATTERY_RECOVERY_THRESHOLD_PARAM_NAME = "battery_soc_safe_mode_recovery_threshold_pct"

class DriverError(Exception):
    pass

@dataclass
class DeliveryRecord:
    item_id: str
    data_class: str
    arrival_time_s: float
    delivered: bool
    delivery_time_s: float | None
    latency_s: float | None
    deadline_missed: bool
    energy_wh: float | None

@dataclass
class SimulationResult:
    config_id: str
    deliveries: list[DeliveryRecord]
    decision_log: list
    final_context: dict

def run_simulation(
    cfg: Config,
    *,
    duration_s: float,
    dt_s: float,
    seed: int,
    policy: Policy = BASELINE_POLICY,
    record_hook=None,
    tick_hook=None,
    ground_stations: Sequence[tuple[float, float, float]] | None = None,
    rate_per_class_per_hour: dict[str, float] | None = None,
    ground_auth_secret: bytes | None = None,
    battery_capacity_wh: float | None = None,
    solar_gen_w: float | None = None,
    initial_soc_pct: float | None = None,
    fault_episodes: Sequence[tuple[float, float, int]] = (),
) -> SimulationResult:
    capacity_wh = BATTERY_CAPACITY_WH if battery_capacity_wh is None else battery_capacity_wh
    solar_w = SOLAR_GEN_W if solar_gen_w is None else solar_gen_w
    if ground_stations is None:
        ground_stations = ((GROUND_STATION_LAT_DEG, GROUND_STATION_LON_DEG, GROUND_STATION_ALT_M),)

    sat = load_satellite()
    start_time = _epoch_datetime(sat)

    scheduler = Scheduler(list(cfg.data_class_priority))
    event_map = build_event_map(cfg)
    arrivals = generate_arrivals(
        list(cfg.data_class_priority), duration_s, seed,
        rate_per_class_per_hour=rate_per_class_per_hour,
    )

    persistence = PersistenceLayer()
    logger = DecisionLogger()

    params_by_name = {p.name: p.value for p in cfg.parameters.values()}
    min_elevation_deg = float(params_by_name["link_quality_min_elevation_deg"])
    fade_margin_db = float(params_by_name["fade_margin_db"])

    state, context = _run_bootstrap(cfg, persistence, logger)
    tx_map = transmit_class_map(cfg)
    served_class: str | None = None

    state_entered_at_t = 0.0

    battery = BatteryState(
        soc_pct=_INITIAL_BATTERY_SOC_PCT if initial_soc_pct is None else initial_soc_pct
    )

    admitted: dict[str, Item] = {}
    records: dict[str, DeliveryRecord] = {}

    arrival_idx = 0
    n_arrivals = len(arrivals)
    n_ticks = int(duration_s // dt_s)
    ticks_since_last_service = 0
    event_queue: list[PendingEvent] = []

    for i in range(n_ticks + 1):
        t = i * dt_s
        when = start_time + timedelta(seconds=t)

        elevation = max(
            elevation_deg(sat, when, lat, lon, alt) for lat, lon, alt in ground_stations
        )
        illuminated = is_illuminated(propagate(sat, when), when)
        mode_before_tick = (state, resolve_transmit_class(tx_map, state, served_class))
        draw_w = transmit_draw_w(mode_before_tick[1], t - state_entered_at_t)
        battery = step_battery(
            battery, illuminated, draw_w, dt_s,
            capacity_wh=capacity_wh, solar_gen_w=solar_w,
        )

        fault_count = next(
            (n for start, end, n in fault_episodes if start <= t < end), _NOMINAL_FAULT_COUNT
        )
        telemetry = {
            "elevation": elevation, "battery_soc": battery.soc_pct,
            "fault_count": fault_count,
        }
        state_before_tick_transitions = state

        was_safe = cfg.states[state].category == "safe"
        pending = merge_pending(
            event_queue,
            _raise_tick_events(cfg, event_map, state, telemetry, t, params_by_name, min_elevation_deg),
        )
        state, context, event_queue = _service_pending(
            cfg, event_map, pending, state, context, telemetry, t, persistence, logger,
            ground_auth_secret=ground_auth_secret,
        )
        if was_safe and cfg.states[state].category != "safe":
            state, context = _reenter_comms_mode(cfg, state, context, persistence, logger, t)

        if state != state_before_tick_transitions:
            served_class = None

        link = link_state(elevation, min_elevation_deg, fade_margin_db)

        while arrival_idx < n_arrivals and arrivals[arrival_idx][0] <= t:
            arrival_time, item = arrivals[arrival_idx]
            scheduler.insert(item)
            admitted[item.id] = item
            records[item.id] = DeliveryRecord(
                item_id=item.id,
                data_class=item.data_class,
                arrival_time_s=arrival_time,
                delivered=False,
                delivery_time_s=None,
                latency_s=None,
                deadline_missed=False,
                energy_wh=None,
            )
            arrival_idx += 1

        if link.is_up and not scheduler.is_empty():
            remaining_transmit_time_s = dt_s
            state_entered_at_t_this_tick = state_entered_at_t
            delivered_any_this_tick = False

            while remaining_transmit_time_s > 0 and not scheduler.is_empty():
                candidates = scheduler.candidate_classes()
                item = scheduler.select_next(key=_edf_key)
                assert item is not None

                item_transmit_time_s = _item_transmit_time_s(item)
                if item_transmit_time_s > remaining_transmit_time_s:
                    scheduler.insert(item)
                    break

                remaining_items = scheduler.all_items()
                features = build_features(
                    priority_order=list(cfg.data_class_priority),
                    candidate_classes=candidates,
                    selected_item=item,
                    now=t,
                    battery_soc_pct=battery.soc_pct,
                    elevation_deg=elevation,
                    is_illuminated=illuminated,
                    ticks_since_last_service=ticks_since_last_service,
                )
                decision_context = DecisionContext(
                    cfg=cfg, sat=sat, start_time=start_time, state=state,
                    fsm_context=context, battery=battery, remaining_items=remaining_items,
                    selected_item=item, arrivals=arrivals, arrival_idx=arrival_idx,
                    event_map=event_map, min_elevation_deg=min_elevation_deg,
                    fade_margin_db=fade_margin_db, now=t, dt_s=dt_s,
                )
                decision = policy.decide(features, decision_context)
                if record_hook is not None:
                    record_hook(features, decision)

                if decision == "hold":
                    scheduler.insert(item)
                    break

                logger.record_scheduler_decision(
                    now=t, selected=item.data_class, candidates=candidates,
                    rule="data_class_priority+edf",
                )
                names = scheduler_select_event_names(event_map, item.data_class)
                if not names:
                    scheduler.insert(item)
                    break

                event_id = resolve(event_map, names[0])
                result = step(
                    cfg,
                    state,
                    event_id,
                    context,
                    telemetry=telemetry,
                    now=t,
                    persisted=persistence.load(),
                )
                if not result.legal:
                    scheduler.insert(item)
                    break

                from_state = state
                from_mode = (from_state, resolve_transmit_class(tx_map, from_state, served_class))
                state, context = result.new_state, result.context
                served_class = item.data_class
                to_mode = (state, resolve_transmit_class(tx_map, state, served_class))
                persistence.save(state, context)
                logger.record_transition(
                    now=t, from_state=from_state, event=event_id, result=result
                )
                if to_mode != from_mode:
                    state_entered_at_t_this_tick = t
                delivery_time_in_state_s = (
                    0.0 if to_mode != from_mode else t - state_entered_at_t_this_tick
                )
                _mark_delivered(
                    records[item.id], item, t, item_transmit_time_s, cfg, state,
                    delivery_time_in_state_s, to_mode[1],
                )
                admitted.pop(item.id, None)

                remaining_transmit_time_s -= item_transmit_time_s
                delivered_any_this_tick = True

            ticks_since_last_service = (
                0 if delivered_any_this_tick else ticks_since_last_service + 1
            )
        else:
            ticks_since_last_service += 1

        if (state, resolve_transmit_class(tx_map, state, served_class)) != mode_before_tick:
            state_entered_at_t = t

        if tick_hook is not None:
            queue_classes = scheduler.candidate_classes()
            tick_hook(t, {
                "elevation_deg": elevation,
                "is_illuminated": illuminated,
                "link_is_up": link.is_up,
                "battery_soc_pct": battery.soc_pct,
                "fsm_state_id": state,
                "fsm_state_category": cfg.states[state].category,
                "ttc_queue_depth": queue_classes.count("TTC"),
                "sstv_queue_depth": queue_classes.count("SSTV"),
                "codec2_m17_queue_depth": queue_classes.count("CODEC2_M17"),
            })

    for item_id, item in admitted.items():
        if item.deadline is not None and duration_s > item.deadline:
            records[item_id].deadline_missed = True

    return SimulationResult(
        config_id=cfg.config_id,
        deliveries=list(records.values()),
        decision_log=list(logger.entries),
        final_context=dict(context),
    )

def _mark_delivered(
    record: DeliveryRecord,
    item: Item,
    t: float,
    item_transmit_time_s: float,
    cfg: Config,
    new_state: str,
    time_in_state_s: float,
    transmit_class: str | None,
) -> None:
    record.delivered = True
    record.delivery_time_s = t
    record.latency_s = t - record.arrival_time_s
    record.deadline_missed = item.deadline is not None and t > item.deadline
    record.energy_wh = (
        transmit_draw_w(transmit_class, time_in_state_s) * item_transmit_time_s / 3600.0
    )

def _run_bootstrap(
    cfg: Config, persistence: PersistenceLayer, logger: DecisionLogger
) -> tuple[str, dict]:
    path = _find_bootstrap_path(cfg)
    state, context = cfg.initial_state, {}
    for event_id, now in path:
        result = step(
            cfg,
            state,
            event_id,
            context,
            telemetry=_BOOTSTRAP_TELEMETRY,
            now=now,
            persisted=persistence.load(),
        )
        if not result.legal:
            raise DriverError(
                f"bootstrap replay produced an illegal step: "
                f"({state}, {event_id})"
            )
        from_state = state
        state, context = result.new_state, result.context
        persistence.save(state, context)
        logger.record_transition(
            now=now, from_state=from_state, event=event_id, result=result
        )
    return state, context

def _edf_key(item) -> float:
    return item.deadline if item.deadline is not None else math.inf

def _item_transmit_time_s(item: Item) -> float:
    return (item.size_bytes * 8) / LINK_DATA_RATE_BPS

def _item_energy_wh(
    state_name: str, time_in_state_s: float, item_transmit_time_s: float,
) -> float:
    return (
        draw_for_state_category(state_name, time_in_state_s)
        * item_transmit_time_s / 3600.0
    )

def _try_fire(
    cfg: Config,
    event_map,
    event_name: str,
    state: str,
    context: dict,
    telemetry: dict,
    now: float,
    persistence: PersistenceLayer,
    logger: DecisionLogger,
    ground_auth_secret: bytes | None = None,
) -> tuple[str, dict, bool]:
    if event_name not in event_map.by_name:
        return state, context, False
    event_id = resolve(event_map, event_name)
    command_signature = (
        sign_command(event_id, now, ground_auth_secret)
        if ground_auth_secret is not None
        else None
    )
    result = step(
        cfg, state, event_id, context, telemetry=telemetry, now=now,
        persisted=persistence.load(),
        ground_auth_secret=ground_auth_secret, command_signature=command_signature,
    )
    if not result.legal:
        return state, context, False
    persistence.save(result.new_state, result.context)
    logger.record_transition(now=now, from_state=state, event=event_id, result=result)
    return result.new_state, result.context, True

def _raise_tick_events(
    cfg: Config, event_map, state: str, telemetry: dict, now: float,
    params_by_name: dict, min_elevation_deg: float,
) -> list[PendingEvent]:
    names: list[str] = []
    if cfg.states[state].category == "safe":
        fault_threshold = params_by_name.get(_FAULT_THRESHOLD_PARAM_NAME)
        fault_count = telemetry["fault_count"]
        fault_active = (
            fault_count > _NOMINAL_FAULT_COUNT and fault_threshold is not None
            and fault_count >= float(fault_threshold)
        )
        if not fault_active:
            threshold = params_by_name.get(_BATTERY_RECOVERY_THRESHOLD_PARAM_NAME)
            if threshold is not None and telemetry["battery_soc"] >= float(threshold):
                names.append(_AUTONOMOUS_RECOVERY_EVENT_NAME)
            if telemetry["elevation"] >= min_elevation_deg:
                names.append(_GROUND_OVERRIDE_EXIT_EVENT_NAME)
    else:
        names.append(_POWER_LOW_EVENT_NAME)
        if telemetry["fault_count"] > _NOMINAL_FAULT_COUNT:
            names.append(_FAULT_DETECTED_EVENT_NAME)
        if cfg.states[state].category == "comms-mode":
            names.append(_PASS_END_EVENT_NAME)
    return [
        PendingEvent(resolve(event_map, n), now) for n in names if n in event_map.by_name
    ]

def _service_pending(
    cfg: Config, event_map, pending: list[PendingEvent], state: str, context: dict,
    telemetry: dict, now: float, persistence: PersistenceLayer, logger: DecisionLogger,
    ground_auth_secret: bytes | None = None,
) -> tuple[str, dict, list[PendingEvent]]:
    ordered = arbitrate(cfg, pending)
    for i, p in enumerate(ordered):
        state, context, fired = _try_fire(
            cfg, event_map, cfg.events[p.event_id].name, state, context,
            telemetry, now, persistence, logger, ground_auth_secret=ground_auth_secret,
        )
        if fired:
            return state, context, ordered[i + 1:]
    return state, context, []

def _maybe_recover_from_safe_mode(
    cfg: Config,
    event_map,
    state: str,
    context: dict,
    telemetry: dict,
    now: float,
    persistence: PersistenceLayer,
    logger: DecisionLogger,
    params_by_name: dict,
    min_elevation_deg: float,
    ground_auth_secret: bytes | None = None,
) -> tuple[str, dict, bool]:
    fault_threshold = params_by_name.get(_FAULT_THRESHOLD_PARAM_NAME)
    fault_count = telemetry["fault_count"]
    if fault_count > _NOMINAL_FAULT_COUNT and fault_threshold is not None and fault_count >= float(fault_threshold):
        return state, context, False

    if _BATTERY_RECOVERY_THRESHOLD_PARAM_NAME in params_by_name:
        recovery_threshold = float(params_by_name[_BATTERY_RECOVERY_THRESHOLD_PARAM_NAME])
        if telemetry["battery_soc"] >= recovery_threshold:
            new_state, new_context, fired = _try_fire(
                cfg, event_map, _AUTONOMOUS_RECOVERY_EVENT_NAME,
                state, context, telemetry, now, persistence, logger,
            )
            if fired:
                return new_state, new_context, True

    if telemetry["elevation"] >= min_elevation_deg:
        new_state, new_context, fired = _try_fire(
            cfg, event_map, _GROUND_OVERRIDE_EXIT_EVENT_NAME,
            state, context, telemetry, now, persistence, logger,
            ground_auth_secret=ground_auth_secret,
        )
        if fired:
            return new_state, new_context, True

    return state, context, False

def _reenter_comms_mode(
    cfg: Config, state: str, context: dict, persistence: PersistenceLayer,
    logger: DecisionLogger, now: float,
) -> tuple[str, dict]:
    path = _find_bootstrap_path(cfg, start_state=state)
    for event_id, _ in path:
        result = step(
            cfg, state, event_id, context, telemetry=_BOOTSTRAP_TELEMETRY,
            now=now, persisted=persistence.load(),
        )
        if not result.legal:
            raise DriverError(
                f"post-recovery re-entry produced an illegal step: ({state}, {event_id})"
            )
        from_state = state
        state, context = result.new_state, result.context
        persistence.save(state, context)
        logger.record_transition(now=now, from_state=from_state, event=event_id, result=result)
    return state, context

def _find_bootstrap_path(
    cfg: Config, start_state: str | None = None
) -> list[tuple[str, float]]:
    start = start_state if start_state is not None else cfg.initial_state
    comms_states = {sid for sid, s in cfg.states.items() if s.category == "comms-mode"}
    if not comms_states:
        raise DriverError("config defines no comms-mode state to bootstrap into")
    if cfg.states[start].category == "comms-mode":
        return []

    event_ids = sorted(cfg.events)
    to_by_transition = {t.id: t.to for t in cfg.transitions}

    start_key = (start, frozenset())
    visited = {start_key}
    queue: deque[tuple[str, dict, list[tuple[str, float]]]] = deque(
        [(start, {}, [])]
    )

    while queue:
        state, context, path = queue.popleft()
        now = len(path) * _BOOTSTRAP_STEP_S
        for event_id in event_ids:
            result = step(
                cfg,
                state,
                event_id,
                context,
                telemetry=_BOOTSTRAP_TELEMETRY,
                now=now,
                persisted=None,
            )
            if not result.legal:
                continue
            target = to_by_transition.get(result.transition_id)
            if target is None or target == "reload_from_persistence":
                continue
            new_state = result.new_state
            if cfg.states[new_state].category == "safe":
                continue

            new_path = path + [(event_id, now)]
            if new_state in comms_states:
                return new_path

            key = (new_state, frozenset(result.context.items()))
            if key in visited:
                continue
            visited.add(key)
            queue.append((new_state, result.context, new_path))

    raise DriverError("no bootstrap path from the initial state to a comms-mode state")

def _epoch_datetime(sat) -> datetime:
    year = sat.epochyr + 2000 if sat.epochyr < 57 else sat.epochyr + 1900
    return datetime(year, 1, 1) + timedelta(days=sat.epochdays - 1.0)
