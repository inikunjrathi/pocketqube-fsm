from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from engine.fsm import StepResult

@dataclass(frozen=True)
class DecisionLogEntry:
    now: float
    kind: str
    rationale: str
    details: Mapping[str, Any]

class DecisionLogger:
    def __init__(self) -> None:
        self._entries: list[DecisionLogEntry] = []

    def record_transition(
        self,
        *,
        now: float,
        from_state: str,
        event: str,
        result: StepResult,
        guard_values: Optional[Mapping[str, Any]] = None,
        rationale: Optional[str] = None,
    ) -> DecisionLogEntry:
        details: dict[str, Any] = {
            "from_state": from_state,
            "event": event,
            "to_state": result.new_state,
            "transition_id": result.transition_id,
            "actions": result.actions,
            "legal": result.legal,
        }
        effective_guard_values = guard_values if guard_values is not None else result.guard_values
        if effective_guard_values is not None:
            details["guard_values"] = dict(effective_guard_values)

        entry = DecisionLogEntry(
            now=now,
            kind="transition",
            rationale=rationale or self._default_transition_rationale(from_state, event, result),
            details=details,
        )
        self._entries.append(entry)
        return entry

    def record_scheduler_decision(
        self,
        *,
        now: float,
        selected: str,
        candidates: list[str],
        rule: str,
        rationale: Optional[str] = None,
    ) -> DecisionLogEntry:
        entry = DecisionLogEntry(
            now=now,
            kind="scheduler",
            rationale=rationale
            or f"selected {selected!r} from candidates {candidates} per rule {rule!r}",
            details={"selected": selected, "candidates": candidates, "rule": rule},
        )
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> tuple[DecisionLogEntry, ...]:
        return tuple(self._entries)

    @staticmethod
    def _default_transition_rationale(from_state: str, event: str, result: StepResult) -> str:
        if not result.legal:
            return f"no-op: no legal transition for ({from_state}, {event})"
        actions = ", ".join(result.actions) if result.actions else "none"
        return (
            f"{from_state} --{event}--> {result.new_state} "
            f"via {result.transition_id} (actions: {actions})"
        )
