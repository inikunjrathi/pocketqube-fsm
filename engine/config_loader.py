from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

class ConfigError(Exception):
    pass

@dataclass(frozen=True)
class StateDef:
    id: str
    name: str
    category: str
    description: str
    entry_actions: tuple[str, ...]
    is_initial: bool

@dataclass(frozen=True)
class EventDef:
    id: str
    name: str
    source: str
    description: str

@dataclass(frozen=True)
class TransitionDef:
    id: str
    from_states: tuple[str, ...] | str
    event: str
    guard: str | None
    to: str | None
    actions: tuple[str, ...]
    requirements: tuple[str, ...]

    def applies_from(self, state_id: str, all_state_ids: frozenset[str]) -> bool:
        if self.from_states == "*":
            return state_id in all_state_ids
        return state_id in self.from_states

@dataclass(frozen=True)
class ParameterDef:
    id: str
    name: str
    value: Any
    applies_to: str
    source: str | None
    confidence: str
    rationale: str

@dataclass(frozen=True)
class LatchDef:
    name: str
    description: str
    set_by: tuple[str, ...]
    one_way: bool
    survives_reset: bool

@dataclass(frozen=True)
class ConflictRankDef:
    rank: int
    category: str
    member_events: tuple[str, ...]
    tie_break: str

@dataclass(frozen=True)
class ModeGroupDef:
    group_name: str
    member_states: tuple[str, ...]

@dataclass(frozen=True)
class Config:
    config_id: str
    name: str
    description: str
    version: str
    states: dict[str, StateDef]
    events: dict[str, EventDef]
    transitions: tuple[TransitionDef, ...]
    parameters: dict[str, ParameterDef]
    latches: tuple[LatchDef, ...]
    data_class_priority: tuple[str, ...]
    conflict_resolution: tuple[ConflictRankDef, ...]
    mode_exclusivity_groups: tuple[ModeGroupDef, ...]
    initial_state: str

    def param_value(self, param_id: str) -> Any:
        try:
            return self.parameters[param_id].value
        except KeyError:
            raise ConfigError(f"unknown parameter id referenced: {param_id}") from None

    def transitions_for(self, state_id: str, event_id: str) -> list[TransitionDef]:
        all_ids = frozenset(self.states)
        return [
            t
            for t in self.transitions
            if t.event == event_id and t.applies_from(state_id, all_ids)
        ]

def _require(d: dict, key: str, ctx: str) -> Any:
    if key not in d:
        raise ConfigError(f"{ctx}: missing required field '{key}'")
    return d[key]

def _load_states(raw: list[dict]) -> dict[str, StateDef]:
    states: dict[str, StateDef] = {}
    for row in raw:
        sid = _require(row, "id", "state")
        if sid in states:
            raise ConfigError(f"duplicate state id: {sid}")
        states[sid] = StateDef(
            id=sid,
            name=_require(row, "name", f"state {sid}"),
            category=row.get("category", ""),
            description=row.get("description", ""),
            entry_actions=tuple(row.get("entry_actions", [])),
            is_initial=bool(row.get("is_initial", False)),
        )
    return states

def _load_events(raw: list[dict]) -> dict[str, EventDef]:
    events: dict[str, EventDef] = {}
    for row in raw:
        eid = _require(row, "id", "event")
        if eid in events:
            raise ConfigError(f"duplicate event id: {eid}")
        events[eid] = EventDef(
            id=eid,
            name=_require(row, "name", f"event {eid}"),
            source=row.get("source", ""),
            description=row.get("description", ""),
        )
    return events

def _load_transitions(raw: list[dict]) -> tuple[TransitionDef, ...]:
    out = []
    seen_ids: set[str] = set()
    for row in raw:
        tid = _require(row, "id", "transition")
        if tid in seen_ids:
            raise ConfigError(f"duplicate transition id: {tid}")
        seen_ids.add(tid)
        from_val = _require(row, "from", f"transition {tid}")
        from_states = from_val if from_val == "*" else tuple(from_val)
        out.append(
            TransitionDef(
                id=tid,
                from_states=from_states,
                event=_require(row, "event", f"transition {tid}"),
                guard=row.get("guard"),
                to=row.get("to"),
                actions=tuple(row.get("actions", [])),
                requirements=tuple(row.get("requirements", [])),
            )
        )
    return tuple(out)

def _load_parameters(raw: list[dict]) -> dict[str, ParameterDef]:
    params: dict[str, ParameterDef] = {}
    for row in raw:
        pid = _require(row, "id", "parameter")
        if pid in params:
            raise ConfigError(f"duplicate parameter id: {pid}")
        params[pid] = ParameterDef(
            id=pid,
            name=_require(row, "name", f"parameter {pid}"),
            value=row.get("value"),
            applies_to=row.get("applies_to", ""),
            source=row.get("source"),
            confidence=row.get("confidence", ""),
            rationale=row.get("rationale", ""),
        )
    return params

