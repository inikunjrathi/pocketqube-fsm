from __future__ import annotations

from pathlib import Path

from engine.config_loader import load_config
from policy.base import BASELINE_POLICY
from policy.dataset import generate_dataset
from policy.oracle import OraclePolicy
from policy.tree import train
from sim.driver import run_simulation
from sim.scenario import ORBITAL_PERIOD_S

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_A = REPO_ROOT / "config" / "config-a.yaml"
CONFIG_B = REPO_ROOT / "config" / "config-b.yaml"

_DURATION_S = 6 * ORBITAL_PERIOD_S
_DT_S = 60.0
_SEED = 12345

def _trained_tree_policy():
    cfg = load_config(CONFIG_A)
    rows = generate_dataset([cfg], seeds=(1, 2), duration_s=_DURATION_S, dt_s=_DT_S)
    return train(rows)

def test_all_three_policies_complete_on_config_a():
    cfg = load_config(CONFIG_A)
    tree_policy = _trained_tree_policy()
    for policy in (BASELINE_POLICY, OraclePolicy(), tree_policy):
        result = run_simulation(cfg, duration_s=_DURATION_S, dt_s=_DT_S, seed=_SEED, policy=policy)
        assert result.config_id == "config-a"

def test_all_three_policies_complete_on_config_b():
    cfg = load_config(CONFIG_B)
    tree_policy = _trained_tree_policy()
    for policy in (BASELINE_POLICY, OraclePolicy(), tree_policy):
        result = run_simulation(cfg, duration_s=_DURATION_S, dt_s=_DT_S, seed=_SEED, policy=policy)
        assert result.config_id == "config-b"
