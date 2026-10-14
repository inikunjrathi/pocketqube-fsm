from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.config_loader import Config, TransitionDef, load_config  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "config-a.yaml"
DEFAULT_OUT_DIR = REPO_ROOT / "mcu" / "firmware" / "app" / "src"

_OPERATOR_RE = re.compile(r"==|!=|>=|<=|<|>")
_CONTEXT_REF_RE = re.compile(r"^context\.(\w+)$")
_ELAPSED_CALL_RE = re.compile(r"^elapsed\((\w+)\)$")
_PARAM_REF_RE = re.compile(r"^[A-Z]+-\d{3}$")
_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")
_QUOTED_STRING_RE = re.compile(r"^'([^']*)'$|^\"([^\"]*)\"$")
_BARE_IDENTIFIER_RE = re.compile(r"^\w+$")
_START_TIMER_RE = re.compile(r"^start_(\w+)$")
_SET_CONTEXT_RE = re.compile(r"^set context\.(\w+) = (.+)$")

_OPERATOR_TO_C = {
    "==": "GUARD_OP_EQ",
    "!=": "GUARD_OP_NE",
    ">=": "GUARD_OP_GE",
    "<=": "GUARD_OP_LE",
    "<": "GUARD_OP_LT",
    ">": "GUARD_OP_GT",
}

class CodegenError(Exception):
    pass

@dataclass(frozen=True)
class Operand:

    kind: str
    name: Optional[str] = None
    param_id: Optional[str] = None
    param_index: int = -1
    timer_index: int = -1
    num_value: float = 0.0
    bool_value: bool = False
    str_value: Optional[str] = None

NONE_OPERAND = Operand(kind="NONE")

@dataclass(frozen=True)
class GuardExpr:
    has_guard: bool
    op: Optional[str] = None
    lhs: Operand = NONE_OPERAND
    rhs: Operand = NONE_OPERAND

NO_GUARD = GuardExpr(has_guard=False)

@dataclass(frozen=True)
class Action:
    kind: str
    raw: str
    context_name: Optional[str] = None
    timer_name: Optional[str] = None
    timer_index: int = -1
    value: Operand = NONE_OPERAND

@dataclass(frozen=True)
class ParsedTransition:
    source: TransitionDef
    guard: GuardExpr
    actions: tuple[Action, ...]

def _split_guard(guard: str) -> tuple[str, str, str]:
    match = _OPERATOR_RE.search(guard)
    if not match:
        raise CodegenError(f"malformed guard (no operator found): {guard!r}")
    lhs_str = guard[: match.start()].strip()
    op = match.group(0)
    rhs_str = guard[match.end() :].strip()
    if not lhs_str or not rhs_str:
        raise CodegenError(f"malformed guard: {guard!r}")
    return lhs_str, op, rhs_str

def _classify_operand(token: str) -> Operand:
    if token == "true":
        return Operand(kind="LIT_BOOL", bool_value=True)
    if token == "false":
        return Operand(kind="LIT_BOOL", bool_value=False)
    if _NUMBER_RE.match(token):
        return Operand(kind="LIT_NUM", num_value=float(token))
    quoted = _QUOTED_STRING_RE.match(token)
    if quoted:
        value = quoted.group(1) if quoted.group(1) is not None else quoted.group(2)
        return Operand(kind="LIT_STR", str_value=value)

    m = _CONTEXT_REF_RE.match(token)
    if m:
        return Operand(kind="CONTEXT", name=m.group(1))

    m = _ELAPSED_CALL_RE.match(token)
    if m:
        return Operand(kind="ELAPSED", name=m.group(1))

    if _PARAM_REF_RE.match(token):
        return Operand(kind="PARAM", param_id=token)

    if _BARE_IDENTIFIER_RE.match(token):
        return Operand(kind="TELEMETRY", name=token)

    raise CodegenError(f"malformed guard operand: {token!r}")

def _parse_guard(guard: Optional[str]) -> GuardExpr:
    if guard is None:
        return NO_GUARD
    lhs_str, op, rhs_str = _split_guard(guard)
    return GuardExpr(
        has_guard=True,
        op=op,
        lhs=_classify_operand(lhs_str),
        rhs=_classify_operand(rhs_str),
    )