def _load_latches(raw: list[dict]) -> tuple[LatchDef, ...]:
    return tuple(
        LatchDef(
            name=_require(row, "name", "latch"),
            description=row.get("description", ""),
            set_by=tuple(row.get("set_by", [])),
            one_way=bool(row.get("one_way", True)),
            survives_reset=bool(row.get("survives_reset", True)),
        )
        for row in raw
    )

def _load_conflict_resolution(raw: list[dict]) -> tuple[ConflictRankDef, ...]:
    return tuple(
        ConflictRankDef(
            rank=_require(row, "rank", "conflict_resolution row"),
            category=_require(row, "category", "conflict_resolution row"),
            member_events=tuple(row.get("member_events", [])),
            tie_break=row.get("tie_break", ""),
        )
        for row in raw
    )

def _load_mode_groups(raw: list[dict]) -> tuple[ModeGroupDef, ...]:
    return tuple(
        ModeGroupDef(
            group_name=_require(row, "group_name", "mode_exclusivity_groups row"),
            member_states=tuple(row.get("member_states", [])),
        )
        for row in raw
    )

def load_config(path: str | Path) -> Config:
    path = Path(path)
    with path.open() as f:
        raw = yaml.safe_load(f)

    meta = _require(raw, "meta", "config")
    states = _load_states(_require(raw, "states", "config"))
    events = _load_events(_require(raw, "events", "config"))
    transitions = _load_transitions(_require(raw, "transitions", "config"))
    parameters = _load_parameters(raw.get("parameters", []))
    latches = _load_latches(raw.get("latches", []))
    conflict_resolution = _load_conflict_resolution(
        _require(raw, "conflict_resolution", "config")
    )
    mode_groups = _load_mode_groups(raw.get("mode_exclusivity_groups", []))
    data_class_priority = tuple(raw.get("data_class_priority", []))

    initial_states = [s.id for s in states.values() if s.is_initial]
    if len(initial_states) != 1:
        raise ConfigError(
            f"config must have exactly one initial state, found {initial_states}"
        )

    cfg = Config(
        config_id=_require(meta, "config_id", "meta"),
        name=meta.get("name", ""),
        description=meta.get("description", ""),
        version=meta.get("version", ""),
        states=states,
        events=events,
        transitions=transitions,
        parameters=parameters,
        latches=latches,
        data_class_priority=data_class_priority,
        conflict_resolution=conflict_resolution,
        mode_exclusivity_groups=mode_groups,
        initial_state=initial_states[0],
    )
    _validate(cfg)
    return cfg

def _validate(cfg: Config) -> None:
    errors: list[str] = []
    state_ids = frozenset(cfg.states)
    event_ids = frozenset(cfg.events)

    for t in cfg.transitions:
        if t.from_states != "*":
            for s in t.from_states:
                if s not in state_ids:
                    errors.append(f"{t.id}: unknown from-state {s!r}")
        if t.event not in event_ids:
            errors.append(f"{t.id}: unknown event {t.event!r}")
        if t.to is not None and t.to != "reload_from_persistence" and t.to not in state_ids:
            errors.append(f"{t.id}: unknown to-state {t.to!r}")

    for latch in cfg.latches:
        for tid in latch.set_by:
            if tid not in {t.id for t in cfg.transitions}:
                errors.append(f"latch {latch.name!r}: unknown set_by transition {tid!r}")

    ranked_events: set[str] = set()
    seen_ranks: set[int] = set()
    for rank_def in cfg.conflict_resolution:
        if rank_def.rank in seen_ranks:
            errors.append(f"conflict_resolution: duplicate rank {rank_def.rank}")
        seen_ranks.add(rank_def.rank)
        for eid in rank_def.member_events:
            if eid not in event_ids:
                errors.append(
                    f"conflict_resolution rank {rank_def.rank}: unknown event {eid!r}"
                )
            if eid in ranked_events:
                errors.append(f"conflict_resolution: event {eid!r} ranked more than once")
            ranked_events.add(eid)
    missing = event_ids - ranked_events
    if missing:
        errors.append(f"conflict_resolution: events never ranked: {sorted(missing)}")

    for group in cfg.mode_exclusivity_groups:
        for s in group.member_states:
            if s not in state_ids:
                errors.append(
                    f"mode_exclusivity_groups[{group.group_name}]: unknown state {s!r}"
                )

    adjacency: dict[str, set[str]] = {}
    for t in cfg.transitions:
        if t.to in (None, "reload_from_persistence"):
            continue
        froms = state_ids if t.from_states == "*" else t.from_states
        for s in froms:
            adjacency.setdefault(s, set()).add(t.to)
    seen = {cfg.initial_state}
    frontier = [cfg.initial_state]
    while frontier:
        cur = frontier.pop()
        for nxt in adjacency.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                frontier.append(nxt)
    unreachable = state_ids - seen
    if unreachable:
        errors.append(f"unreachable states from {cfg.initial_state}: {sorted(unreachable)}")

    if errors:
        raise ConfigError(
            f"{cfg.config_id}: {len(errors)} validation error(s):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )
