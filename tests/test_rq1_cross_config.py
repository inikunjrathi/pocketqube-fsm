# RB-02 RB-10 RB-09 RC-13

from __future__ import annotations

import re
from pathlib import Path

from tests.fixtures.transition_cases import CONFIG_B, CONFIG_C

REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_HARNESS_FILES = (
    REPO_ROOT / "tests" / "test_transition_coverage.py",
    REPO_ROOT / "tests" / "test_fault_injection.py",
    REPO_ROOT / "tests" / "test_latch_fuzz.py",
    REPO_ROOT / "tests" / "fixtures" / "drive.py",
    REPO_ROOT / "tests" / "fixtures" / "transition_cases.py",
    REPO_ROOT / "tests" / "fixtures" / "event_chains.py",
)

_CONFIG_BRANCH_RE = re.compile(r"config_id\s*==|config\.config_id\s*==")

def test_config_b_has_no_autonomous_recovery_event_or_state():
    event_names = {e.name for e in CONFIG_B.events.values()}
    assert "AUTONOMOUS_RECOVERY_CONDITIONS_MET" not in event_names

    state_names = {s.name for s in CONFIG_B.states.values()}
    assert not any("RECOVERY" in name for name in state_names)

    safe_mode_id = next(s.id for s in CONFIG_B.states.values() if s.name == "SAFE_MODE")
    exits_from_safe_mode = [
        t for t in CONFIG_B.transitions
        if t.from_states != "*" and safe_mode_id in t.from_states and t.to != safe_mode_id
    ]
    exit_event_names = {CONFIG_B.events[t.event].name for t in exits_from_safe_mode}
    assert exit_event_names == {"GROUND_OVERRIDE_EXIT_SAFE"}

def test_config_c_has_autonomous_recovery_on_config_b_style_chassis():
    event_names = {e.name for e in CONFIG_C.events.values()}
    assert "AUTONOMOUS_RECOVERY_CONDITIONS_MET" in event_names

    safe_mode_id = next(s.id for s in CONFIG_C.states.values() if s.name == "SAFE_MODE")
    exits_from_safe_mode = [
        t for t in CONFIG_C.transitions
        if t.from_states != "*" and safe_mode_id in t.from_states and t.to != safe_mode_id
    ]
    exit_event_names = {CONFIG_C.events[t.event].name for t in exits_from_safe_mode}
    assert exit_event_names == {"GROUND_OVERRIDE_EXIT_SAFE", "AUTONOMOUS_RECOVERY_CONDITIONS_MET"}

    assert {s.name for s in CONFIG_C.states.values()} == {s.name for s in CONFIG_B.states.values()}
    assert event_names - {"AUTONOMOUS_RECOVERY_CONDITIONS_MET"} == {
        e.name for e in CONFIG_B.events.values()
    }

    autonomous_exit = next(
        t for t in exits_from_safe_mode
        if CONFIG_C.events[t.event].name == "AUTONOMOUS_RECOVERY_CONDITIONS_MET"
    )
    assert CONFIG_C.states[autonomous_exit.to].name == "COMMISSIONING"
    assert autonomous_exit.guard is not None and "battery_soc" in autonomous_exit.guard

def test_shared_harness_files_never_branch_on_config_id():
    for path in SHARED_HARNESS_FILES:
        text = path.read_text()
        assert not _CONFIG_BRANCH_RE.search(text), (
            f"{path.name} contains per-config branching — a genuine "
            "Config-B limitation must be reported as an honest 'no', not "
            "worked around with an if config_id == branch (see "
            "requirements-config-b.md)"
        )
