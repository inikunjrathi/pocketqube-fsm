from __future__ import annotations

from pathlib import Path

from engine.config_loader import load_config
from policy.base import FeatureVector
from policy.dataset import TrainingRow, generate_dataset
from sim.scenario import ORBITAL_PERIOD_S

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_A = REPO_ROOT / "config" / "config-a.yaml"
CONFIG_B = REPO_ROOT / "config" / "config-b.yaml"

_TEST_SEEDS = (1, 2)
_TEST_DURATION_S = 6 * ORBITAL_PERIOD_S
_TEST_DT_S = 60.0

def test_generate_dataset_produces_rows_with_valid_labels():
    cfg = load_config(CONFIG_A)
    rows = generate_dataset([cfg], seeds=_TEST_SEEDS, duration_s=_TEST_DURATION_S, dt_s=_TEST_DT_S)
    assert rows, "expected at least one decision point across 2 seeds"
    for row in rows:
        assert isinstance(row, TrainingRow)
        assert isinstance(row.features, FeatureVector)
        assert row.label in ("serve", "hold")

def test_generate_dataset_is_deterministic():
    cfg = load_config(CONFIG_A)
    rows1 = generate_dataset([cfg], seeds=_TEST_SEEDS, duration_s=_TEST_DURATION_S, dt_s=_TEST_DT_S)
    rows2 = generate_dataset([cfg], seeds=_TEST_SEEDS, duration_s=_TEST_DURATION_S, dt_s=_TEST_DT_S)
    assert len(rows1) == len(rows2)
    assert [r.label for r in rows1] == [r.label for r in rows2]
    assert [r.features for r in rows1] == [r.features for r in rows2]

def test_generate_dataset_covers_both_configs():
    config_a = load_config(CONFIG_A)
    config_b = load_config(CONFIG_B)
    rows = generate_dataset(
        [config_a, config_b], seeds=_TEST_SEEDS, duration_s=_TEST_DURATION_S, dt_s=_TEST_DT_S,
    )
    rows_a_only = generate_dataset(
        [config_a], seeds=_TEST_SEEDS, duration_s=_TEST_DURATION_S, dt_s=_TEST_DT_S,
    )
    assert len(rows) >= len(rows_a_only)
