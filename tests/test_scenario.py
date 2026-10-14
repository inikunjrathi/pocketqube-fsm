from __future__ import annotations

import ast
from pathlib import Path

from sim import scenario

def test_ground_station_coordinates_are_physically_valid():
    assert -90.0 <= scenario.GROUND_STATION_LAT_DEG <= 90.0
    assert -180.0 <= scenario.GROUND_STATION_LON_DEG <= 180.0
    assert scenario.GROUND_STATION_ALT_M >= 0.0

def test_battery_and_draw_constants_are_positive():
    assert scenario.BATTERY_CAPACITY_WH > 0.0
    assert scenario.SOLAR_GEN_W > 0.0
    for draw_w in (
        scenario.DRAW_W_IDLE,
        scenario.DRAW_W_COMMS_TTC,
        scenario.DRAW_W_COMMS_SSTV,
        scenario.DRAW_W_COMMS_VOICE,
    ):
        assert draw_w > 0.0

def test_no_network_access():
    source = Path(scenario.__file__).read_text()
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
        f"sim/scenario.py imports network modules: {imported_modules & banned}"
    )
