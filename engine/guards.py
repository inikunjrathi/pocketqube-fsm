from __future__ import annotations

import re
from typing import Any, Mapping

_OPERATOR_RE = re.compile(r"==|!=|>=|<=|<|>")
_CONTEXT_REF_RE = re.compile(r"^context\.(\w+)$")
_ELAPSED_CALL_RE = re.compile(r"^elapsed\((\w+)\)$")
_PARAM_REF_RE = re.compile(r"^[A-Z]+-\d{3}$")
_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")
_QUOTED_STRING_RE = re.compile(r"^'([^']*)'$|^\"([^\"]*)\"$")

class GuardError(Exception):
    pass

def evaluate_guard(
    guard: str,
    *,
    context: Mapping[str, Any],
    telemetry: Mapping[str, Any],
    params: Mapping[str, Any],
    now: float,
) -> bool:
    resolved = resolve_operands(guard, context=context, telemetry=telemetry, params=params, now=now)
    lhs, rhs = resolved["lhs"]["value"], resolved["rhs"]["value"]
    op = resolved["operator"]

    if lhs is None or rhs is None:
        return False

    if op == "==":
        return lhs == rhs
    if op == "!=":
        return lhs != rhs
    if op == ">=":
        return lhs >= rhs
    if op == "<=":
        return lhs <= rhs
    if op == "<":
        return lhs < rhs
    return lhs > rhs

def resolve_operands(
    guard: str,
    *,
    context: Mapping[str, Any],
    telemetry: Mapping[str, Any],
    params: Mapping[str, Any],
    now: float,
) -> dict[str, Any]:
    lhs_str, op, rhs_str = _split(guard)
    lhs = _resolve_operand(lhs_str, context, telemetry, params, now)
    rhs = _resolve_operand(rhs_str, context, telemetry, params, now)
    return {
        "operator": op,
        "lhs": {"token": lhs_str, "value": lhs},
        "rhs": {"token": rhs_str, "value": rhs},
    }

def _split(guard: str) -> tuple[str, str, str]:
    match = _OPERATOR_RE.search(guard)
    if not match:
        raise GuardError(f"malformed guard (no operator found): {guard!r}")

    lhs_str = guard[: match.start()].strip()
    op = match.group(0)
    rhs_str = guard[match.end() :].strip()
    if not lhs_str or not rhs_str:
        raise GuardError(f"malformed guard: {guard!r}")
    return lhs_str, op, rhs_str

def _resolve_operand(
    token: str,
    context: Mapping[str, Any],
    telemetry: Mapping[str, Any],
    params: Mapping[str, Any],
    now: float,
) -> Any:
    if token == "true":
        return True
    if token == "false":
        return False
    if _NUMBER_RE.match(token):
        return float(token) if "." in token else int(token)
    quoted = _QUOTED_STRING_RE.match(token)
    if quoted:
        return quoted.group(1) if quoted.group(1) is not None else quoted.group(2)

    m = _CONTEXT_REF_RE.match(token)
    if m:
        return context.get(m.group(1), False)

    m = _ELAPSED_CALL_RE.match(token)
    if m:
        started_at = context.get(m.group(1))
        return None if started_at is None else now - started_at

    if _PARAM_REF_RE.match(token):
        if token not in params:
            raise GuardError(f"guard references unknown parameter id: {token!r}")
        return params[token]

    if re.match(r"^\w+$", token):
        if token not in telemetry:
            raise GuardError(f"guard references unsupplied telemetry field: {token!r}")
        return telemetry[token]

    raise GuardError(f"malformed guard operand: {token!r}")
