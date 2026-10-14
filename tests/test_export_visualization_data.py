from __future__ import annotations

from pathlib import Path

import pytest

from engine.config_loader import load_config
from sim.scenario import ORBITAL_PERIOD_S
from tools.export_visualization_data import (
    _parse_ci_value,
    build_complexity_data,
    build_model_checking_data,
    build_multi_seed_baseline_data,
    build_multi_seed_policy_data,
    build_power_uncertainty_data,
    build_replay_data,
    build_rq1_data,
    build_rq3_data,
    build_sensitivity_data,
    compute_rq2_data,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_A = REPO_ROOT / "config" / "config-a.yaml"
CONFIG_B = REPO_ROOT / "config" / "config-b.yaml"

SHORT_DURATION_S = 3 * ORBITAL_PERIOD_S

@pytest.mark.requirement("R-26")
def test_build_rq1_data_reflects_known_config_asymmetry():
    config_a = load_config(CONFIG_A)
    config_b = load_config(CONFIG_B)
    data = build_rq1_data(config_a, config_b)
    by_id = {c["config_id"]: c for c in data["configs"]}
    assert set(by_id) == {"config-a", "config-b"}
    # R-26
    assert by_id["config-a"]["autonomous_recovery_capable"] is True
    assert by_id["config-b"]["autonomous_recovery_capable"] is False
    assert by_id["config-a"]["state_count"] == len(config_a.states)
    assert by_id["config-b"]["event_count"] == len(config_b.events)
    assert by_id["config-a"]["transition_count"] == len(config_a.transitions)
    assert by_id["config-a"]["name"] == config_a.name

def test_compute_rq2_data_reports_all_passing():
    data = compute_rq2_data()
    assert data["failed"] == 0
    assert data["passed"] >= 100
    assert set(data["test_files"]) == {
        "tests/test_fault_injection.py",
        "tests/test_latch_fuzz.py",
        "tests/test_persistence.py",
    }

def test_build_rq3_data_parses_six_rows_and_an_answer():
    data = build_rq3_data()
    assert len(data["rows"]) == 6
    row = data["rows"][0]
    assert set(row) == {
        "config_id", "policy", "delivery_success_pct",
        "ttc_latency_p95_s", "energy_per_bit_j",
    }
    config_ids = {r["config_id"] for r in data["rows"]}
    policies = {r["policy"] for r in data["rows"]}
    assert config_ids == {"config-a", "config-b"}
    assert policies == {"baseline", "oracle", "tree"}
    assert isinstance(data["answer"], str) and data["answer"]
    assert "##" not in data["answer"]
    assert "|" not in data["answer"]
    assert "Multi-seed" not in data["answer"]

def test_parse_ci_value_extracts_mean_n_and_ci_bounds():
    parsed = _parse_ci_value("0.920321 (n=20, 95% CI [0.916119, 0.924522])")
    assert parsed == {"mean": 0.920321, "n": 20, "ci_low": 0.916119, "ci_high": 0.924522}

def test_parse_ci_value_rejects_malformed_cell():
    with pytest.raises(RuntimeError):
        _parse_ci_value("not a CI value")

def test_build_multi_seed_baseline_data_has_both_configs():
    data = build_multi_seed_baseline_data()
    assert len(data["configs"]) == 2
    config_ids = {c["config_id"] for c in data["configs"]}
    assert config_ids == {"config-a", "config-b"}
    for c in data["configs"]:
        assert c["n_seeds"] > 0
        assert "Delivery success rate" in c["metrics"]
        summary = c["metrics"]["Delivery success rate"]
        assert 0.0 <= summary["mean"] <= 1.0
        assert summary["ci_low"] <= summary["mean"] <= summary["ci_high"]

def test_build_multi_seed_policy_data_has_six_rows():
    data = build_multi_seed_policy_data()
    assert len(data["rows"]) == 6
    config_ids = {r["config_id"] for r in data["rows"]}
    policies = {r["policy"] for r in data["rows"]}
    assert config_ids == {"config-a", "config-b"}
    assert policies == {"baseline", "oracle", "tree"}
    for r in data["rows"]:
        assert 0.0 <= r["delivery_success"]["mean"] <= 1.0

def test_build_complexity_data_has_both_configs_and_ratio():
    data = build_complexity_data()
    assert len(data["configs"]) == 2
    for c in data["configs"]:
        policy_names = {p["policy"] for p in c["policies"]}
        assert policy_names == {"baseline", "tree", "oracle"}
        assert c["oracle_to_tree_ratio"] > 1

def test_build_sensitivity_data_has_four_parameters_and_interpretation():
    data = build_sensitivity_data()
    assert len(data["parameters"]) == 4
    param_ids = {p["param_id"] for p in data["parameters"]}
    assert param_ids == {"P-013", "P-014", "P-015", "P-019"}
    for p in data["parameters"]:
        assert len(p["rows"]) == 3
        assert sum(1 for r in p["rows"] if r["is_baseline"]) == 1
    assert data["interpretation"]["P-015"] == "real sensitivity"
    assert data["interpretation"]["P-019"] == "no movement"

def test_build_power_uncertainty_data_has_both_classes():
    data = build_power_uncertainty_data()
    assert len(data["classes"]) == 2
    classes = {c["data_class"] for c in data["classes"]}
    assert classes == {"SSTV", "CODEC2_M17"}
    for c in data["classes"]:
        assert len(c["rows"]) == 3
        assert c["range_low"] < c["range_high"]

def test_build_model_checking_data_reports_no_errors():
    data = build_model_checking_data()
    assert len(data["rows"]) == 2
    for r in data["rows"]:
        assert r["result"] == "No error found"
        assert r["states_declared"] > 0
        assert r["states_reached"] > 0

def test_build_replay_data_produces_ticks_and_deliveries():
    cfg = load_config(CONFIG_A)
    dt_s = 60.0
    data = build_replay_data(cfg, seed=42, duration_s=SHORT_DURATION_S, dt_s=dt_s)
    assert data["config_id"] == "config-a"
    assert data["duration_s"] == SHORT_DURATION_S
    assert data["dt_s"] == dt_s
    assert data["seed"] == 42
    assert len(data["ticks"]) == int(SHORT_DURATION_S // dt_s) + 1

    first_tick = data["ticks"][0]
    assert set(first_tick) == {
        "t", "elevation_deg", "is_illuminated", "link_is_up", "battery_soc_pct",
        "fsm_state_id", "fsm_state_category", "ttc_queue_depth",
        "sstv_queue_depth", "codec2_m17_queue_depth",
    }
    assert first_tick["t"] == 0.0

    assert isinstance(data["deliveries"], list)
    if data["deliveries"]:
        delivery = data["deliveries"][0]
        assert set(delivery) == {
            "item_id", "data_class", "arrival_time_s", "delivered",
            "delivery_time_s", "latency_s", "deadline_missed",
        }

def test_write_visualization_data_writes_both_files(tmp_path):
    from tools.export_visualization_data import write_visualization_data

    data_path = tmp_path / "data.json"
    html_path = tmp_path / "index.html"
    write_visualization_data(
        data_output_path=data_path, html_output_path=html_path,
        seed=42, duration_s=SHORT_DURATION_S, dt_s=60.0,
    )
    assert data_path.exists()
    assert html_path.exists()

    html_text = html_path.read_text()
    assert "__DATA_JSON_PLACEHOLDER__" not in html_text
    assert '"rq1"' in html_text
    assert '"replay"' in html_text

    import json
    data = json.loads(data_path.read_text())
    assert set(data) == {
        "replay", "rq1", "rq2", "rq3",
        "multi_seed_baseline", "multi_seed_policy", "complexity",
        "sensitivity", "power_uncertainty", "model_checking",
    }
