from __future__ import annotations

import ast
from pathlib import Path

import pytest

from engine.config_loader import load_config
from sim.event_mapping import (
    EventMappingError,
    build_event_map,
    resolve,
    scheduler_select_event_names,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_A = REPO_ROOT / "config" / "config-a.yaml"
CONFIG_B = REPO_ROOT / "config" / "config-b.yaml"

COMMON_EVENT_NAMES = (
    "RESET",
    "FAULT_DETECTED",
    "WATCHDOG_TIMEOUT",
    "GROUND_SAFE_MODE_CMD",
)

def test_config_a_resolves_per_class_events():
    cfg_a = load_config(CONFIG_A)
    event_map = build_event_map(cfg_a)

    names = scheduler_select_event_names(event_map, "TTC")

    assert names == ["SCHEDULER_SELECT_TTC"]
    assert names[0] in event_map.by_name
    assert resolve(event_map, names[0]) == event_map.by_name["SCHEDULER_SELECT_TTC"]

def test_config_b_resolves_collapsed_events():
    cfg_b = load_config(CONFIG_B)
    event_map = build_event_map(cfg_b)

    names = scheduler_select_event_names(event_map, "TTC")

    assert names == ["SCHEDULER_SELECT_ACTIVE"]
    assert names[0] in event_map.by_name
    assert resolve(event_map, names[0]) == event_map.by_name["SCHEDULER_SELECT_ACTIVE"]

    assert "SCHEDULER_SELECT_TTC" not in event_map.by_name

def test_no_config_id_branching():
    import sim.event_mapping as event_mapping_module

    source = Path(event_mapping_module.__file__).read_text()
    tree = ast.parse(source)

    def references_config_id(node: ast.expr) -> bool:
        return (isinstance(node, ast.Attribute) and node.attr == "config_id") or (
            isinstance(node, ast.Name) and node.id == "config_id"
        )

    offending: list[ast.Compare] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            sides = [node.left, *node.comparators]
            if any(references_config_id(side) for side in sides):
                offending.append(node)

    assert not offending, (
        "sim/event_mapping.py contains config_id branching -- Config B's "
        "collapsed events must be handled by probing event_map.by_name, "
        "never by checking cfg.config_id (see Global Constraints)"
    )

def test_resolve_missing_event_raises_named_error():
    cfg_a = load_config(CONFIG_A)
    event_map = build_event_map(cfg_a)

    with pytest.raises(EventMappingError) as exc_info:
        resolve(event_map, "NOT_A_REAL_EVENT")

    assert "NOT_A_REAL_EVENT" in str(exc_info.value)
    assert isinstance(exc_info.value, KeyError)

def test_common_events_resolve_in_both_configs():
    for config_path in (CONFIG_A, CONFIG_B):
        cfg = load_config(config_path)
        event_map = build_event_map(cfg)
        for name in COMMON_EVENT_NAMES:
            assert name in event_map.by_name
            resolved_id = resolve(event_map, name)
            assert resolved_id == event_map.by_name[name]

def test_all_real_data_classes_resolve_in_both_configs():
    for config_path in (CONFIG_A, CONFIG_B):
        cfg = load_config(config_path)
        event_map = build_event_map(cfg)
        priority_order = list(cfg.data_class_priority)
        assert "CODEC2_M17" in priority_order

        for data_class in priority_order:
            names = scheduler_select_event_names(event_map, data_class)
            assert names, (
                f"{config_path.name}: no scheduler-select event resolved "
                f"for real data class {data_class!r}"
            )
            for name in names:
                assert name in event_map.by_name

    cfg_a = load_config(CONFIG_A)
    event_map_a = build_event_map(cfg_a)
    assert scheduler_select_event_names(event_map_a, "CODEC2_M17") == [
        "SCHEDULER_SELECT_VOICE"
    ]

def test_no_network_access():
    import sim.event_mapping as event_mapping_module

    source = Path(event_mapping_module.__file__).read_text()
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
        f"sim/event_mapping.py imports network modules: {imported_modules & banned}"
    )
