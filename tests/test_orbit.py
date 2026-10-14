from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sim.orbit import Pass, elevation_deg, find_passes, load_satellite, propagate
from sim.scenario import (
    GROUND_STATION_ALT_M,
    GROUND_STATION_LAT_DEG,
    GROUND_STATION_LON_DEG,
    GROUND_STATIONS_DUAL,
)

TLE_EPOCH = datetime(2025, 1, 21, 21, 45, 38, 676096, tzinfo=timezone.utc)

def test_reference_tle_is_valid_leo():
    sat = load_satellite()
    x, y, z = propagate(sat, TLE_EPOCH)
    radius_km = (x**2 + y**2 + z**2) ** 0.5
    assert 6800.0 <= radius_km <= 7000.0

def test_propagate_is_deterministic():
    sat = load_satellite()
    when = TLE_EPOCH + timedelta(minutes=37)
    r1 = propagate(sat, when)
    r2 = propagate(sat, when)
    assert r1 == r2

def test_elevation_at_subsatellite_point_is_near_90():
    sat = load_satellite()
    best = -90.0
    t = TLE_EPOCH + timedelta(hours=8, minutes=15)
    end = TLE_EPOCH + timedelta(hours=8, minutes=35)
    step = timedelta(seconds=1)
    while t <= end:
        el = elevation_deg(
            sat, t, GROUND_STATION_LAT_DEG, GROUND_STATION_LON_DEG, GROUND_STATION_ALT_M
        )
        best = max(best, el)
        t += step
    assert best > 80.0

def test_find_passes_returns_sane_passes_over_one_day():
    sat = load_satellite()
    passes = find_passes(
        sat,
        start=TLE_EPOCH,
        end=TLE_EPOCH + timedelta(hours=24),
        min_elevation_deg=10.0,
    )

    assert len(passes) > 1
    for p in passes:
        assert isinstance(p, Pass)
        assert p.aos < p.los
        assert p.max_elevation_deg >= 10.0
        duration_min = (p.los - p.aos).total_seconds() / 60.0
        assert duration_min < 15.0

def test_find_passes_default_stations_matches_single_station_call():
    sat = load_satellite()
    start = TLE_EPOCH
    end = TLE_EPOCH + timedelta(hours=24)

    default_passes = find_passes(sat, start=start, end=end, min_elevation_deg=10.0)
    explicit_single = find_passes(
        sat,
        start=start,
        end=end,
        min_elevation_deg=10.0,
        stations=((GROUND_STATION_LAT_DEG, GROUND_STATION_LON_DEG, GROUND_STATION_ALT_M),),
    )

    assert default_passes == explicit_single

def test_find_passes_with_second_station_has_at_least_as_much_contact():
    sat = load_satellite()
    start = TLE_EPOCH
    end = TLE_EPOCH + timedelta(hours=24)

    single = find_passes(sat, start=start, end=end, min_elevation_deg=10.0)
    dual = find_passes(
        sat, start=start, end=end, min_elevation_deg=10.0, stations=GROUND_STATIONS_DUAL
    )

    single_contact_s = sum((p.los - p.aos).total_seconds() for p in single)
    dual_contact_s = sum((p.los - p.aos).total_seconds() for p in dual)

    assert dual_contact_s >= single_contact_s
    assert dual_contact_s > single_contact_s

def test_no_network_access():
    import sim.orbit as orbit_module

    source = Path(orbit_module.__file__).read_text()
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
        f"sim/orbit.py imports network modules: {imported_modules & banned}"
    )
