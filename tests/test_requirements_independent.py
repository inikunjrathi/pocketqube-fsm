from __future__ import annotations

import itertools
from collections import deque
from pathlib import Path

import pytest
import yaml

from engine.config_loader import Config, load_config
from engine.fsm import step

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = yaml.safe_load(
    (REPO_ROOT / "docs" / "tla" / "independent_requirements.yaml").read_text()
)
CONFIG_IDS = ("config-a", "config-b", "config-c")
_LONG_AGO = 10**7
_TELEMETRY = [
    {"elevation": e, "battery_soc": b, "fault_count": f}
    for e, b, f in itertools.product((-90, 90), (0, 100), (0, 99))
]

def _norm(context: dict) -> frozenset:
    return frozenset(
        (k, 0 if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
        for k, v in context.items()
    )

def _variants(cfg: Config, event: str):
    guarded = any(t.guard for t in cfg.transitions if t.event == event)
    if not guarded:
        return [({}, 0)]
    return [(tel, now) for tel in _TELEMETRY for now in (0, _LONG_AGO)]

def explore(cfg: Config):
    init = ((cfg.initial_state, frozenset()), None)
    seen, queue, edges = {init}, deque([init]), []
    while queue:
        node = queue.popleft()
        (state, ctx), bank = node
        persisted = None if bank is None else {"state": bank[0], "context": dict(bank[1])}
        for event in cfg.events:
            results = set()
            for tel, now in _variants(cfg, event):
                r = step(cfg, state, event, dict(ctx), telemetry=tel, now=now, persisted=persisted)
                if r.legal:
                    results.add((r.new_state, _norm(r.context), r.transition_id))
            for new_state, new_ctx, tid in results:
                live = (new_state, new_ctx)
                for new_bank in (live, bank):
                    dst = (live, new_bank)
                    edges.append((node, cfg.events[event].name, dst, tid))
                    if dst not in seen:
                        seen.add(dst)
                        queue.append(dst)
    return seen, edges

_EXPLORED = {}

def _explored(config_id: str):
    if config_id not in _EXPLORED:
        cfg = load_config(REPO_ROOT / "config" / f"{config_id}.yaml")
        _EXPLORED[config_id] = (cfg, *explore(cfg))
    return _EXPLORED[config_id]

def _flag(ctx: frozenset, name: str) -> bool:
    return dict(ctx).get(name, False) is True

def check(cfg: Config, nodes, edges, req: dict) -> dict[str, list]:
    name = {s.id: s.name for s in cfg.states.values()}
    L = req["latch"]
    bad: dict[str, list] = {k: [] for k in (
        "PostLatchStatesHaveLatch", "LatchRisesOnlyVia", "RfSilenceLeftOnlyVia",
        "SafeExitOnlyVia", "SafeEntryOnlyVia", "SchedulerOnlyInComms",
        "GroundSafeAvailableExactly", "ResetAlwaysAvailable", "LiveOnceDurable",
        "DurableNeverClears",
    )}
    for (live, bank) in nodes:
        if name[live[0]] not in req["pre_latch_states"] and not _flag(live[1], L):
            bad["PostLatchStatesHaveLatch"].append(live)
        if bank is not None and _flag(bank[1], L) and not _flag(live[1], L):
            bad["LiveOnceDurable"].append((live, bank))

    ground_reaches_safe, reset_from = set(), set()
    for src, ev, dst, tid in edges:
        s, d = name[src[0][0]], name[dst[0][0]]
        was, now_ = _flag(src[0][1], L), _flag(dst[0][1], L)
        if not was and now_ and not (
            ev in req["latch_events"] and all(_flag(dst[0][1], f) for f in req["latch_requires"])
        ):
            bad["LatchRisesOnlyVia"].append((s, ev, d))
        silent = req["rf_silent_states"]
        if s in silent and d not in silent and ev not in req["rf_enable_events"]:
            bad["RfSilenceLeftOnlyVia"].append((s, ev, d))
        safe = req["safe_state"]
        if s == safe and d != safe and ev not in req["safe_exit_events"]:
            bad["SafeExitOnlyVia"].append((s, ev, d))
        if s != safe and d == safe and ev not in req["safe_entry_events"]:
            bad["SafeEntryOnlyVia"].append((s, ev, d))
        if ev in req["scheduler_events"] and not (s in req["comms_states"] and d in req["comms_states"]):
            bad["SchedulerOnlyInComms"].append((s, ev, d))
        if ev == req["ground_safe_event"] and d == safe:
            ground_reaches_safe.add(s)
        if ev == req["reset_event"]:
            reset_from.add(src)
        if src[1] is not None and _flag(src[1][1], L) and not (dst[1] and _flag(dst[1][1], L)):
            bad["DurableNeverClears"].append((s, ev, d))

    reached_states = {name[live[0]] for live, _ in nodes}
    expected = set(req["ground_safe_from"]) & reached_states
    if ground_reaches_safe != expected:
        bad["GroundSafeAvailableExactly"].append(sorted(ground_reaches_safe ^ expected))
    bad["ResetAlwaysAvailable"] = [n for n in nodes if n not in reset_from]
    return bad

KNOWN_VIOLATIONS: set[tuple[str, str]] = set()

PROPERTIES = (
    "PostLatchStatesHaveLatch", "LatchRisesOnlyVia", "RfSilenceLeftOnlyVia",
    "SafeExitOnlyVia", "SafeEntryOnlyVia", "SchedulerOnlyInComms",
    "GroundSafeAvailableExactly", "ResetAlwaysAvailable", "LiveOnceDurable",
    "DurableNeverClears",
)

def _param(config_id, prop):
    marks = []
    if (config_id, prop) in KNOWN_VIOLATIONS:
        marks.append(pytest.mark.xfail(strict=True, reason="known config defect, see module comment"))
    return pytest.param(config_id, prop, id=f"{config_id}:{prop}", marks=marks)

@pytest.mark.parametrize(
    "config_id,prop", [_param(c, p) for c in CONFIG_IDS for p in PROPERTIES]
)
def test_engine_satisfies_independent_requirement(config_id, prop):
    cfg, nodes, edges = _explored(config_id)
    violations = check(cfg, nodes, edges, REQUIREMENTS[config_id])[prop]
    assert violations == [], violations[:3]

@pytest.mark.parametrize("config_id", CONFIG_IDS)
def test_exploration_exercises_every_transition_row(config_id):
    cfg, _, edges = _explored(config_id)
    fired = {tid for *_, tid in edges}
    assert fired == {t.id for t in cfg.transitions}

def test_config_a_safe_mode_before_latch_returns_to_confirmation_not_commissioning():
    cfg = load_config(REPO_ROOT / "config" / "config-a.yaml")
    by_name = {e.name: e.id for e in cfg.events.values()}
    for exit_event in ("AUTONOMOUS_RECOVERY_CONDITIONS_MET", "GROUND_OVERRIDE_EXIT_SAFE"):
        state, ctx = cfg.initial_state, {}
        for ev, now in (("SEPARATION_DETECTED", 0), ("RF_INHIBIT_TIMER_EXPIRED", 900),
                        ("DEPLOY_CONFIRM_PATH_A", 901), ("GROUND_SAFE_MODE_CMD", 902), (exit_event, 903)):
            r = step(cfg, state, by_name[ev], ctx, now=now)
            assert r.legal
            state, ctx = r.new_state, r.context
        assert cfg.states[state].name == "DEPLOY_CONFIRM_PENDING"
        assert ctx.get("deployment_confirmed", False) is False
        assert ctx["path_a_confirmed"] is True
        r = step(cfg, state, by_name["DEPLOY_CONFIRM_PATH_B"], ctx, now=904)
        assert cfg.states[r.new_state].name == "DEPLOYED_CONFIRMED"
        assert r.context["deployment_confirmed"] is True
