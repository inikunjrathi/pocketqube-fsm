from __future__ import annotations

import itertools
from random import Random

from engine.scheduler import Item

DEFAULT_RATE_PER_CLASS_PER_HOUR = 4.0

TTC_ARRIVAL_RATE_PER_HOUR = 20.0

_DEFAULT_RATE_PER_HOUR_BY_CLASS: dict[str, float] = {
    "TTC": TTC_ARRIVAL_RATE_PER_HOUR,
}

_SIZE_BYTES_RANGE_BY_CLASS: dict[str, tuple[int, int]] = {
    "TTC": (64, 512),
    "SSTV": (2048, 8192),
    "CODEC2_M17": (256, 1536),
}
_DEFAULT_SIZE_BYTES_RANGE = (64, 1024)

_DEADLINE_WINDOW_S_BY_CLASS: dict[str, float] = {
    "TTC": 300.0,
    "SSTV": 3600.0,
    "CODEC2_M17": 900.0,
}
_DEFAULT_DEADLINE_WINDOW_S = 1800.0

def generate_arrivals(
    priority_order: list[str],
    duration_s: float,
    seed: int,
    *,
    rate_per_class_per_hour: dict[str, float] | None = None,
) -> list[tuple[float, Item]]:
    if rate_per_class_per_hour is None:
        rate_per_class_per_hour = {}

    rng = Random(seed)
    id_counter = itertools.count()
    arrivals: list[tuple[float, Item]] = []

    for data_class in priority_order:
        rate_per_hour = rate_per_class_per_hour.get(
            data_class,
            _DEFAULT_RATE_PER_HOUR_BY_CLASS.get(
                data_class, DEFAULT_RATE_PER_CLASS_PER_HOUR
            ),
        )
        rate_per_s = rate_per_hour / 3600.0
        if rate_per_s <= 0.0:
            continue

        size_lo, size_hi = _SIZE_BYTES_RANGE_BY_CLASS.get(
            data_class, _DEFAULT_SIZE_BYTES_RANGE
        )
        deadline_window_s = _DEADLINE_WINDOW_S_BY_CLASS.get(
            data_class, _DEFAULT_DEADLINE_WINDOW_S
        )

        t = 0.0
        while True:
            t += rng.expovariate(rate_per_s)
            if t >= duration_s:
                break
            size_bytes = rng.randint(size_lo, size_hi)
            item = Item(
                id=f"ARR-{next(id_counter):06d}",
                data_class=data_class,
                size_bytes=size_bytes,
                deadline=t + deadline_window_s,
            )
            arrivals.append((t, item))

    arrivals.sort(key=lambda pair: pair[0])
    return arrivals
