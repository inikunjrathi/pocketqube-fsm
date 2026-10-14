from __future__ import annotations

import ast
from pathlib import Path

from engine.config_loader import load_config
from engine.scheduler import Item
from sim.data_arrival import (
    DEFAULT_RATE_PER_CLASS_PER_HOUR,
    TTC_ARRIVAL_RATE_PER_HOUR,
    generate_arrivals,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_A = REPO_ROOT / "config" / "config-a.yaml"

PRIORITY = ["TTC", "SSTV", "CODEC2_M17"]

def test_same_seed_is_deterministic():
    first = generate_arrivals(PRIORITY, duration_s=7200.0, seed=42)
    second = generate_arrivals(PRIORITY, duration_s=7200.0, seed=42)
    assert first == second
    assert len(first) > 0

def test_different_seeds_differ():
    first = generate_arrivals(PRIORITY, duration_s=7200.0, seed=1)
    second = generate_arrivals(PRIORITY, duration_s=7200.0, seed=2)
    assert first != second

def test_all_items_use_configured_classes():
    cfg_a = load_config(CONFIG_A)
    priority_order = list(cfg_a.data_class_priority)

    arrivals = generate_arrivals(priority_order, duration_s=36000.0, seed=7)
    assert len(arrivals) > 0
    for _, item in arrivals:
        assert isinstance(item, Item)
        assert item.data_class in priority_order

def test_sizes_and_deadlines_are_positive_and_ordered():
    arrivals = generate_arrivals(PRIORITY, duration_s=36000.0, seed=99)
    assert len(arrivals) > 0
    for arrival_time_s, item in arrivals:
        assert item.size_bytes > 0
        assert item.deadline is not None
        assert item.deadline > arrival_time_s

    times = [t for t, _ in arrivals]
    assert times == sorted(times)

def test_arrival_rate_within_tolerance():
    duration_s = 360000.0
    duration_hours = duration_s / 3600.0
    seed = 12345

    rate_per_class_per_hour = {cls: DEFAULT_RATE_PER_CLASS_PER_HOUR for cls in PRIORITY}
    arrivals = generate_arrivals(
        PRIORITY,
        duration_s=duration_s,
        seed=seed,
        rate_per_class_per_hour=rate_per_class_per_hour,
    )

    target_class = "TTC"
    expected_count = rate_per_class_per_hour[target_class] * duration_hours
    actual_count = sum(1 for _, item in arrivals if item.data_class == target_class)

    tolerance = 0.30
    assert actual_count >= expected_count * (1 - tolerance)
    assert actual_count <= expected_count * (1 + tolerance)

def test_ttc_default_rate_reflects_real_beacon_cadence_when_omitted():
    duration_s = 360000.0
    duration_hours = duration_s / 3600.0
    seed = 54321

    arrivals = generate_arrivals(PRIORITY, duration_s=duration_s, seed=seed)

    tolerance = 0.30

    ttc_expected = TTC_ARRIVAL_RATE_PER_HOUR * duration_hours
    ttc_actual = sum(1 for _, item in arrivals if item.data_class == "TTC")
    assert ttc_actual >= ttc_expected * (1 - tolerance)
    assert ttc_actual <= ttc_expected * (1 + tolerance)

    for other_class in ("SSTV", "CODEC2_M17"):
        expected = DEFAULT_RATE_PER_CLASS_PER_HOUR * duration_hours
        actual = sum(1 for _, item in arrivals if item.data_class == other_class)
        assert actual >= expected * (1 - tolerance)
        assert actual <= expected * (1 + tolerance)

def test_no_network_access():
    import sim.data_arrival as data_arrival_module

    source = Path(data_arrival_module.__file__).read_text()
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
        f"sim/data_arrival.py imports network modules: {imported_modules & banned}"
    )
