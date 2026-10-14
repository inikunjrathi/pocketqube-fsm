from __future__ import annotations

from dataclasses import dataclass

from engine.config_loader import Config
from policy.base import FeatureVector
from policy.oracle import OraclePolicy
from sim.driver import run_simulation

DEFAULT_SEEDS = tuple(range(1000, 1020))
DATASET_DURATION_S = 172_800.0
DATASET_DT_S = 10.0

@dataclass(frozen=True)
class TrainingRow:
    features: FeatureVector
    label: str

def generate_dataset(
    configs: list[Config],
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
    *,
    duration_s: float = DATASET_DURATION_S,
    dt_s: float = DATASET_DT_S,
    **sim_kwargs,
) -> list[TrainingRow]:
    rows: list[TrainingRow] = []

    def _record(features: FeatureVector, label: str) -> None:
        rows.append(TrainingRow(features=features, label=label))

    for cfg in configs:
        for seed in seeds:
            run_simulation(
                cfg, duration_s=duration_s, dt_s=dt_s, seed=seed,
                policy=OraclePolicy(sim_kwargs.get("ground_stations")),
                record_hook=_record, **sim_kwargs,
            )
    return rows
