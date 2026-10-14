from __future__ import annotations

from pathlib import Path

from engine.config_loader import load_config
from sim.scenario import GROUND_STATIONS_DUAL, ORBITAL_PERIOD_S
from tools.generate_ground_station_analysis import (
    CoverageRow,
    render_document,
    run_coverage_scenario,
    write_ground_station_analysis,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_A = REPO_ROOT / "config" / "config-a.yaml"
CONFIG_B = REPO_ROOT / "config" / "config-b.yaml"

SHORT_DURATION_S = 10 * ORBITAL_PERIOD_S
SEED = 42

def test_run_coverage_scenario_dual_station_has_at_least_as_much_contact():
    cfg = load_config(CONFIG_A)
    single = run_coverage_scenario(
        cfg, seed=SEED, duration_s=SHORT_DURATION_S, dt_s=60.0, ground_stations=None,
    )
    dual = run_coverage_scenario(
        cfg, seed=SEED, duration_s=SHORT_DURATION_S, dt_s=60.0,
        ground_stations=GROUND_STATIONS_DUAL,
    )

    assert isinstance(single, CoverageRow)
    assert dual.station_count == 2
    assert single.station_count == 1
    assert dual.contact_time_s >= single.contact_time_s
    assert dual.contact_time_s > single.contact_time_s

def test_run_coverage_scenario_reports_contact_time_within_duration_bounds():
    cfg = load_config(CONFIG_A)
    row = run_coverage_scenario(
        cfg, seed=SEED, duration_s=SHORT_DURATION_S, dt_s=60.0, ground_stations=None,
    )
    assert 0.0 <= row.contact_time_s <= SHORT_DURATION_S

def test_render_document_contains_required_content():
    single = CoverageRow(
        config_id="config-a", station_count=1, contact_time_s=1000.0,
        contact_time_pct=10.0, delivery_success_rate=0.5,
        ttc_latency_p95_s=120.0, energy_per_delivered_bit_j=1e-4,
    )
    dual = CoverageRow(
        config_id="config-a", station_count=2, contact_time_s=2000.0,
        contact_time_pct=20.0, delivery_success_rate=0.6,
        ttc_latency_p95_s=90.0, energy_per_delivered_bit_j=9e-5,
    )
    doc = render_document({"config-a": (single, dual)})
    assert "# Ground-Station Coverage Analysis" in doc
    assert "config-a" in doc
    assert "Svalbard" in doc
    assert "1000" in doc or "1,000" in doc
    assert "auto-generated" in doc.lower()

def test_write_ground_station_analysis_writes_a_file(tmp_path):
    output_path = tmp_path / "ground-station-coverage-analysis.md"
    write_ground_station_analysis(
        output_path, seed=SEED, duration_s=SHORT_DURATION_S, dt_s=60.0,
    )
    text = output_path.read_text()
    assert "# Ground-Station Coverage Analysis" in text
    assert "config-a" in text
    assert "config-b" in text
