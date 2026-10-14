from __future__ import annotations

import ast
from pathlib import Path

from engine.config_loader import load_config
from sim.link import LinkState, link_state

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_A = REPO_ROOT / "config" / "config-a.yaml"
CONFIG_B = REPO_ROOT / "config" / "config-b.yaml"

def test_link_down_below_min_elevation():
    state = link_state(elevation_deg=5.0, min_elevation_deg=10.0, fade_margin_db=3.0)
    assert isinstance(state, LinkState)
    assert state.is_up is False

def test_link_up_at_or_above_min_elevation():
    at_min = link_state(elevation_deg=10.0, min_elevation_deg=10.0, fade_margin_db=3.0)
    above_min = link_state(elevation_deg=45.0, min_elevation_deg=10.0, fade_margin_db=3.0)
    assert at_min.is_up is True
    assert above_min.is_up is True

def test_margin_increases_with_elevation():
    low = link_state(elevation_deg=15.0, min_elevation_deg=10.0, fade_margin_db=3.0)
    high = link_state(elevation_deg=60.0, min_elevation_deg=10.0, fade_margin_db=3.0)
    assert high.margin_db > low.margin_db

def test_uses_real_config_parameters():
    cfg_a = load_config(CONFIG_A)
    cfg_b = load_config(CONFIG_B)

    min_elev_a = cfg_a.param_value("P-015")
    fade_margin_a = cfg_a.param_value("P-016")
    min_elev_b = cfg_b.param_value("PB-006")
    fade_margin_b = cfg_b.param_value("PB-007")

    representative_elevation = 45.0

    state_a = link_state(representative_elevation, min_elev_a, fade_margin_a)
    state_b = link_state(representative_elevation, min_elev_b, fade_margin_b)

    assert isinstance(state_a, LinkState)
    assert isinstance(state_b, LinkState)
    assert state_a.is_up is True
    assert state_b.is_up is True

def test_margin_matches_real_calibration_point():
    state = link_state(elevation_deg=15.0, min_elevation_deg=10.0, fade_margin_db=3.0)
    assert state.margin_db == 10.0

def test_margin_at_min_elevation_is_positive():
    state = link_state(elevation_deg=10.0, min_elevation_deg=10.0, fade_margin_db=3.0)
    assert state.margin_db == 7.5

def test_margin_at_zenith():
    state = link_state(elevation_deg=90.0, min_elevation_deg=10.0, fade_margin_db=3.0)
    assert state.margin_db == 47.5

def test_meets_fade_margin_true_at_configured_floor():
    state = link_state(elevation_deg=10.0, min_elevation_deg=10.0, fade_margin_db=3.0)
    assert state.meets_fade_margin is True

def test_meets_fade_margin_false_below_floor():
    state = link_state(elevation_deg=0.5, min_elevation_deg=0.0, fade_margin_db=3.0)
    assert state.is_up is True
    assert state.meets_fade_margin is False

def test_no_network_access():
    import sim.link as link_module

    source = Path(link_module.__file__).read_text()
    tree = ast.parse(source)

    banned = {"requests", "urllib", "socket"}
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module.split(".")[0])

    assert not (imported_modules & banned), (
        f"sim/link.py imports network modules: {imported_modules & banned}"
    )
