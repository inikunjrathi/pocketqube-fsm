from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from engine.fsm import step
from engine.decision_log import DecisionLogger
from engine.persistence import PersistenceLayer
import heapq
import itertools
import math

from engine.scheduler import SchedulerError
from policy.base import DecisionContext, FeatureVector
from sim.driver import (
    _NOMINAL_FAULT_COUNT,
    _PASS_END_EVENT_NAME,
    _POWER_LOW_EVENT_NAME,
    _item_transmit_time_s,
    _maybe_recover_from_safe_mode,
    _reenter_comms_mode,
    _try_fire,
)
from sim.event_mapping import resolve, scheduler_select_event_names
from sim.link import link_state
from sim.orbit import elevation_deg, propagate
from sim.power import (
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
    SOLAR_GEN_W,
)

TTC_CLASS_NAME = "TTC"

ORACLE_HORIZON_S = 900.0

@dataclass(frozen=True)
class RolloutOutcome:
    ttc_deadline_misses: int
    other_deadline_misses: int
    energy_wh: float
    latency_s: float

    def score(self) -> tuple[int, int, float, float]:
        return (
            self.ttc_deadline_misses, self.other_deadline_misses,
            self.energy_wh, self.latency_s,
        )

class _EdfQueue:

    def __init__(self, priority_order: list[str]) -> None:
        self._rank = {cls: r for r, cls in enumerate(priority_order)}
        self._heap: list = []
        self._seq = itertools.count()

    def insert(self, item) -> None:
        rank = self._rank.get(item.data_class)
        if rank is None:
            raise SchedulerError(f"item {item.id!r} has unknown data class: {item.data_class!r}")
        deadline = item.deadline if item.deadline is not None else math.inf
        heapq.heappush(self._heap, (rank, deadline, next(self._seq), item))

    def select_next(self):
        return heapq.heappop(self._heap)[3] if self._heap else None

    def all_items(self) -> list:
        return [entry[3] for entry in self._heap]

    def is_empty(self) -> bool:
        return not self._heap

_TX_MAPS: dict = {}

def _tx_map(cfg):
    key = (cfg.config_id, id(cfg))
    if key not in _TX_MAPS:
        _TX_MAPS[key] = transmit_class_map(cfg)
    return _TX_MAPS[key]

_DEFAULT_GROUND_STATIONS = (
    (GROUND_STATION_LAT_DEG, GROUND_STATION_LON_DEG, GROUND_STATION_ALT_M),
)

class OraclePolicy:

    def __init__(self, ground_stations=None) -> None:
        self.ground_stations = tuple(ground_stations or _DEFAULT_GROUND_STATIONS)

    def decide(self, features: FeatureVector, context: DecisionContext) -> str:
        serve_outcome = _rollout(context, action="serve", ground_stations=self.ground_stations)
        hold_outcome = _rollout(context, action="hold", ground_stations=self.ground_stations)
        return "serve" if serve_outcome.score() <= hold_outcome.score() else "hold"

