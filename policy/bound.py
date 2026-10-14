from __future__ import annotations

import bisect
import heapq
import math
from collections import deque
from dataclasses import dataclass

from engine.config_loader import Config
from sim.data_arrival import generate_arrivals
from sim.orbit import elevation_deg, load_satellite
from sim.scenario import (
    GROUND_STATION_ALT_M,
    GROUND_STATION_LAT_DEG,
    GROUND_STATION_LON_DEG,
    LINK_DATA_RATE_BPS,
)

@dataclass(frozen=True)
class ScenarioBound:
    n_generated: int
    n_reachable_window: int
    n_reachable_deadline: int
    window_bound: int
    deadline_bound: int

def _up_tick_times(cfg: Config, duration_s, dt_s, ground_stations) -> list[float]:
    from sim.driver import _epoch_datetime
    from datetime import timedelta

    params = {p.name: p.value for p in cfg.parameters.values()}
    mask = float(params["link_quality_min_elevation_deg"])
    sat = load_satellite()
    start = _epoch_datetime(sat)
    times = []
    for i in range(int(duration_s // dt_s) + 1):
        t = i * dt_s
        when = start + timedelta(seconds=t)
        if max(elevation_deg(sat, when, *gs) for gs in ground_stations) >= mask:
            times.append(t)
    return times

def moore_hodgson(jobs: list[tuple[float, int]]) -> int:
    heap: list[int] = []
    load = 0
    for deadline, size in sorted(jobs):
        heapq.heappush(heap, -size)
        load += size
        if load > deadline:
            load += heapq.heappop(heap)
    return len(heap)

def fluid_completions(jobs: list[tuple[int, int, int]], n_slots: int, slot_cap: int) -> float:
    free = [slot_cap] * n_slots
    flow: list[dict[int, int]] = [{} for _ in range(n_slots)]
    total = 0.0
    for j in sorted(range(len(jobs)), key=lambda j: jobs[j][2]):
        lo, hi, need = jobs[j]
        if lo >= hi or need <= 0:
            continue
        got = 0
        for s in range(lo, hi):
            if free[s]:
                take = min(free[s], need - got)
                free[s] -= take
                flow[s][j] = flow[s].get(j, 0) + take
                got += take
                if got == need:
                    break
        while got < need:
            delta = _augment(j, jobs, free, flow, need - got)
            if delta == 0:
                break
            got += delta
        total += got / need
    return total

def _augment(j, jobs, free, flow, want) -> int:
    n_slots = len(free)
    nxt = list(range(n_slots + 1))

    def find(s):
        while nxt[s] != s:
            nxt[s] = nxt[nxt[s]]
            s = nxt[s]
        return s

    parent_slot: dict[int, int] = {}
    parent_job: dict[int, int] = {j: -1}
    queue = deque([j])
    end = None
    while queue and end is None:
        k = queue.popleft()
        lo, hi, _ = jobs[k]
        s = find(lo)
        while s < hi:
            nxt[s] = s + 1
            parent_slot[s] = k
            if free[s]:
                end = s
                break
            for m, amount in flow[s].items():
                if amount and m not in parent_job:
                    parent_job[m] = s
                    queue.append(m)
            s = find(s + 1)
    if end is None:
        return 0
    delta = min(free[end], want)
    k = parent_slot[end]
    while k != j:
        sp = parent_job[k]
        delta = min(delta, flow[sp][k])
        k = parent_slot[sp]
    s = end
    free[s] -= delta
    while True:
        k = parent_slot[s]
        flow[s][k] = flow[s].get(k, 0) + delta
        if k == j:
            return delta
        sp = parent_job[k]
        flow[sp][k] -= delta
        if not flow[sp][k]:
            del flow[sp][k]
        s = sp

def scenario_bound(
    cfg: Config,
    *,
    seed: int,
    duration_s: float,
    dt_s: float,
    ground_stations=None,
    rate_per_class_per_hour=None,
) -> ScenarioBound:
    ground_stations = ground_stations or (
        (GROUND_STATION_LAT_DEG, GROUND_STATION_LON_DEG, GROUND_STATION_ALT_M),
    )
    up = _up_tick_times(cfg, duration_s, dt_s, ground_stations)
    arrivals = generate_arrivals(
        list(cfg.data_class_priority), duration_s, seed,
        rate_per_class_per_hour=rate_per_class_per_hour,
    )
    slot_cap = int(round(dt_s * LINK_DATA_RATE_BPS / 8))
    n_up = len(up)

    window_jobs, deadline_jobs = [], []
    reach_w = reach_d = 0
    for arrival, item in arrivals:
        lo = bisect.bisect_left(up, arrival)
        hi = bisect.bisect_right(up, item.deadline)
        reach_w += lo < n_up
        reach_d += lo < hi
        window_jobs.append(((n_up - lo) * slot_cap, item.size_bytes))
        deadline_jobs.append((lo, hi, item.size_bytes))
    return ScenarioBound(
        n_generated=len(arrivals),
        n_reachable_window=reach_w,
        n_reachable_deadline=reach_d,
        window_bound=moore_hodgson(window_jobs),
        deadline_bound=math.floor(fluid_completions(deadline_jobs, n_up, slot_cap) + 1e-9),
    )
