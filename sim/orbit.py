from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sgp4.api import Satrec, jday

from sim.scenario import (
    EARTH_RADIUS_KM,
    GROUND_STATION_ALT_M,
    GROUND_STATION_LAT_DEG,
    GROUND_STATION_LON_DEG,
    REFERENCE_TLE_LINE1,
    REFERENCE_TLE_LINE2,
)

def load_satellite() -> Satrec:
    return Satrec.twoline2rv(REFERENCE_TLE_LINE1, REFERENCE_TLE_LINE2)

def propagate(sat: Satrec, when: datetime) -> tuple[float, float, float]:
    jd, fr = _jday_of(when)
    return _propagate_jd(sat, when, jd, fr)

def _propagate_jd(
    sat: Satrec, when: datetime, jd: float, fr: float
) -> tuple[float, float, float]:
    error_code, r, _v = sat.sgp4(jd, fr)
    if error_code != 0:
        raise ValueError(f"sgp4 propagation error {error_code} at {when!r}")
    return r

def elevation_deg(
    sat: Satrec, when: datetime, lat_deg: float, lon_deg: float, alt_m: float
) -> float:
    jd, fr = _jday_of(when)
    r_eci = _propagate_jd(sat, when, jd, fr)
    r_ecef = _eci_to_ecef(r_eci, jd, fr)

    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    station_radius_km = EARTH_RADIUS_KM + alt_m / 1000.0
    station_ecef = (
        station_radius_km * math.cos(lat) * math.cos(lon),
        station_radius_km * math.cos(lat) * math.sin(lon),
        station_radius_km * math.sin(lat),
    )

    dx = r_ecef[0] - station_ecef[0]
    dy = r_ecef[1] - station_ecef[1]
    dz = r_ecef[2] - station_ecef[2]
    range_km = math.sqrt(dx * dx + dy * dy + dz * dz)

    up_x = math.cos(lat) * math.cos(lon)
    up_y = math.cos(lat) * math.sin(lon)
    up_z = math.sin(lat)
    up_component = dx * up_x + dy * up_y + dz * up_z

    return math.degrees(math.asin(up_component / range_km))

@dataclass(frozen=True)
class Pass:
    aos: datetime
    los: datetime
    max_elevation_deg: float

def find_passes(
    sat: Satrec,
    start: datetime,
    end: datetime,
    min_elevation_deg: float,
    step_s: float = 10.0,
    stations: Sequence[tuple[float, float, float]] | None = None,
) -> list[Pass]:
    if stations is None:
        stations = ((GROUND_STATION_LAT_DEG, GROUND_STATION_LON_DEG, GROUND_STATION_ALT_M),)

    passes: list[Pass] = []
    step = timedelta(seconds=step_s)

    in_pass = False
    aos: datetime | None = None
    los: datetime | None = None
    max_elevation = float("-inf")

    t = start
    while t <= end:
        el = max(elevation_deg(sat, t, lat, lon, alt) for lat, lon, alt in stations)
        if el >= min_elevation_deg:
            if not in_pass:
                in_pass = True
                aos = t
                max_elevation = el
            else:
                max_elevation = max(max_elevation, el)
            los = t
        else:
            if in_pass:
                if aos is None or los is None:
                    raise RuntimeError("in_pass=True without aos/los set")
                passes.append(Pass(aos=aos, los=los, max_elevation_deg=max_elevation))
                in_pass = False
                max_elevation = float("-inf")
        t += step

    if in_pass:
        if aos is None or los is None:
            raise RuntimeError("in_pass=True without aos/los set")
        passes.append(Pass(aos=aos, los=los, max_elevation_deg=max_elevation))

    return passes

def _jday_of(when: datetime) -> tuple[float, float]:
    return jday(
        when.year,
        when.month,
        when.day,
        when.hour,
        when.minute,
        when.second + when.microsecond / 1e6,
    )

def _gmst_rad(jd: float, fr: float) -> float:
    jd_full = jd + fr
    centuries = (jd_full - 2451545.0) / 36525.0
    gmst_deg = (
        280.46061837
        + 360.98564736629 * (jd_full - 2451545.0)
        + 0.000387933 * centuries * centuries
        - (centuries**3) / 38710000.0
    )
    gmst_deg %= 360.0
    return math.radians(gmst_deg)

def _eci_to_ecef(
    r_eci: tuple[float, float, float], jd: float, fr: float
) -> tuple[float, float, float]:
    theta = _gmst_rad(jd, fr)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    x, y, z = r_eci
    return (
        cos_t * x + sin_t * y,
        -sin_t * x + cos_t * y,
        z,
    )