def _rollout(
    context: DecisionContext, *, action: str, ground_stations=_DEFAULT_GROUND_STATIONS,
) -> RolloutOutcome:
    cfg, sat, start_time = context.cfg, context.sat, context.start_time
    state, fsm_context = context.state, dict(context.fsm_context)
    battery = context.battery
    event_map = context.event_map
    now, dt_s = context.now, context.dt_s
    min_elevation_deg, fade_margin_db = context.min_elevation_deg, context.fade_margin_db
    acted_item = context.selected_item

    scheduler = _EdfQueue(list(cfg.data_class_priority))
    for it in context.remaining_items:
        scheduler.insert(it)
    if action == "hold":
        scheduler.insert(acted_item)

    persistence = PersistenceLayer(latch.name for latch in cfg.latches)
    logger = DecisionLogger()
    params_by_name = {p.name: p.value for p in cfg.parameters.values()}

    ttc_misses = 0
    other_misses = 0
    energy_wh = 0.0
    responsiveness_s = 0.0
    idx = context.arrival_idx
    arrivals = context.arrivals
    n_arrivals = len(arrivals)
    horizon_ticks = max(1, int(ORACLE_HORIZON_S // dt_s))

    state_entered_at_t = now
    tx_map = _tx_map(cfg)
    served_class = None

    for step_i in range(horizon_ticks):
        t = now + step_i * dt_s
        when = start_time + timedelta(seconds=t)
        elevation = max(
            elevation_deg(sat, when, lat, lon, alt) for lat, lon, alt in ground_stations
        )
        illuminated = is_illuminated(propagate(sat, when), when)
        mode_before_tick = (state, resolve_transmit_class(tx_map, state, served_class))
        draw_w = transmit_draw_w(mode_before_tick[1], t - state_entered_at_t)
        battery = step_battery(
            battery, illuminated, draw_w, dt_s,
            capacity_wh=BATTERY_CAPACITY_WH, solar_gen_w=SOLAR_GEN_W,
        )
        telemetry = {
            "elevation": elevation, "battery_soc": battery.soc_pct,
            "fault_count": _NOMINAL_FAULT_COUNT,
        }
        state_before_tick_transitions = state

        if cfg.states[state].category == "safe":
            state, fsm_context, recovered = _maybe_recover_from_safe_mode(
                cfg, event_map, state, fsm_context, telemetry, t, persistence,
                logger, params_by_name, min_elevation_deg,
            )
            if recovered:
                state, fsm_context = _reenter_comms_mode(
                    cfg, state, fsm_context, persistence, logger, t,
                )
        else:
            state, fsm_context, _ = _try_fire(
                cfg, event_map, _POWER_LOW_EVENT_NAME, state, fsm_context,
                telemetry, t, persistence, logger,
            )
        if cfg.states[state].category == "comms-mode":
            state, fsm_context, _ = _try_fire(
                cfg, event_map, _PASS_END_EVENT_NAME, state, fsm_context,
                telemetry, t, persistence, logger,
            )

        if state != state_before_tick_transitions:
            served_class = None

        while idx < n_arrivals and arrivals[idx][0] <= t:
            _, arriving_item = arrivals[idx]
            scheduler.insert(arriving_item)
            idx += 1

        link = link_state(elevation, min_elevation_deg, fade_margin_db)

        remaining_transmit_time_s = dt_s
        state_entered_at_t_this_tick = state_entered_at_t
        run_tail_this_tick = step_i > 0

        if step_i == 0 and action == "serve":
            item_transmit_time_s = _item_transmit_time_s(acted_item)
            names = scheduler_select_event_names(event_map, acted_item.data_class)
            served = False
            if names:
                event_id = resolve(event_map, names[0])
                result = step(
                    cfg, state, event_id, fsm_context, telemetry=telemetry,
                    now=t, persisted=None,
                )
                if result.legal:
                    from_mode = (state, resolve_transmit_class(tx_map, state, served_class))
                    state, fsm_context = result.new_state, result.context
                    served_class = acted_item.data_class
                    to_mode = (state, resolve_transmit_class(tx_map, state, served_class))
                    if to_mode != from_mode:
                        state_entered_at_t_this_tick = t
                    delivery_time_in_state_s = (
                        0.0 if to_mode != from_mode else t - state_entered_at_t_this_tick
                    )
                    energy_wh += (
                        transmit_draw_w(to_mode[1], delivery_time_in_state_s)
                        * item_transmit_time_s / 3600.0
                    )
                    responsiveness_s += t - now
                    remaining_transmit_time_s -= item_transmit_time_s
                    served = True
            if not served:
                scheduler.insert(acted_item)
            run_tail_this_tick = True

        if run_tail_this_tick:
            while (
                remaining_transmit_time_s > 0
                and link.is_up
                and not scheduler.is_empty()
            ):
                item_to_serve = scheduler.select_next()
                assert item_to_serve is not None
                item_transmit_time_s = _item_transmit_time_s(item_to_serve)
                if item_transmit_time_s > remaining_transmit_time_s:
                    scheduler.insert(item_to_serve)
                    break

                names = scheduler_select_event_names(event_map, item_to_serve.data_class)
                if not names:
                    scheduler.insert(item_to_serve)
                    break

                event_id = resolve(event_map, names[0])
                result = step(
                    cfg, state, event_id, fsm_context, telemetry=telemetry,
                    now=t, persisted=None,
                )
                if not result.legal:
                    scheduler.insert(item_to_serve)
                    break

                from_mode = (state, resolve_transmit_class(tx_map, state, served_class))
                state, fsm_context = result.new_state, result.context
                served_class = item_to_serve.data_class
                to_mode = (state, resolve_transmit_class(tx_map, state, served_class))
                if to_mode != from_mode:
                    state_entered_at_t_this_tick = t
                delivery_time_in_state_s = (
                    0.0 if to_mode != from_mode else t - state_entered_at_t_this_tick
                )
                energy_wh += (
                    transmit_draw_w(to_mode[1], delivery_time_in_state_s)
                    * item_transmit_time_s / 3600.0
                )
                responsiveness_s += t - now
                remaining_transmit_time_s -= item_transmit_time_s

        if (state, resolve_transmit_class(tx_map, state, served_class)) != mode_before_tick:
            state_entered_at_t = t

    horizon_end = now + horizon_ticks * dt_s
    for remaining in scheduler.all_items():
        if remaining.deadline is not None and horizon_end > remaining.deadline:
            if remaining.data_class == TTC_CLASS_NAME:
                ttc_misses += 1
            else:
                other_misses += 1

    return RolloutOutcome(
        ttc_deadline_misses=ttc_misses, other_deadline_misses=other_misses,
        energy_wh=energy_wh, latency_s=responsiveness_s,
    )
