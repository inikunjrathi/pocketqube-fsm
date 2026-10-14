from __future__ import annotations

from pathlib import Path

import pytest

from engine.config_loader import ConfigError, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_A = REPO_ROOT / "config" / "config-a.yaml"
CONFIG_B = REPO_ROOT / "config" / "config-b.yaml"
CONFIG_C = REPO_ROOT / "config" / "config-c.yaml"

MINIMAL_VALID = """
meta:
  config_id: minimal
  name: Minimal
  description: ""
  version: "0.0.1"
states:
  - {id: S-01, name: A, is_initial: true}
  - {id: S-02, name: B, is_initial: false}
events:
  - {id: E-01, name: GO, source: onboard}
transitions:
  - {id: T-01, from: [S-01], event: E-01, to: S-02}
conflict_resolution:
  - {rank: 1, category: only, member_events: [E-01]}
"""

def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(text)
    return p

def test_loads_config_a_without_error():
    cfg = load_config(CONFIG_A)
    assert cfg.config_id == "config-a"
    assert cfg.initial_state == "S-01"

def test_loads_config_b_without_error():
    cfg = load_config(CONFIG_B)
    assert cfg.config_id == "config-b"
    assert cfg.initial_state == "S-01"

def test_loads_config_c_without_error():
    cfg = load_config(CONFIG_C)
    assert cfg.config_id == "config-c"
    assert cfg.initial_state == "S-01"
    assert len(cfg.events) == 16
    assert len(cfg.transitions) == 16

def test_config_a_transitions_for_returns_matching_rows():
    cfg = load_config(CONFIG_A)
    rows = cfg.transitions_for("S-01", "E-01")
    assert [t.id for t in rows] == ["T-01"]

def test_minimal_valid_config_loads(tmp_path):
    cfg = load_config(write(tmp_path, MINIMAL_VALID))
    assert cfg.initial_state == "S-01"

def test_zero_initial_states_rejected(tmp_path):
    bad = MINIMAL_VALID.replace("is_initial: true", "is_initial: false")
    with pytest.raises(ConfigError, match="exactly one initial state"):
        load_config(write(tmp_path, bad))

def test_two_initial_states_rejected(tmp_path):
    bad = MINIMAL_VALID.replace(
        "{id: S-02, name: B, is_initial: false}",
        "{id: S-02, name: B, is_initial: true}",
    )
    with pytest.raises(ConfigError, match="exactly one initial state"):
        load_config(write(tmp_path, bad))

def test_duplicate_state_id_rejected(tmp_path):
    bad = MINIMAL_VALID.replace(
        "  - {id: S-02, name: B, is_initial: false}",
        "  - {id: S-01, name: B, is_initial: false}",
    )
    with pytest.raises(ConfigError, match="duplicate state id"):
        load_config(write(tmp_path, bad))

def test_transition_referencing_unknown_state_rejected(tmp_path):
    bad = MINIMAL_VALID.replace(
        "{id: T-01, from: [S-01], event: E-01, to: S-02}",
        "{id: T-01, from: [S-01], event: E-01, to: S-99}",
    )
    with pytest.raises(ConfigError, match="unknown to-state"):
        load_config(write(tmp_path, bad))

def test_transition_referencing_unknown_event_rejected(tmp_path):
    bad = MINIMAL_VALID.replace(
        "{id: T-01, from: [S-01], event: E-01, to: S-02}",
        "{id: T-01, from: [S-01], event: E-99, to: S-02}",
    ).replace(
        "  - {rank: 1, category: only, member_events: [E-01]}",
        "  - {rank: 1, category: only, member_events: [E-01, E-99]}",
    )
    with pytest.raises(ConfigError, match="unknown event"):
        load_config(write(tmp_path, bad))

def test_unreachable_state_rejected(tmp_path):
    bad = MINIMAL_VALID.replace(
        "  - {id: S-02, name: B, is_initial: false}\n",
        "  - {id: S-02, name: B, is_initial: false}\n"
        "  - {id: S-03, name: Orphan, is_initial: false}\n",
    )
    with pytest.raises(ConfigError, match="unreachable states"):
        load_config(write(tmp_path, bad))

def test_event_missing_from_conflict_resolution_rejected(tmp_path):
    bad = MINIMAL_VALID.replace(
        "  - {rank: 1, category: only, member_events: [E-01]}",
        "  - {rank: 1, category: only, member_events: []}",
    )
    with pytest.raises(ConfigError, match="never ranked"):
        load_config(write(tmp_path, bad))

def test_missing_required_top_level_key_rejected(tmp_path):
    bad = MINIMAL_VALID.replace("states:\n  - {id: S-01, name: A, is_initial: true}\n  - {id: S-02, name: B, is_initial: false}\n", "")
    with pytest.raises(ConfigError, match="missing required field 'states'"):
        load_config(write(tmp_path, bad))
