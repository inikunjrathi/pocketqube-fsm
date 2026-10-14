from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from engine.auth import AUTH_COUNTER_KEY, AuthConfigError, verify_command
from engine.config_loader import Config, TransitionDef
from engine.guards import evaluate_guard, resolve_operands

_SET_CONTEXT_RE = re.compile(r"^set context\.(\w+) = (.+)$")
_START_TIMER_RE = re.compile(r"^start_(\w+)$")
_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")
_QUOTED_STRING_RE = re.compile(r"^'([^']*)'$|^\"([^\"]*)\"$")

class FSMError(Exception):
    pass

@dataclass(frozen=True)
class StepResult:
    new_state: str
    context: dict
    actions: tuple[str, ...]
    transition_id: Optional[str]
    legal: bool
    guard_values: Optional[dict[str, Any]] = None

def step(
    config: Config,
    state: str,
    event: str,
    context: Mapping[str, Any],
    *,
    telemetry: Optional[Mapping[str, Any]] = None,
    now: float = 0,
    persisted: Optional[Mapping[str, Any]] = None,
    ground_auth_secret: Optional[bytes] = None,
    command_signature: Optional[str] = None,
    require_auth: bool = False,
    replay_protection: bool = False,
    command_counter: Optional[int] = None,
) -> StepResult:
    telemetry = telemetry or {}
    params = {pid: p.value for pid, p in config.parameters.items()}

    if (require_auth or replay_protection) and not ground_auth_secret:
        raise AuthConfigError("require_auth/replay_protection set but no ground_auth_secret")

    accepted_counter: Optional[int] = None
    if ground_auth_secret is not None and config.events[event].source == "ground":
        if replay_protection:
            last = context.get(AUTH_COUNTER_KEY, -1)
            ok = (
                type(command_counter) is int
                and command_counter > last
                and verify_command(event, now, command_signature, ground_auth_secret, command_counter)
            )
        else:
            ok = verify_command(event, now, command_signature, ground_auth_secret)
        if not ok:
            return StepResult(
                new_state=state, context=dict(context), actions=(), transition_id=None,
                legal=False,
            )
        if replay_protection:
            accepted_counter = command_counter
            context = {**context, AUTH_COUNTER_KEY: command_counter}

    chosen, guard_values = _select_transition(config, state, event, context, telemetry, params, now)
    if chosen is None:
        return StepResult(
            new_state=state, context=dict(context), actions=(), transition_id=None, legal=False
        )

    new_state, base_context = _resolve_target(config, chosen, state, context, persisted)
    latch_names = frozenset(latch.name for latch in config.latches)
    new_context = _apply_actions(base_context, chosen.actions, now, latch_names)
    new_context = _apply_latch_sets(new_context, config.latches, chosen.id)
    if accepted_counter is not None:
        new_context[AUTH_COUNTER_KEY] = max(new_context.get(AUTH_COUNTER_KEY, -1), accepted_counter)

    return StepResult(
        new_state=new_state,
        context=new_context,
        actions=chosen.actions,
        transition_id=chosen.id,
        legal=True,
        guard_values=guard_values,
    )

def _select_transition(
    config: Config,
    state: str,
    event: str,
    context: Mapping[str, Any],
    telemetry: Mapping[str, Any],
    params: Mapping[str, Any],
    now: float,
) -> tuple[Optional[TransitionDef], Optional[dict[str, Any]]]:
    for t in config.transitions_for(state, event):
        if t.guard is None:
            return t, None
        if evaluate_guard(t.guard, context=context, telemetry=telemetry, params=params, now=now):
            resolved = resolve_operands(
                t.guard, context=context, telemetry=telemetry, params=params, now=now
            )
            guard_values = {
                resolved["lhs"]["token"]: resolved["lhs"]["value"],
                resolved["rhs"]["token"]: resolved["rhs"]["value"],
            }
            return t, guard_values
    return None, None

def _resolve_target(
    config: Config,
    chosen: TransitionDef,
    state: str,
    context: Mapping[str, Any],
    persisted: Optional[Mapping[str, Any]],
) -> tuple[str, dict]:
    if chosen.to is None:
        return state, dict(context)
    if chosen.to == "reload_from_persistence":
        if persisted is not None:
            return persisted["state"], dict(persisted.get("context", {}))
        return config.initial_state, {}
    return chosen.to, dict(context)

def _apply_actions(
    base_context: dict, actions: tuple[str, ...], now: float, latch_names: frozenset[str]
) -> dict:
    new_context = dict(base_context)
    for action in actions:
        m = _SET_CONTEXT_RE.match(action)
        if m:
            name, value_token = m.group(1), m.group(2)
            value = _parse_action_value(value_token)
            if name in latch_names and new_context.get(name) is True and value is False:
                continue
            new_context[name] = value
            continue
        m = _START_TIMER_RE.match(action)
        if m:
            new_context[m.group(1)] = now
            continue
    return new_context

def _apply_latch_sets(context: dict, latches, transition_id: str) -> dict:
    new_context = dict(context)
    for latch in latches:
        if transition_id in latch.set_by:
            new_context[latch.name] = True
    return new_context

def _parse_action_value(token: str) -> Any:
    if token == "true":
        return True
    if token == "false":
        return False
    if _NUMBER_RE.match(token):
        return float(token) if "." in token else int(token)
    quoted = _QUOTED_STRING_RE.match(token)
    if quoted:
        return quoted.group(1) if quoted.group(1) is not None else quoted.group(2)
    raise FSMError(f"malformed context-mutation value: {token!r}")