def _parse_action_value(token: str) -> Operand:
    if token == "true":
        return Operand(kind="LIT_BOOL", bool_value=True)
    if token == "false":
        return Operand(kind="LIT_BOOL", bool_value=False)
    if _NUMBER_RE.match(token):
        return Operand(kind="LIT_NUM", num_value=float(token))
    quoted = _QUOTED_STRING_RE.match(token)
    if quoted:
        value = quoted.group(1) if quoted.group(1) is not None else quoted.group(2)
        return Operand(kind="LIT_STR", str_value=value)
    raise CodegenError(f"malformed context-mutation action value: {token!r}")

def _parse_action(action: str) -> Action:
    m = _SET_CONTEXT_RE.match(action)
    if m:
        name, value_token = m.group(1), m.group(2)
        return Action(
            kind="SET_CONTEXT",
            raw=action,
            context_name=name,
            value=_parse_action_value(value_token),
        )
    m = _START_TIMER_RE.match(action)
    if m:
        return Action(kind="START_TIMER", raw=action, timer_name=m.group(1))
    return Action(kind="OPAQUE", raw=action)

def _parse_transition(t: TransitionDef) -> ParsedTransition:
    return ParsedTransition(
        source=t,
        guard=_parse_guard(t.guard),
        actions=tuple(_parse_action(a) for a in t.actions),
    )

def _guard_operands(guard: GuardExpr) -> tuple[Operand, ...]:
    if not guard.has_guard:
        return ()
    return (guard.lhs, guard.rhs)

def _referenced_param_ids(parsed: list[ParsedTransition]) -> set[str]:
    return {
        op.param_id
        for pt in parsed
        for op in _guard_operands(pt.guard)
        if op.kind == "PARAM"
    }

def _referenced_timer_ids(parsed: list[ParsedTransition]) -> set[str]:
    return {
        op.name
        for pt in parsed
        for op in _guard_operands(pt.guard)
        if op.kind == "ELAPSED"
    }

def _armed_timer_ids(parsed: list[ParsedTransition]) -> set[str]:
    return {
        a.timer_name
        for pt in parsed
        for a in pt.actions
        if a.kind == "START_TIMER"
    }

def _validate_params(cfg: Config, parsed: list[ParsedTransition], referenced: set[str]) -> None:
    for pt in parsed:
        for op in _guard_operands(pt.guard):
            if op.kind != "PARAM":
                continue
            pid = op.param_id
            if pid not in cfg.parameters:
                raise CodegenError(
                    f"{cfg.config_id}: transition {pt.source.id}'s guard "
                    f"{pt.source.guard!r} references unknown parameter id "
                    f"{pid!r} (engine.guards.evaluate_guard would raise "
                    f"GuardError on this at runtime; codegen refuses to "
                    f"build a table with a guard that can never resolve)"
                )
    for pid in referenced:
        value = cfg.parameters[pid].value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CodegenError(
                f"{cfg.config_id}: parameter {pid!r} is referenced by a "
                f"guard but its value ({value!r}, type "
                f"{type(value).__name__}) is not numeric -- only "
                f"numeric parameters can be compiled into the firmware's "
                f"parameters[] array (plan Task 2 Step 2: everything else "
                f"in ParameterDef.value is traceability metadata, dropped "
                f"from firmware, not emitted here)"
            )

def _validate_timers(
    cfg: Config, parsed: list[ParsedTransition], referenced: set[str], armed: set[str]
) -> None:
    missing = referenced - armed
    if not missing:
        return
    offending = sorted(
        pt.source.id
        for pt in parsed
        for op in _guard_operands(pt.guard)
        if op.kind == "ELAPSED" and op.name in missing
    )
    raise CodegenError(
        f"{cfg.config_id}: elapsed()/start_ mismatch -- transition(s) "
        f"{offending} reference elapsed() on timer id(s) {sorted(missing)} "
        f"but no transition in this config ever fires a 'start_<id>' "
        f"action for {sorted(missing)}. This is the historical near-bug "
        f"class documented in docs/config-schema.md's elapsed()/start_ "
        f"convention note (Config B originally armed "
        f"'start_switch_debounce_timer' but checked "
        f"'elapsed(switch_debounce)' -- a naming mismatch that would have "
        f"made the guard never resolve the timer it meant to read). "
        f"Codegen refuses to build a table with a dead elapsed() guard; "
        f"fix the config's action/guard identifiers to match exactly."
    )

