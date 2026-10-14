from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from engine.config_loader import Config, TransitionDef, load_config

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_A = load_config(REPO_ROOT / "config" / "config-a.yaml")
CONFIG_B = load_config(REPO_ROOT / "config" / "config-b.yaml")
CONFIG_C = load_config(REPO_ROOT / "config" / "config-c.yaml")
ALL_CONFIGS = (CONFIG_A, CONFIG_B, CONFIG_C)

class FixtureMissingError(Exception):
    pass

@dataclass(frozen=True)
class TransitionFixture:
    context: dict
    telemetry: dict
    now: float

@dataclass(frozen=True)
class LegalCase:
    config: Config
    transition: TransitionDef
    origin_state: str
    fixture: TransitionFixture

FIXTURES: dict[tuple[str, str], TransitionFixture] = {
    ("config-a", "T-01"): TransitionFixture({}, {}, 0),
    ("config-a", "T-02"): TransitionFixture({"rf_inhibit_timer": 0}, {}, 900),
    ("config-a", "T-03"): TransitionFixture({"path_b_confirmed": False}, {}, 0),
    ("config-a", "T-04"): TransitionFixture({"path_b_confirmed": True}, {}, 0),
    ("config-a", "T-05"): TransitionFixture({"path_a_confirmed": False}, {}, 0),
    ("config-a", "T-06"): TransitionFixture({"path_a_confirmed": True}, {}, 0),
    ("config-a", "T-07"): TransitionFixture({}, {}, 0),
    ("config-a", "T-08"): TransitionFixture({}, {}, 0),
    ("config-a", "T-09"): TransitionFixture({}, {}, 0),
    ("config-a", "T-10"): TransitionFixture({}, {}, 0),
    ("config-a", "T-11"): TransitionFixture({}, {}, 0),
    ("config-a", "T-12"): TransitionFixture({}, {}, 0),
    ("config-a", "T-13"): TransitionFixture({}, {"elevation": 5}, 0),
    ("config-a", "T-14"): TransitionFixture({}, {"fault_count": 3}, 0),
    ("config-a", "T-15"): TransitionFixture({}, {"battery_soc": 20}, 0),
    ("config-a", "T-16"): TransitionFixture({}, {}, 0),
    ("config-a", "T-17"): TransitionFixture({}, {}, 0),
    ("config-a", "T-18"): TransitionFixture({"deployment_confirmed": True}, {}, 0),
    ("config-a", "T-21"): TransitionFixture({"deployment_confirmed": True}, {}, 0),
    ("config-a", "T-25"): TransitionFixture({}, {}, 0),
    ("config-a", "T-26"): TransitionFixture({}, {}, 0),
    ("config-a", "T-22"): TransitionFixture({}, {}, 0),
    ("config-a", "T-23"): TransitionFixture({}, {}, 0),
    ("config-a", "T-24"): TransitionFixture({"ground_contact_timer": 0}, {}, 172800),
    ("config-b", "T-01"): TransitionFixture({}, {}, 0),
    ("config-b", "T-02"): TransitionFixture({"switch_debounce_timer": 0}, {}, 5),
    ("config-b", "T-03"): TransitionFixture({}, {}, 0),
    ("config-b", "T-04"): TransitionFixture({}, {}, 0),
    ("config-b", "T-05"): TransitionFixture({}, {}, 0),
    ("config-b", "T-06"): TransitionFixture({}, {}, 0),
    ("config-b", "T-07"): TransitionFixture({}, {"elevation": 5}, 0),
    ("config-b", "T-08"): TransitionFixture({}, {"fault_count": 3}, 0),
    ("config-b", "T-09"): TransitionFixture({}, {"battery_soc": 20}, 0),
    ("config-b", "T-10"): TransitionFixture({}, {}, 0),
    ("config-b", "T-11"): TransitionFixture({}, {}, 0),
    ("config-b", "T-12"): TransitionFixture({}, {}, 0),
    ("config-b", "T-13"): TransitionFixture({}, {}, 0),
    ("config-b", "T-14"): TransitionFixture({}, {}, 0),
    ("config-b", "T-15"): TransitionFixture({"ground_contact_timer": 0}, {}, 172800),
    ("config-c", "T-01"): TransitionFixture({}, {}, 0),
    ("config-c", "T-02"): TransitionFixture({"switch_debounce_timer": 0}, {}, 5),
    ("config-c", "T-03"): TransitionFixture({}, {}, 0),
    ("config-c", "T-04"): TransitionFixture({}, {}, 0),
    ("config-c", "T-05"): TransitionFixture({}, {}, 0),
    ("config-c", "T-06"): TransitionFixture({}, {}, 0),
    ("config-c", "T-07"): TransitionFixture({}, {"elevation": 5}, 0),
    ("config-c", "T-08"): TransitionFixture({}, {"fault_count": 3}, 0),
    ("config-c", "T-09"): TransitionFixture({}, {"battery_soc": 20}, 0),
    ("config-c", "T-10"): TransitionFixture({}, {}, 0),
    ("config-c", "T-11"): TransitionFixture({}, {}, 0),
    ("config-c", "T-12"): TransitionFixture({}, {}, 0),
    ("config-c", "T-13"): TransitionFixture({}, {}, 0),
    ("config-c", "T-14"): TransitionFixture({}, {}, 0),
    ("config-c", "T-15"): TransitionFixture({"ground_contact_timer": 0}, {}, 172800),
    ("config-c", "T-16"): TransitionFixture({}, {"battery_soc": 35}, 0),
}

def fixture_for(cfg: Config, transition: TransitionDef) -> TransitionFixture:
    key = (cfg.config_id, transition.id)
    try:
        return FIXTURES[key]
    except KeyError:
        raise FixtureMissingError(
            f"no FIXTURES entry for {cfg.config_id}:{transition.id} — "
            "add one to tests/fixtures/transition_cases.py"
        ) from None

def legal_cases(cfg: Config) -> list[LegalCase]:
    # RB-05 RB-07 RB-08
    all_state_ids = sorted(cfg.states)
    cases = []
    for t in cfg.transitions:
        origins = all_state_ids if t.from_states == "*" else t.from_states
        fixture = fixture_for(cfg, t)
        for origin in origins:
            cases.append(LegalCase(config=cfg, transition=t, origin_state=origin, fixture=fixture))
    return cases

def illegal_pairs(cfg: Config) -> list[tuple[Config, str, str]]:
    pairs = []
    for state_id in sorted(cfg.states):
        for event_id in sorted(cfg.events):
            if not cfg.transitions_for(state_id, event_id):
                pairs.append((cfg, state_id, event_id))
    return pairs
