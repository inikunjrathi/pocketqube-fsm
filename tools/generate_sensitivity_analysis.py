from __future__ import annotations

import contextlib
import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sim.power as _power_module  # noqa: E402
from engine.config_loader import Config, load_config  # noqa: E402
from sim.data_arrival import generate_arrivals  # noqa: E402
from sim.driver import DeliveryRecord, run_simulation  # noqa: E402
from sim.scenario import DRAW_W_COMMS_TTC, LINK_DATA_RATE_BPS  # noqa: E402
from tools.generate_baseline_results import (  # noqa: E402
    DEFAULT_DT_S,
    DEFAULT_DURATION_S,
    DEFAULT_SEED,
    run_baseline,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = REPO_ROOT / "docs" / "sensitivity-analysis.md"

EXCLUDED_PARAMETERS = (
    ("P-011", "deploy_confirm_path_a_timeout_s", "Monitoring threshold, not guard-consumed (see docs/parameters.md's review note)."),
    ("P-012", "deploy_confirm_path_b_beacon_window_s", "Monitoring threshold, not guard-consumed (same note)."),
    ("P-016", "fade_margin_db", "Read into a variable but never used by any control-flow gate (documented \"honesty note\" in docs/parameters.md -- link.is_up depends only on the elevation mask)."),
    ("P-017", "watchdog_timeout_s", "No watchdog-timeout simulation exists in sim/ -- structural only."),
    ("P-018", "mode_exclusivity_ruleset", "Structural declaration (which states are mutually exclusive), not a numeric guard value."),
    ("P-020", "safe_mode_exit_policy", "Documentation label describing which structural variant a config implements, not a runtime-checked guard value (see decision record 0002/0003)."),
    ("P-022", "decision_log_verbosity", "Controls log completeness, not simulated behavior."),
    ("P-024", "conflict_resolution_default_order", "Structural (which rank each event belongs to), not a single numeric guard value to sweep."),
)

@dataclasses.dataclass(frozen=True)
class SweepSpec:
    param_id: str
    param_name: str
    unit: str
    baseline_value: float
    low_value: float
    high_value: float
    note: str = ""

SWEEP_SPECS: tuple[SweepSpec, ...] = (
    SweepSpec(
        "P-013", "battery_soc_safe_mode_entry_threshold_pct", "%",
        baseline_value=25.0, low_value=15.0, high_value=35.0,
    ),
    SweepSpec(
        "P-014", "battery_soc_safe_mode_recovery_threshold_pct", "%",
        baseline_value=40.0, low_value=30.0, high_value=50.0,
    ),
    SweepSpec(
        "P-015", "link_quality_min_elevation_deg", "deg",
        baseline_value=10.0, low_value=5.0, high_value=15.0,
    ),
    SweepSpec(
        "P-019", "fault_count_threshold_for_latched_fault", "consecutive faults",
        baseline_value=3.0, low_value=1.0, high_value=5.0,
        note=(
            "sim/driver.py's simulated telemetry hardcodes fault_count=0 for "
            "the whole reference scenario (no fault injection exists in the "
            "sim/ layer) -- every value below is expected to show identical "
            "metrics to the baseline. This null result is itself the finding: "
            "the fault-triggered safe-mode path is untestable via any "
            "delivery/energy metric this project reports, only via "
            "engine-level fault-injection tests."
        ),
    ),
)

POWER_UNCERTAINTY_BAND = 0.30

POWER_UNCERTAINTY_SPECS: tuple[tuple[str, str, float], ...] = (
    ("SSTV", "COMMS_SSTV", 1.5),
    ("CODEC2_M17", "COMMS_VOICE", 1.25),
)

@contextlib.contextmanager
def _overridden_comms_draw(category_key: str, new_draw_w: float):
    original = dict(_power_module._COMMS_BURST_DRAW_W_BY_CATEGORY)
    try:
        _power_module._COMMS_BURST_DRAW_W_BY_CATEGORY = {**original, category_key: new_draw_w}
        yield
    finally:
        _power_module._COMMS_BURST_DRAW_W_BY_CATEGORY = original

def _energy_per_bit_by_class(
    deliveries: list[DeliveryRecord], size_bytes_by_item: dict[str, int]
) -> dict[str, float | None]:
    energy_j_by_class: dict[str, float] = {}
    bits_by_class: dict[str, int] = {}
    for d in deliveries:
        if not d.delivered:
            continue
        energy_j_by_class[d.data_class] = (
            energy_j_by_class.get(d.data_class, 0.0) + (d.energy_wh or 0.0) * 3600.0
        )
        bits_by_class[d.data_class] = (
            bits_by_class.get(d.data_class, 0)
            + size_bytes_by_item.get(d.item_id, 0) * 8
        )
    return {
        cls: (energy_j_by_class[cls] / bits_by_class[cls] if bits_by_class.get(cls) else None)
        for cls in energy_j_by_class
    }

@dataclasses.dataclass(frozen=True)
class PowerUncertaintyResult:
    ratio: float
    draw_w: float
    energy_per_bit_j: float | None

def run_power_uncertainty_sweep(
    cfg: Config, data_class: str, category_key: str, baseline_ratio: float,
    *, seed: int, duration_s: float, dt_s: float,
) -> list[PowerUncertaintyResult]:
    priority_order = list(cfg.data_class_priority)
    arrivals = generate_arrivals(priority_order, duration_s, seed)
    size_bytes_by_item = {item.id: item.size_bytes for _, item in arrivals}

    results = []
    for ratio in (
        baseline_ratio * (1 - POWER_UNCERTAINTY_BAND),
        baseline_ratio,
        baseline_ratio * (1 + POWER_UNCERTAINTY_BAND),
    ):
        draw_w = DRAW_W_COMMS_TTC * ratio
        with _overridden_comms_draw(category_key, draw_w):
            result = run_simulation(cfg, duration_s=duration_s, dt_s=dt_s, seed=seed)
        per_class = _energy_per_bit_by_class(result.deliveries, size_bytes_by_item)
        results.append(
            PowerUncertaintyResult(
                ratio=ratio, draw_w=draw_w, energy_per_bit_j=per_class.get(data_class)
            )
        )
    return results

def _render_power_uncertainty_section(
    uncertainty: dict[str, list[PowerUncertaintyResult]],
) -> str:
    lines = [
        "## Power-model uncertainty: SSTV/VOICE transmit draw",
        "",
        "SIM-009 (SSTV) and SIM-010 (VOICE, `CODEC2_M17`) transmit draws are "
        "not real POQUITO figures -- POQUITO carries neither payload. Both "
        "are the one cited real draw (`DRAW_W_COMMS_TTC` = "
        f"{DRAW_W_COMMS_TTC} W) scaled by a placeholder ratio. This section "
        f"reports each class's own energy-per-bit across a "
        f"+/-{POWER_UNCERTAINTY_BAND * 100:.0f}% band on that ratio, instead "
        "of the single point estimate docs/baseline-results.md reports "
        "(which is an aggregate across all three classes and would dilute "
        "this signal -- see this module's docstring).",
        "",
    ]
    for data_class, results in uncertainty.items():
        lines.append(f"### {data_class}")
        lines.append("")
        lines.append("| Ratio (x TTC draw) | Draw (W) | Energy per delivered bit (J/bit) |")
        lines.append("|---|---|---|")
        for r in results:
            energy_str = _fmt_energy(r.energy_per_bit_j)
            lines.append(f"| {r.ratio:.3f} | {r.draw_w:.4f} | {energy_str} |")
        lines.append("")
        values = [r.energy_per_bit_j for r in results if r.energy_per_bit_j is not None]
        if len(values) >= 2:
            lines.append(
                f"Range: [{min(values):.6g}, {max(values):.6g}] J/bit across "
                f"the +/-{POWER_UNCERTAINTY_BAND * 100:.0f}% band -- this is "
                "the honest uncertainty on this figure until a real payload "
                "draw measurement (or a cited analog) replaces the scaled "
                "placeholder."
            )
            lines.append("")
    return "\n".join(lines)

def with_overridden_parameter(cfg: Config, param_id: str, new_value: float) -> Config:
    if param_id not in cfg.parameters:
        raise KeyError(f"{param_id} not present in {cfg.config_id}'s parameters")
    new_parameters = dict(cfg.parameters)
    new_parameters[param_id] = dataclasses.replace(new_parameters[param_id], value=new_value)
    return dataclasses.replace(cfg, parameters=new_parameters)

@dataclasses.dataclass(frozen=True)
class SweepResult:
    value: float
    delivery_success_rate: float
    energy_per_delivered_bit_j: float | None

def run_sweep(
    cfg: Config, spec: SweepSpec, *, seed: int, duration_s: float, dt_s: float
) -> list[SweepResult]:
    results = []
    for value in (spec.low_value, spec.baseline_value, spec.high_value):
        swept_cfg = with_overridden_parameter(cfg, spec.param_id, value)
        row = run_baseline(swept_cfg, seed=seed, duration_s=duration_s, dt_s=dt_s)
        results.append(
            SweepResult(
                value=value,
                delivery_success_rate=row.metrics.delivery_success_rate,
                energy_per_delivered_bit_j=row.metrics.energy_per_delivered_bit_j,
            )
        )
    return results

def _fmt_energy(value: float | None) -> str:
    return "—" if value is None else f"{value:.6g}"

def _render_sweep_section(spec: SweepSpec, results: list[SweepResult]) -> str:
    lines = [
        f"## {spec.param_id} `{spec.param_name}` ({spec.unit})",
        "",
    ]
    if spec.note:
        lines.append(f"**Note:** {spec.note}")
        lines.append("")
    lines.extend(
        [
            "| Value | Delivery success rate | Energy per delivered bit (J/bit) |",
            "|---|---|---|",
        ]
    )
    for r in results:
        marker = " (baseline)" if r.value == spec.baseline_value else ""
        lines.append(
            f"| {r.value:g}{marker} | {r.delivery_success_rate * 100:.2f}% | "
            f"{_fmt_energy(r.energy_per_delivered_bit_j)} |"
        )
    lines.append("")
    return "\n".join(lines)

def render_document(
    swept: dict[str, list[SweepResult]],
    *,
    power_uncertainty: dict[str, list[PowerUncertaintyResult]] | None = None,
) -> str:
    parts = [
        "<!-- Auto-generated by tools/generate_sensitivity_analysis.py. "
        "Do not hand-edit. -->",
        "",
        "# Parameter Sensitivity Analysis",
        "",
        "One-at-a-time sensitivity sweep over every Config-A `Assumed` "
        "parameter confirmed (by direct code inspection) to actually reach "
        "a guard or a sim/driver.py code path -- see this module's "
        "docstring for the full scoping rationale. Each parameter is swept "
        "across a low/baseline/high value with every other parameter held "
        f"at its shipped config-a.yaml value, on the real reference "
        f"scenario (seed={DEFAULT_SEED}, duration_s={DEFAULT_DURATION_S}, "
        f"dt_s={DEFAULT_DT_S}).",
        "",
    ]
    for spec in SWEEP_SPECS:
        results = swept.get(spec.param_id)
        if results:
            parts.append(_render_sweep_section(spec, results))

    parts.append("## Interpretation")
    parts.append("")
    parts.append(
        "Whether a parameter's low/high values actually move the reported "
        "metrics is itself part of the sensitivity finding, not just the "
        "magnitude when they do:"
    )
    parts.append("")
    for spec in SWEEP_SPECS:
        results = swept.get(spec.param_id)
        if not results:
            continue
        rates = {round(r.delivery_success_rate, 6) for r in results}
        if len(rates) == 1:
            parts.append(
                f"- **{spec.param_id}** (`{spec.param_name}`): **no movement** "
                "across the full low/baseline/high range -- delivery success "
                f"stays at {next(iter(rates)) * 100:.2f}% regardless of value. "
                + (
                    "Expected (see note above)."
                    if spec.note
                    else "Not predicted in advance: the reference scenario's "
                    "battery/power dynamics apparently never cross this "
                    "threshold at all in the committed 48h window, an "
                    "empirical finding this sweep surfaces rather than one "
                    "assumed beforehand."
                )
            )
        else:
            low_rate = next(r.delivery_success_rate for r in results if r.value == spec.low_value)
            high_rate = next(r.delivery_success_rate for r in results if r.value == spec.high_value)
            parts.append(
                f"- **{spec.param_id}** (`{spec.param_name}`): **real "
                f"sensitivity** -- delivery success ranges from "
                f"{min(low_rate, high_rate) * 100:.2f}% to "
                f"{max(low_rate, high_rate) * 100:.2f}% across the swept "
                "range, a materially different result depending on which "
                "value this currently-`Assumed` parameter turns out to be "
                "once real mission data is available."
            )
    parts.append("")

    parts.append("## Parameters excluded from this sweep")
    parts.append("")
    parts.append(
        "The remaining Config-A `Assumed`/`TBD` parameters are excluded "
        "because they have no code path in `engine/`, `sim/`, or `policy/` "
        "that reads them (confirmed by repo-wide grep, not assumed) -- "
        "sweeping them could not move any simulated metric:"
    )
    parts.append("")
    parts.append("| ID | Parameter | Why excluded |")
    parts.append("|---|---|---|")
    for param_id, name, reason in EXCLUDED_PARAMETERS:
        parts.append(f"| {param_id} | `{name}` | {reason} |")
    parts.append("")

    if power_uncertainty:
        parts.append(_render_power_uncertainty_section(power_uncertainty))

    return "\n".join(parts)

def write_sensitivity_analysis(
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    *,
    seed: int = DEFAULT_SEED,
    duration_s: float = DEFAULT_DURATION_S,
    dt_s: float = DEFAULT_DT_S,
) -> None:
    config_a = load_config(REPO_ROOT / "config" / "config-a.yaml")
    swept = {
        spec.param_id: run_sweep(config_a, spec, seed=seed, duration_s=duration_s, dt_s=dt_s)
        for spec in SWEEP_SPECS
    }
    power_uncertainty = {
        data_class: run_power_uncertainty_sweep(
            config_a, data_class, category_key, baseline_ratio,
            seed=seed, duration_s=duration_s, dt_s=dt_s,
        )
        for data_class, category_key, baseline_ratio in POWER_UNCERTAINTY_SPECS
    }
    Path(output_path).write_text(render_document(swept, power_uncertainty=power_uncertainty))

def main() -> None:
    write_sensitivity_analysis(DEFAULT_OUTPUT_PATH)
    print(f"wrote {DEFAULT_OUTPUT_PATH}")

if __name__ == "__main__":
    main()