@dataclass(frozen=True)
class ParamRow:
    id: str
    value: float

@dataclass(frozen=True)
class TransitionRow:
    id: str
    from_wildcard: bool
    from_mask: int
    event_index: int
    guard: GuardExpr
    target_kind: str
    to_state_index: int
    actions: tuple[Action, ...]

@dataclass(frozen=True)
class LatchRow:

    name: str
    set_by_indices: tuple[int, ...]

@dataclass(frozen=True)
class GeneratedTables:
    state_ids: tuple[str, ...]
    state_names: tuple[str, ...]
    event_ids: tuple[str, ...]
    event_names: tuple[str, ...]
    event_sources: tuple[str, ...]
    parameters: tuple[ParamRow, ...]
    timers: tuple[str, ...]
    transitions: tuple[TransitionRow, ...]
    latches: tuple[LatchRow, ...]
    initial_state_index: int

def _resolve_operand_indices(op: Operand, param_index: dict[str, int], timer_index: dict[str, int]) -> Operand:
    if op.kind == "PARAM":
        return replace(op, param_index=param_index[op.param_id])
    if op.kind == "ELAPSED":
        return replace(op, timer_index=timer_index[op.name])
    return op

def _resolve_guard_indices(guard: GuardExpr, param_index: dict[str, int], timer_index: dict[str, int]) -> GuardExpr:
    if not guard.has_guard:
        return guard
    return replace(
        guard,
        lhs=_resolve_operand_indices(guard.lhs, param_index, timer_index),
        rhs=_resolve_operand_indices(guard.rhs, param_index, timer_index),
    )

def _resolve_action_indices(action: Action, timer_index: dict[str, int]) -> Action:
    if action.kind == "START_TIMER":
        return replace(action, timer_index=timer_index.get(action.timer_name, -1))
    return action

def generate_tables(cfg: Config) -> GeneratedTables:
    if len(cfg.states) > 32:
        raise CodegenError(
            f"{cfg.config_id}: {len(cfg.states)} states exceeds the 32-state "
            f"limit of this codegen's uint32_t from_mask bitmask encoding"
        )

    state_order = list(cfg.states.values())
    state_index = {s.id: i for i, s in enumerate(state_order)}
    event_order = list(cfg.events.values())
    event_index = {e.id: i for i, e in enumerate(event_order)}

    parsed = [_parse_transition(t) for t in cfg.transitions]

    referenced_params = _referenced_param_ids(parsed)
    referenced_timers = _referenced_timer_ids(parsed)
    armed_timers = _armed_timer_ids(parsed)

    _validate_params(cfg, parsed, referenced_params)
    _validate_timers(cfg, parsed, referenced_timers, armed_timers)

    param_order = sorted(referenced_params)
    param_index = {pid: i for i, pid in enumerate(param_order)}
    timer_order = sorted(referenced_timers)
    timer_index = {tid: i for i, tid in enumerate(timer_order)}

    all_state_ids = frozenset(cfg.states)
    transitions: list[TransitionRow] = []
    for pt in parsed:
        t = pt.source
        from_wildcard = t.from_states == "*"
        if from_wildcard:
            from_mask = (1 << len(state_order)) - 1
        else:
            from_mask = 0
            for sid in t.from_states:
                from_mask |= 1 << state_index[sid]
        assert t.applies_from(next(iter(all_state_ids)), all_state_ids) in (True, False)

        if t.to is None:
            target_kind, to_state_index = "SELF", -1
        elif t.to == "reload_from_persistence":
            target_kind, to_state_index = "RELOAD", -1
        else:
            target_kind, to_state_index = "STATE", state_index[t.to]

        guard = _resolve_guard_indices(pt.guard, param_index, timer_index)
        actions = tuple(_resolve_action_indices(a, timer_index) for a in pt.actions)

        transitions.append(
            TransitionRow(
                id=t.id,
                from_wildcard=from_wildcard,
                from_mask=from_mask,
                event_index=event_index[t.event],
                guard=guard,
                target_kind=target_kind,
                to_state_index=to_state_index,
                actions=actions,
            )
        )

    transition_index = {t.id: i for i, t in enumerate(cfg.transitions)}
    latches = tuple(
        LatchRow(
            name=latch.name,
            set_by_indices=tuple(transition_index[tid] for tid in latch.set_by),
        )
        for latch in cfg.latches
    )

    return GeneratedTables(
        state_ids=tuple(s.id for s in state_order),
        state_names=tuple(s.name for s in state_order),
        event_ids=tuple(e.id for e in event_order),
        event_names=tuple(e.name for e in event_order),
        event_sources=tuple(e.source for e in event_order),
        parameters=tuple(ParamRow(id=pid, value=float(cfg.parameters[pid].value)) for pid in param_order),
        timers=tuple(timer_order),
        transitions=tuple(transitions),
        latches=latches,
        initial_state_index=state_index[cfg.initial_state],
    )

