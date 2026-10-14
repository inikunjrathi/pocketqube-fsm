from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.config_loader import Config, load_config  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "tla"
INDEPENDENT_REQUIREMENTS = DEFAULT_OUTPUT_DIR / "independent_requirements.yaml"
CONFIG_IDS = ("config-a", "config-b", "config-c")

_BOOL_GUARD_RE = re.compile(r"^context\.(\w+)\s*(==|!=)\s*(true|false)$")
_SET_BOOL_RE = re.compile(r"^set context\.(\w+) = (true|false)$")

def _tla_id(state_id: str) -> str:
    return state_id.replace("-", "_")

def _expand_from_states(cfg: Config, from_states) -> tuple[str, ...]:
    if from_states == "*":
        return tuple(cfg.states.keys())
    return tuple(from_states)

def _bool_vars(cfg: Config) -> list[str]:
    names = [latch.name for latch in cfg.latches]
    for t in cfg.transitions:
        found = [m.group(1) for a in t.actions if (m := _SET_BOOL_RE.match(a))]
        if t.guard and (m := _BOOL_GUARD_RE.match(t.guard.strip())):
            found.append(m.group(1))
        names += [n for n in found if n not in names]
    return names

def _guard_expr(guard: str | None) -> str | None:
    if guard is None:
        return "TRUE"
    m = _BOOL_GUARD_RE.match(guard.strip())
    if not m:
        return None
    var, op, lit = m.groups()
    return f"({var} {'=' if op == '==' else '#'} {lit.upper()})"

def _set_str(items) -> str:
    return "{" + ", ".join(f'"{i}"' for i in items) + "}"

def _emit_action(cfg: Config, t, earlier, bools: list[str]) -> str:
    from_set = _set_str(_tla_id(s) for s in _expand_from_states(cfg, t.from_states))
    reload = t.to == "reload_from_persistence"
    if t.to is None:
        pc_next = "pc"
    elif reload:
        pc_next = "b_pc"
    else:
        pc_next = f'"{_tla_id(t.to)}"'

    lines = [f"{t.id.replace('-', '_')} ==", f"    /\\ pc \\in {from_set}"]
    g = _guard_expr(t.guard)
    if g not in (None, "TRUE"):
        lines.append(f"    /\\ {g}")
    for e in earlier:
        eg = _guard_expr(e.guard)
        if eg is None:
            continue
        e_from = _set_str(_tla_id(s) for s in _expand_from_states(cfg, e.from_states))
        lines.append(f"    /\\ ~(pc \\in {e_from} /\\ {eg})")

    latch_names = {latch.name for latch in cfg.latches}
    value = {v: (f"b_{v}" if reload else v) for v in bools}
    for action in t.actions:
        m = _SET_BOOL_RE.match(action)
        if not m:
            continue
        var, lit = m.groups()
        if lit == "true":
            value[var] = "TRUE"
        elif var not in latch_names:
            value[var] = "FALSE"
    for latch in cfg.latches:
        if t.id in latch.set_by:
            value[latch.name] = "TRUE"

    lines.append(f"    /\\ pc' = {pc_next}")
    lines += [f"    /\\ {v}' = {value[v]}" for v in bools]
    lines.append(f'    /\\ ev\' = "{cfg.events[t.event].name}"')
    lines.append("    /\\ Persist")
    return "\n".join(lines)

def load_independent_requirements(path: str | Path = INDEPENDENT_REQUIREMENTS) -> dict:
    path = Path(path)
    return yaml.safe_load(path.read_text()) if path.exists() else {}

def _independent_properties(cfg: Config, req: dict) -> tuple[list[str], list[str], list[str]]:
    by_name = {s.name: s.id for s in cfg.states.values()}
    event_names = {e.name for e in cfg.events.values()}

    def states(names):
        missing = [n for n in names if n not in by_name]
        if missing:
            raise ValueError(f"{cfg.config_id}: requirement names unknown states {missing}")
        return _set_str(_tla_id(by_name[n]) for n in names)

    def events(names):
        missing = [n for n in names if n not in event_names]
        if missing:
            raise ValueError(f"{cfg.config_id}: requirement names unknown events {missing}")
        return _set_str(names)

    L = req["latch"]
    safe = f'"{_tla_id(by_name[req["safe_state"]])}"'
    requires = "".join(f" /\\ {f}'" for f in req.get("latch_requires", []))
    defs = [
        f"PostLatchStatesHaveLatch == pc \\notin {states(req['pre_latch_states'])} => {L}",
        f"LatchRisesOnlyVia == [][(~{L} /\\ {L}') => (ev' \\in {events(req['latch_events'])}{requires})]_Vars",
        f"RfSilenceLeftOnlyVia == [][(pc \\in {states(req['rf_silent_states'])} /\\ pc' \\notin "
        f"{states(req['rf_silent_states'])}) => ev' \\in {events(req['rf_enable_events'])}]_Vars",
        f"SafeExitOnlyVia == [][(pc = {safe} /\\ pc' # {safe}) => ev' \\in {events(req['safe_exit_events'])}]_Vars",
        f"SafeEntryOnlyVia == [][(pc # {safe} /\\ pc' = {safe}) => ev' \\in {events(req['safe_entry_events'])}]_Vars",
        f"SchedulerOnlyInComms == [][ev' \\in {events(req['scheduler_events'])} => "
        f"(pc \\in {states(req['comms_states'])} /\\ pc' \\in {states(req['comms_states'])})]_Vars",
        f"GroundSafeAvailableExactly == pc \\in {states(req['ground_safe_from'])} <=> "
        f"ENABLED (Step /\\ ev' = \"{req['ground_safe_event']}\" /\\ pc' = {safe})",
        f"ResetAlwaysAvailable == ENABLED (Step /\\ ev' = \"{req['reset_event']}\")",
    ]
    invariants = ["PostLatchStatesHaveLatch", "GroundSafeAvailableExactly", "ResetAlwaysAvailable"]
    properties = ["LatchRisesOnlyVia", "RfSilenceLeftOnlyVia", "SafeExitOnlyVia",
                  "SafeEntryOnlyVia", "SchedulerOnlyInComms"]
    return defs, invariants, properties

