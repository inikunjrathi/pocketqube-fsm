from __future__ import annotations

from pathlib import Path

from engine.config_loader import load_config
from sim.scenario import ORBITAL_PERIOD_S
from tools.generate_worst_case_scenarios import (
    ScenarioResult,
    WORST_CASE_OVERRIDES_BY_CONFIG,
    render_document,
    run_scenario,
    with_overridden_parameters,
    write_worst_case_scenarios,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_A = REPO_ROOT / "config" / "config-a.yaml"

SHORT_DURATION_S = 10 * ORBITAL_PERIOD_S
SEED = 42

def test_with_overridden_parameters_replaces_all_targets():
    cfg = load_config(CONFIG_A)
    overrides = {"P-013": 99.0, "P-015": 88.0}

    swept = with_overridden_parameters(cfg, overrides)

    assert swept.parameters["P-013"].value == 99.0
    assert swept.parameters["P-015"].value == 88.0
    for param_id in cfg.parameters:
        if param_id not in overrides:
            assert swept.parameters[param_id].value == cfg.parameters[param_id].value
    assert cfg.parameters["P-013"].value != 99.0

def test_run_scenario_baseline_matches_run_baseline_delivery_rate():
    from tools.generate_baseline_results import run_baseline

    cfg = load_config(CONFIG_A)
    baseline_row = run_baseline(cfg, seed=SEED, duration_s=SHORT_DURATION_S, dt_s=60.0)
    scenario = run_scenario(
        cfg, {}, seed=SEED, duration_s=SHORT_DURATION_S, dt_s=60.0, ground_stations=None,
    )
    assert isinstance(scenario, ScenarioResult)
    assert scenario.delivery_success_rate == baseline_row.metrics.delivery_success_rate

def test_run_scenario_worst_case_is_no_better_than_baseline():
    cfg = load_config(CONFIG_A)
    baseline = run_scenario(
        cfg, {}, seed=SEED, duration_s=SHORT_DURATION_S, dt_s=60.0, ground_stations=None,
    )
    worst = run_scenario(
        cfg, WORST_CASE_OVERRIDES_BY_CONFIG["config-a"], seed=SEED,
        duration_s=SHORT_DURATION_S, dt_s=60.0, ground_stations=None,
    )
    assert worst.delivery_success_rate <= baseline.delivery_success_rate

def test_render_document_contains_required_content():
    baseline = ScenarioResult(
        label="baseline", delivery_success_rate=0.9, ttc_latency_p95_s=100.0,
        energy_per_delivered_bit_j=1e-4,
    )
    worst = ScenarioResult(
        label="worst-case", delivery_success_rate=0.5, ttc_latency_p95_s=300.0,
        energy_per_delivered_bit_j=2e-4,
    )
    doc = render_document({"config-a": (baseline, worst)})
    assert "# Worst-Case Scenario Analysis" in doc
    assert "config-a" in doc
    assert "compounding" in doc.lower()
    assert "auto-generated" in doc.lower()

def test_write_worst_case_scenarios_writes_a_file(tmp_path):
    output_path = tmp_path / "worst-case-scenario-analysis.md"
    write_worst_case_scenarios(output_path, seed=SEED, duration_s=SHORT_DURATION_S, dt_s=60.0)
    text = output_path.read_text()
    assert "# Worst-Case Scenario Analysis" in text
    assert "config-a" in text
    assert "config-b" in text