def c_ident(raw: str) -> str:
    return raw.replace("-", "_")

def _c_string(s: Optional[str]) -> str:
    if s is None:
        return "NULL"
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'

def _c_bool(b: bool) -> str:
    return "true" if b else "false"

def _c_double(x: float) -> str:
    return repr(float(x))

def _render_operand(op: Operand) -> str:
    kind = {
        "NONE": "OPERAND_NONE",
        "CONTEXT": "OPERAND_CONTEXT",
        "TELEMETRY": "OPERAND_TELEMETRY",
        "PARAM": "OPERAND_PARAM",
        "ELAPSED": "OPERAND_ELAPSED",
        "LIT_NUM": "OPERAND_LITERAL_NUM",
        "LIT_BOOL": "OPERAND_LITERAL_BOOL",
        "LIT_STR": "OPERAND_LITERAL_STR",
    }[op.kind]
    return (
        f"{{ .kind = {kind}, .name = {_c_string(op.name)}, "
        f".param_index = {op.param_index}, .timer_index = {op.timer_index}, "
        f".num_value = {_c_double(op.num_value)}, .bool_value = {_c_bool(op.bool_value)}, "
        f".str_value = {_c_string(op.str_value)} }}"
    )

def _render_guard(guard: GuardExpr, indent: str) -> list[str]:
    op = _OPERATOR_TO_C[guard.op] if guard.has_guard else "GUARD_OP_EQ /* unused: has_guard == false */"
    lines = [
        f"{indent}.guard = {{",
        f"{indent}    .has_guard = {_c_bool(guard.has_guard)},",
        f"{indent}    .op = {op},",
        f"{indent}    .lhs = {_render_operand(guard.lhs)},",
        f"{indent}    .rhs = {_render_operand(guard.rhs)},",
        f"{indent}}},",
    ]
    return lines

def _render_action(a: Action) -> str:
    kind = {"OPAQUE": "ACTION_OPAQUE", "SET_CONTEXT": "ACTION_SET_CONTEXT", "START_TIMER": "ACTION_START_TIMER"}[a.kind]
    return (
        f"    {{ .kind = {kind}, .raw = {_c_string(a.raw)}, "
        f".context_name = {_c_string(a.context_name)}, .timer_name = {_c_string(a.timer_name)}, "
        f".timer_index = {a.timer_index}, .value = {_render_operand(a.value)} }},"
    )

