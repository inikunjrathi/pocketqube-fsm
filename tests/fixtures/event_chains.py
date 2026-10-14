# RB-02

from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class EventChain:
    label: str
    config_id: str
    events: tuple[tuple[str, float], ...]
    latch_set_at_index: int

CONFIG_A_PATH_B_FIRST = EventChain(
    label="config-a-path-b-confirms-first",
    config_id="config-a",
    events=(
        ("E-01", 0), ("E-02", 900), ("E-04", 900), ("E-03", 900),
        ("E-19", 900), ("E-05", 900),
    ),
    latch_set_at_index=3,
)

CONFIG_A_PATH_A_FIRST = EventChain(
    label="config-a-path-a-confirms-first",
    config_id="config-a",
    events=(
        ("E-01", 0), ("E-02", 900), ("E-03", 900), ("E-04", 900),
        ("E-19", 900), ("E-05", 900),
    ),
    latch_set_at_index=3,
)

CONFIG_B_SINGLE_PATH = EventChain(
    label="config-b-single-path",
    config_id="config-b",
    events=(
        ("E-01", 0), ("E-14", 5), ("E-02", 5), ("E-03", 5),
    ),
    latch_set_at_index=1,
)

CONFIG_C_SINGLE_PATH = EventChain(
    label="config-c-single-path",
    config_id="config-c",
    events=(
        ("E-01", 0), ("E-14", 5), ("E-02", 5), ("E-03", 5),
    ),
    latch_set_at_index=1,
)

ALL_CHAINS = (
    CONFIG_A_PATH_B_FIRST, CONFIG_A_PATH_A_FIRST, CONFIG_B_SINGLE_PATH, CONFIG_C_SINGLE_PATH,
)
