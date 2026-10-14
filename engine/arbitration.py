from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from engine.config_loader import Config
from engine.fsm import StepResult, step

_PASS_END = "PASS_END"
_RESET = "RESET"
_SELECT_PREFIX = "SCHEDULER_SELECT_"
_SELECT_IDLE = "SCHEDULER_SELECT_IDLE"

class ArbitrationError(Exception):
    pass

@dataclass(frozen=True)
class PendingEvent:
    event_id: str
    timestamp: float
    command_signature: Optional[str] = None

@dataclass(frozen=True)
class ArbitrationResult:
    result: Optional[StepResult]
    serviced: Optional[PendingEvent]
    dropped: tuple[PendingEvent, ...]
    remaining: tuple[PendingEvent, ...]

def _rule(tie_break: str) -> str:
    text = tie_break.lower()
    if "data_class_priority" in text:
        return "data_class"
    if "reset" in text and "wins" in text:
        return "reset_wins"
    if text == "" or "timestamp" in text:
        return "timestamp"
    raise ArbitrationError(f"unrecognised conflict_resolution tie_break: {tie_break!r}")

def _class_key(config: Config, name: str) -> int:
    n = len(config.data_class_priority)
    if name == _PASS_END:
        return 0
    if name == _SELECT_IDLE:
        return n + 2
    if name.startswith(_SELECT_PREFIX):
        suffix = name[len(_SELECT_PREFIX):]
        if suffix in config.data_class_priority:
            return 1 + config.data_class_priority.index(suffix)
        return n + 1
    return 0

def event_static_keys(config: Config) -> dict[str, tuple[int, int, int]]:
    keys: dict[str, tuple[int, int, int]] = {}
    for row in config.conflict_resolution:
        rule = _rule(row.tie_break)
        for eid in row.member_events:
            name = config.events[eid].name
            class_key = _class_key(config, name) if rule == "data_class" else 0
            reset_key = (0 if name == _RESET else 1) if rule == "reset_wins" else 0
            keys[eid] = (row.rank, class_key, reset_key)
    return keys

def arbitrate(config: Config, pending: Sequence[PendingEvent]) -> list[PendingEvent]:
    keys = event_static_keys(config)
    unknown = [p.event_id for p in pending if p.event_id not in keys]
    if unknown:
        raise ArbitrationError(f"pending events with no conflict rank: {unknown}")

    def key(p: PendingEvent):
        rank, class_key, reset_key = keys[p.event_id]
        return (rank, class_key, p.timestamp, reset_key, p.event_id)

    return sorted(pending, key=key)

def merge_pending(queued: Sequence[PendingEvent], raised: Sequence[PendingEvent]) -> list[PendingEvent]:
    by_id: dict[str, PendingEvent] = {}
    for p in [*queued, *raised]:
        if p.event_id not in by_id or p.timestamp < by_id[p.event_id].timestamp:
            by_id[p.event_id] = p
    return list(by_id.values())

def step_many(
    config: Config,
    state: str,
    pending: Sequence[PendingEvent],
    context: Mapping[str, Any],
    *,
    telemetry: Optional[Mapping[str, Any]] = None,
    now: float = 0,
    persisted: Optional[Mapping[str, Any]] = None,
    ground_auth_secret: Optional[bytes] = None,
) -> ArbitrationResult:
    ordered = arbitrate(config, pending)
    for i, p in enumerate(ordered):
        r = step(
            config, state, p.event_id, context, telemetry=telemetry, now=now,
            persisted=persisted, ground_auth_secret=ground_auth_secret,
            command_signature=p.command_signature,
        )
        if r.legal:
            return ArbitrationResult(r, p, tuple(ordered[:i]), tuple(ordered[i + 1:]))
    return ArbitrationResult(None, None, tuple(ordered), ())

def describe(config: Config, arb: ArbitrationResult) -> str:
    if arb.serviced is None:
        return "arbitration: no pending event had a legal transition"
    rank_of = {eid: row for row in config.conflict_resolution for eid in row.member_events}

    def label(p: PendingEvent) -> str:
        row = rank_of[p.event_id]
        return f"{p.event_id} {config.events[p.event_id].name} (rank {row.rank} {row.category})"

    over = ", ".join(label(p) for p in arb.remaining) or "none"
    return (
        f"serviced {label(arb.serviced)} via {arb.result.transition_id}; "
        f"still queued: {over}"
    )