def render_header(cfg: Config, tables: GeneratedTables) -> str:
    lines = [
        "/* AUTO-GENERATED FILE -- DO NOT HAND-EDIT.",
        f" * Generated by tools/codegen_c_table.py from config/{cfg.config_id}.yaml",
        " * Regenerate with:",
        f" *     python3 tools/codegen_c_table.py config/{cfg.config_id}.yaml",
        " * from the repo root. Edit the source YAML and regenerate instead of",
        " * hand-editing this file.",
        " */",
        "#ifndef ENGINE_CONFIG_TABLE_H",
        "#define ENGINE_CONFIG_TABLE_H",
        "",
        "#include <stdbool.h>",
        "#include <stdint.h>",
        "",
        "#ifdef __cplusplus",
        'extern "C" {',
        "#endif",
        "",
        "/* --- states --- */",
        "typedef enum {",
    ]
    for sid in tables.state_ids:
        lines.append(f"    STATE_{c_ident(sid)},")
    lines.append("    STATE_COUNT")
    lines.append("} state_id_t;")
    lines.append("")
    lines.append("typedef struct {")
    lines.append('    const char *id;   /* e.g. "S-01" */')
    lines.append('    const char *name; /* e.g. "STOWED" */')
    lines.append("} state_def_t;")
    lines.append("")
    lines.append("/* --- events --- */")
    lines.append("typedef enum {")
    for eid in tables.event_ids:
        lines.append(f"    EVENT_{c_ident(eid)},")
    lines.append("    EVENT_COUNT")
    lines.append("} event_id_t;")
    lines.append("")
    lines.extend(
        [
            "typedef struct {",
            '    const char *id;     /* e.g. "E-01" */',
            "    const char *name;",
            '    const char *source; /* EventDef.source verbatim, e.g. "ground" --',
            "                           engine/fsm.py's auth short-circuit gates on",
            '                           `config.events[event].source == "ground"` */',
            "} event_def_t;",
            "",
            "/* --- guard operand grammar (docs/config-schema.md) --- */",
            "typedef enum {",
            "    OPERAND_NONE = 0,   /* unused slot (guard-less transition) */",
            "    OPERAND_CONTEXT,    /* context.<name>; missing -> false, not an error */",
            "    OPERAND_TELEMETRY,  /* bare identifier; missing -> runtime hard error */",
            "    OPERAND_PARAM,      /* index into g_parameters[] */",
            "    OPERAND_ELAPSED,    /* index into g_timers[]; unarmed -> VAL_NONE */",
            "    OPERAND_LITERAL_NUM,",
            "    OPERAND_LITERAL_BOOL,",
            "    OPERAND_LITERAL_STR,",
            "} operand_kind_t;",
            "",
            "typedef struct {",
            "    operand_kind_t kind;",
            "    const char *name;      /* CONTEXT/TELEMETRY/ELAPSED identifier, else NULL */",
            "    int32_t param_index;   /* PARAM: index into g_parameters[], else -1 */",
            "    int32_t timer_index;   /* ELAPSED: index into g_timers[], else -1 */",
            "    double num_value;      /* LITERAL_NUM, else 0.0 */",
            "    bool bool_value;       /* LITERAL_BOOL, else false */",
            "    const char *str_value; /* LITERAL_STR, else NULL */",
            "} guard_operand_t;",
            "",
            "typedef enum {",
            "    GUARD_OP_EQ = 0,",
            "    GUARD_OP_NE,",
            "    GUARD_OP_GE,",
            "    GUARD_OP_LE,",
            "    GUARD_OP_LT,",
            "    GUARD_OP_GT,",
            "} guard_op_t;",
            "",
            "typedef struct {",
            "    bool has_guard;      /* false: transition is unconditional */",
            "    guard_op_t op;       /* unused when has_guard == false */",
            "    guard_operand_t lhs;",
            "    guard_operand_t rhs;",
            "} guard_expr_t;",
            "",
            "/* --- action string semantics (docs/config-schema.md) --- */",
            "typedef enum {",
            "    ACTION_OPAQUE = 0,  /* recorded verbatim in the decision log, no other effect */",
            '    ACTION_SET_CONTEXT, /* "set context.<name> = <value>" */',
            '    ACTION_START_TIMER, /* "start_<timer_id>" -- arms elapsed(<timer_id>) */',
            "} action_kind_t;",
            "",
            "typedef struct {",
            "    action_kind_t kind;",
            "    const char *raw;          /* original action string, verbatim, for the",
            "                                  DECISION log's actions=<a1,a2,...> field */",
            "    const char *context_name; /* SET_CONTEXT target name, else NULL */",
            "    const char *timer_name;   /* START_TIMER timer id (context slot), else NULL */",
            "    int32_t timer_index;      /* START_TIMER: index into g_timers[] if this",
            "                                  timer is read by some elapsed() guard in this",
            "                                  config, else -1 (armed but never read --",
            "                                  harmless, not a build error) */",
            "    guard_operand_t value;    /* SET_CONTEXT: literal value (LITERAL_BOOL/",
            "                                  NUM/STR); unused for OPAQUE/START_TIMER */",
            "} action_t;",
            "",
            "/* --- numeric-only parameters (guard-referenced subset only; see",
            " * module docstring in tools/codegen_c_table.py for why the rest of",
            " * ParameterDef.value is dropped) --- */",
            "typedef struct {",
            '    const char *id; /* e.g. "P-010" */',
            "    double value;",
            "} parameter_t;",
            "",
            "/* --- elapsed()/start_ timers (guard-referenced subset only) --- */",
            "typedef struct {",
            '    const char *id; /* e.g. "rf_inhibit_timer" */',
            "} timer_def_t;",
            "",
            "/* --- transitions --- */",
            "typedef enum {",
            "    TARGET_SELF = 0,            /* to: null -> self-loop */",
            '    TARGET_STATE,                /* to: "<state-id>" */',
            '    TARGET_RELOAD_PERSISTENCE,   /* to: "reload_from_persistence" */',
            "} target_kind_t;",
            "",
            "typedef struct {",
            '    const char *id;         /* e.g. "T-01" */',
            '    bool from_wildcard;      /* from: "*" in the source YAML */',
            "    uint32_t from_mask;      /* bit i set <=> STATE_<i> is a legal origin;",
            "                                fully set when from_wildcard == true */",
            "    event_id_t event;",
            "    guard_expr_t guard;",
            "    target_kind_t target_kind;",
            "    state_id_t to_state;     /* valid only if target_kind == TARGET_STATE;",
            "                                STATE_COUNT (sentinel) otherwise */",
            "    const action_t *actions;",
            "    uint8_t actions_count;",
            "} transition_t;",
            "",
            "/* --- latches (engine.config_loader.LatchDef) --- */",
            "/* Deliberately independent of action_t's ACTION_SET_CONTEXT above --",
            " * see engine/fsm.py's `_apply_latch_sets` docstring and this project's",
            " * Phase 8 Task 4 plan section (\"two separate one-way-latch mechanisms",
            " * ... port both as independent paths, do NOT collapse them\"). A",
            " * latch's `set_by` names g_transitions[] indices (resolved at codegen",
            " * time from LatchDef.set_by's transition-id strings): whenever a",
            " * transition whose index appears here fires, engine_fsm.c sets this",
            " * latch's context flag true, unconditionally -- entirely independent",
            " * of whatever that transition's own .actions array contains.",
            " * `one_way`/`survives_reset` (LatchDef fields) are traceability-only",
            " * in engine/fsm.py itself and are not compiled into firmware -- see",
            " * tools/codegen_c_table.py's LatchRow docstring. */",
            "typedef struct {",
            "    const char *name;       /* context flag name this latch controls */",
            "    const uint32_t *set_by; /* g_transitions[] indices; NULL if none */",
            "    uint32_t set_by_count;",
            "} latch_def_t;",
            "",
            f"#define ENGINE_CONFIG_ID {_c_string(cfg.config_id)}",
            f"#define ENGINE_CONFIG_INITIAL_STATE STATE_{c_ident(cfg.initial_state)}",
            "",
            "extern const state_def_t g_states[STATE_COUNT];",
            "extern const event_def_t g_events[EVENT_COUNT];",
            "extern const parameter_t g_parameters[];",
            "extern const uint32_t g_parameters_count;",
            "extern const timer_def_t g_timers[];",
            "extern const uint32_t g_timers_count;",
            "extern const transition_t g_transitions[];",
            "extern const uint32_t g_transitions_count;",
            "extern const latch_def_t g_latches[];",
            "extern const uint32_t g_latches_count;",
            "",
            "#ifdef __cplusplus",
            "}",
            "#endif",
            "",
            "#endif /* ENGINE_CONFIG_TABLE_H */",
        ]
    )
    return "\n".join(lines) + "\n"