def _properties(cfg: Config, requirements: dict | None):
    latch_vars = [latch.name for latch in cfg.latches]
    defs = []
    for v in latch_vars:
        defs.append(f"{v}NeverClears == [][{v} => {v}']_Vars")
        defs.append(f"{v}DurableNeverClears == [][b_{v} => b_{v}']_Vars")
        defs.append(f"{v}LiveOnceDurable == b_{v} => {v}")
    invariants = ["TypeOK"] + [f"{v}LiveOnceDurable" for v in latch_vars]
    properties = [f"{v}DurableNeverClears" for v in latch_vars]
    req = (requirements or {}).get(cfg.config_id)
    if req:
        d, i, p = _independent_properties(cfg, req)
        defs, invariants, properties = defs + d, invariants + i, properties + p
    return defs, invariants, properties

def generate_tla_module(cfg: Config, requirements: dict | None = None) -> str:
    module_name = cfg.config_id.replace("-", "_")
    states_set = _set_str(_tla_id(s) for s in cfg.states)
    bools = _bool_vars(cfg)
    live = ["pc"] + bools
    bank = [f"b_{v}" for v in live]
    all_vars = live + bank + ["ev"]
    init_pc = f'"{_tla_id(cfg.initial_state)}"'

    lines = [
        f"---- MODULE {module_name} ----",
        f"(* Auto-generated by tools/generate_tla_spec.py from config/{cfg.config_id}.yaml. *)",
        "(* Do not hand-edit. Boolean-context guards exact, other guards *)",
        "(* nondeterministic, b_* = last durable snapshot; see the generator docstring. *)",
        "EXTENDS Naturals, TLC",
        "",
        f"States == {states_set}",
        f"InitState == {init_pc}",
        "",
        f"VARIABLES {', '.join(all_vars)}",
        f"Vars == <<{', '.join(all_vars)}>>",
        "",
        "TypeOK ==",
        "    /\\ pc \\in States /\\ b_pc \\in States",
        *[f"    /\\ {v} \\in BOOLEAN /\\ b_{v} \\in BOOLEAN" for v in bools],
        "",
        "Init ==",
        f"    /\\ pc = InitState /\\ b_pc = InitState",
        *[f"    /\\ {v} = FALSE /\\ b_{v} = FALSE" for v in bools],
        '    /\\ ev = "INIT"',
        "",
        "(* Each legal step either persists its result or leaves the old snapshot. *)",
        "Persist ==",
        "    \\/ " + " /\\ ".join(f"{b}' = {v}'" for b, v in zip(bank, live)),
        f"    \\/ UNCHANGED <<{', '.join(bank)}>>",
        "",
    ]
    for i, t in enumerate(cfg.transitions):
        earlier = [e for e in cfg.transitions[:i] if e.event == t.event]
        lines += [_emit_action(cfg, t, earlier, bools), ""]

    names = [t.id.replace("-", "_") for t in cfg.transitions]
    lines += [
        f"Step == {' \\/ '.join(names)}",
        "Stutter == UNCHANGED Vars",
        "Next == Step \\/ Stutter",
        "Spec == Init /\\ [][Next]_Vars",
        "",
    ]
    defs, _, _ = _properties(cfg, requirements)
    for d in defs:
        lines += [d, ""]
    lines.append("====")
    return "\n".join(lines) + "\n"

def generate_tla_config(cfg: Config, requirements: dict | None = None) -> str:
    _, invariants, properties = _properties(cfg, requirements)
    lines = ["\\* Auto-generated by tools/generate_tla_spec.py. Do not hand-edit.",
             "SPECIFICATION Spec"]
    lines += [f"INVARIANT {i}" for i in invariants]
    lines += [f"PROPERTY {p}" for p in properties]
    return "\n".join(lines) + "\n"

def write_tla_spec(
    cfg: Config, output_dir: str | Path = DEFAULT_OUTPUT_DIR, requirements: dict | None = None
) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    module_name = cfg.config_id.replace("-", "_")
    tla_path = output_dir / f"{module_name}.tla"
    cfg_path = output_dir / f"{module_name}.cfg"
    tla_path.write_text(generate_tla_module(cfg, requirements))
    cfg_path.write_text(generate_tla_config(cfg, requirements))
    return tla_path, cfg_path

def main() -> None:
    requirements = load_independent_requirements()
    for config_id in CONFIG_IDS:
        cfg = load_config(REPO_ROOT / "config" / f"{config_id}.yaml")
        for path in write_tla_spec(cfg, requirements=requirements):
            print(f"wrote {path}")

if __name__ == "__main__":
    main()