def render_source(cfg: Config, tables: GeneratedTables) -> str:
    lines = [
        "/* AUTO-GENERATED FILE -- DO NOT HAND-EDIT.",
        f" * Generated by tools/codegen_c_table.py from config/{cfg.config_id}.yaml",
        " * (Phase 8 Task 2). See engine_config_table.h's header comment to",
        " * regenerate.",
        " */",
        '#include "engine_config_table.h"',
        "",
        "#include <stddef.h>",
        "",
        "const state_def_t g_states[STATE_COUNT] = {",
    ]
    for sid, name in zip(tables.state_ids, tables.state_names):
        lines.append(f"    [STATE_{c_ident(sid)}] = {{ .id = {_c_string(sid)}, .name = {_c_string(name)} }},")
    lines.append("};")
    lines.append("")
    lines.append("const event_def_t g_events[EVENT_COUNT] = {")
    for eid, name, source in zip(tables.event_ids, tables.event_names, tables.event_sources):
        lines.append(
            f"    [EVENT_{c_ident(eid)}] = {{ .id = {_c_string(eid)}, .name = {_c_string(name)}, "
            f".source = {_c_string(source)} }},"
        )
    lines.append("};")
    lines.append("")
    lines.append("const parameter_t g_parameters[] = {")
    for p in tables.parameters:
        lines.append(f"    {{ .id = {_c_string(p.id)}, .value = {_c_double(p.value)} }},")
    lines.append("};")
    lines.append(f"const uint32_t g_parameters_count = {len(tables.parameters)};")
    lines.append("")
    lines.append("const timer_def_t g_timers[] = {")
    for tid in tables.timers:
        lines.append(f"    {{ .id = {_c_string(tid)} }},")
    lines.append("};")
    lines.append(f"const uint32_t g_timers_count = {len(tables.timers)};")
    lines.append("")

    for t in tables.transitions:
        if not t.actions:
            continue
        lines.append(f"static const action_t k_actions_{c_ident(t.id)}[] = {{")
        for a in t.actions:
            lines.append(_render_action(a))
        lines.append("};")
        lines.append("")

    lines.append("const transition_t g_transitions[] = {")
    for t in tables.transitions:
        lines.append("    {")
        lines.append(f"        .id = {_c_string(t.id)},")
        lines.append(f"        .from_wildcard = {_c_bool(t.from_wildcard)},")
        lines.append(f"        .from_mask = {t.from_mask}u,")
        lines.append(f"        .event = EVENT_{c_ident(tables.event_ids[t.event_index])},")
        lines.extend(_render_guard(t.guard, "        "))
        target_kind = {
            "SELF": "TARGET_SELF",
            "STATE": "TARGET_STATE",
            "RELOAD": "TARGET_RELOAD_PERSISTENCE",
        }[t.target_kind]
        lines.append(f"        .target_kind = {target_kind},")
        if t.target_kind == "STATE":
            to_state = f"STATE_{c_ident(tables.state_ids[t.to_state_index])}"
        else:
            to_state = "STATE_COUNT /* unused: target_kind != TARGET_STATE */"
        lines.append(f"        .to_state = {to_state},")
        if t.actions:
            lines.append(f"        .actions = k_actions_{c_ident(t.id)},")
        else:
            lines.append("        .actions = NULL,")
        lines.append(f"        .actions_count = {len(t.actions)},")
        lines.append("    },")
    lines.append("};")
    lines.append(f"const uint32_t g_transitions_count = {len(tables.transitions)};")
    lines.append("")

    for latch in tables.latches:
        if not latch.set_by_indices:
            continue
        lines.append(f"static const uint32_t k_latch_set_by_{c_ident(latch.name)}[] = {{")
        lines.append("    " + ", ".join(str(i) for i in latch.set_by_indices) + ",")
        lines.append("};")
        lines.append("")
    lines.append("const latch_def_t g_latches[] = {")
    for latch in tables.latches:
        set_by = f"k_latch_set_by_{c_ident(latch.name)}" if latch.set_by_indices else "NULL"
        lines.append(
            f"    {{ .name = {_c_string(latch.name)}, .set_by = {set_by}, "
            f".set_by_count = {len(latch.set_by_indices)} }},"
        )
    lines.append("};")
    lines.append(f"const uint32_t g_latches_count = {len(tables.latches)};")
    lines.append("")
    return "\n".join(lines)

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compile a mission config (config/config-*.yaml) into "
            "mcu/firmware/app/src/engine_config_table.c/.h. Exactly one "
            "config is embedded in a given firmware build; re-run this "
            "script against a different config to switch which one."
        )
    )
    parser.add_argument(
        "config_path",
        nargs="?",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"path to a config/*.yaml file (default: {DEFAULT_CONFIG_PATH.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help=f"output directory for engine_config_table.c/.h (default: {DEFAULT_OUT_DIR.relative_to(REPO_ROOT)})",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config_path)
    tables = generate_tables(cfg)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    header_path = out_dir / "engine_config_table.h"
    source_path = out_dir / "engine_config_table.c"
    header_path.write_text(render_header(cfg, tables))
    source_path.write_text(render_source(cfg, tables))
    print(f"wrote {header_path}")
    print(f"wrote {source_path}")
    print(
        f"{cfg.config_id}: {len(tables.transitions)} transitions, "
        f"{len(tables.state_ids)} states, {len(tables.event_ids)} events, "
        f"{len(tables.parameters)} guard-referenced parameters, "
        f"{len(tables.timers)} guard-referenced timers"
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
