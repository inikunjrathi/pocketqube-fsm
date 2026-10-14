from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.config_loader import Config, load_config  # noqa: E402
from sim.data_arrival import generate_arrivals  # noqa: E402
from sim.driver import DeliveryRecord, run_simulation  # noqa: E402
from sim.metrics import (  # noqa: E402
    AggregatedMetrics,
    BaselineMetrics,
    aggregate_metrics,
    compute_metrics,
)
from sim.scenario import GROUND_STATIONS_DUAL  # noqa: E402

TTC_CLASS_NAME = "TTC"

DEFAULT_SEED = 42
DEFAULT_DURATION_S = 172_800.0
DEFAULT_DT_S = 10.0

EVAL_SEEDS: tuple[int, ...] = tuple(range(5000, 5020))

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = REPO_ROOT / "docs" / "baseline-results.md"

_NA = "—"

@dataclass(frozen=True)
class PerClassBreakdown:

    arrived: int
    delivered_on_time: int
    delivered_late: int
    never_delivered: int

def _per_class_breakdown(
    deliveries: list[DeliveryRecord], priority_order: list[str]
) -> dict[str, PerClassBreakdown]:
    breakdown = {cls: [0, 0, 0, 0] for cls in priority_order}
    for record in deliveries:
        counts = breakdown[record.data_class]
        counts[0] += 1
        if record.delivered and not record.deadline_missed:
            counts[1] += 1
        elif record.delivered and record.deadline_missed:
            counts[2] += 1
        else:
            counts[3] += 1
    return {
        cls: PerClassBreakdown(*counts) for cls, counts in breakdown.items()
    }

@dataclass(frozen=True)
class BaselineRow:
    config_id: str
    metrics: BaselineMetrics
    per_class_breakdown: dict[str, PerClassBreakdown]

def run_baseline(
    cfg: Config, *, seed: int, duration_s: float, dt_s: float,
    ground_stations: tuple[tuple[float, float, float], ...] | None = None,
) -> BaselineRow:
    result = run_simulation(
        cfg, duration_s=duration_s, dt_s=dt_s, seed=seed,
        ground_stations=ground_stations,
    )
    priority_order = list(cfg.data_class_priority)

    arrivals = generate_arrivals(priority_order, duration_s, seed)
    size_bytes_by_item = {item.id: item.size_bytes for _, item in arrivals}

    metrics = compute_metrics(
        result.deliveries,
        ttc_class_name=TTC_CLASS_NAME,
        priority_order=priority_order,
        size_bytes_by_item=size_bytes_by_item,
    )
    return BaselineRow(
        config_id=cfg.config_id,
        metrics=metrics,
        per_class_breakdown=_per_class_breakdown(result.deliveries, priority_order),
    )

def run_baseline_multi_seed(
    cfg: Config, *, seeds: tuple[int, ...], duration_s: float, dt_s: float,
    ground_stations: tuple[tuple[float, float, float], ...] | None = None,
) -> AggregatedMetrics:
    per_seed_metrics = [
        run_baseline(
            cfg, seed=seed, duration_s=duration_s, dt_s=dt_s,
            ground_stations=ground_stations,
        ).metrics
        for seed in seeds
    ]
    return aggregate_metrics(per_seed_metrics)

def _fmt_ci(summary) -> str:  # noqa: ANN001 - MetricSummary, avoid import cycle in type hint
    return f"{summary.mean:.6g} (n={summary.n}, 95% CI [{summary.ci95_low:.6g}, {summary.ci95_high:.6g}])"

def _render_multi_seed_section(config_id: str, agg: AggregatedMetrics) -> str:
    lines = [
        f"### Config {config_id} — multi-seed ({agg.n_runs} seeds)",
        "",
        "Same scenario (duration, dt, TLE, ground station) as the single-seed "
        "reference run above, repeated across "
        f"{agg.n_runs} independent seeds and aggregated with "
        "sim.metrics.aggregate_metrics() (mean, 95% CI via the normal "
        "approximation — see that module's docstring). Supplements, does not "
        "replace, the seed=42 reference run above.",
        "",
        "| Metric | Mean (95% CI) |",
        "|---|---|",
        f"| Delivery success rate | {_fmt_ci(agg.delivery_success_rate)} |",
    ]
    if agg.deadline_success_ratio is not None:
        lines.append(f"| Deadline success ratio (all classes) | {_fmt_ci(agg.deadline_success_ratio)} |")
        for cls, summary in agg.deadline_success_ratio_by_class.items():
            lines.append(f"| Deadline success ratio ({cls}) | {_fmt_ci(summary)} |")
    if agg.ttc_latency_p95_s is not None:
        lines.append(f"| TT&C latency p95 (s) | {_fmt_ci(agg.ttc_latency_p95_s)} |")
    if agg.energy_per_delivered_bit_j is not None:
        lines.append(
            f"| Energy per delivered bit (J/bit) | {_fmt_ci(agg.energy_per_delivered_bit_j)} |"
        )
    lines.append("")
    return "\n".join(lines)

def _fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"

def _fmt_s(value: float | None) -> str:
    return _NA if value is None else f"{value:.3f}"

def _fmt_energy(value: float | None) -> str:
    return _NA if value is None else f"{value:.6g}"

def _render_row_section(row: BaselineRow) -> str:
    m = row.metrics
    lines = [
        f"## Config {row.config_id}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Delivery success rate (delivered within run window / generated) | {_fmt_pct(m.delivery_success_rate)} |",
        f"| Deadline success ratio (delivered by deadline / generated) | {_fmt_pct(m.deadline_success_ratio)} |",
        f"| TT&C latency min (s) | {_fmt_s(m.ttc_latency_min_s)} |",
        f"| TT&C latency median (s) | {_fmt_s(m.ttc_latency_median_s)} |",
        f"| TT&C latency p95 (s) | {_fmt_s(m.ttc_latency_p95_s)} |",
        f"| TT&C latency max (s) | {_fmt_s(m.ttc_latency_max_s)} |",
        f"| Energy per delivered bit (J/bit) | {_fmt_energy(m.energy_per_delivered_bit_j)} |",
        "",
        "### Per-class delivery breakdown",
        "",
        "The aggregate delivery success rate and deadline-miss counts above "
        "average over all classes; this table breaks the same run down by "
        "data class so that a class the frozen priority scheduler starves "
        "entirely (delivered = 0) is visible rather than folded into the "
        "aggregate. \"Delivered (late)\" and \"Never delivered\" are both "
        "counted in the deadline-misses table above, but are distinct "
        "outcomes: the former means the item eventually arrived at the "
        "ground, just after its deadline; the latter means it was still "
        "queued, undelivered, at the end of the run.",
        "",
        "| Data class | Arrived | Delivered (on time) | Delivered (late) | Never delivered | Deadline success ratio |",
        "|---|---|---|---|---|---|",
    ]
    for data_class, b in row.per_class_breakdown.items():
        lines.append(
            f"| {data_class} | {b.arrived} | {b.delivered_on_time} | "
            f"{b.delivered_late} | {b.never_delivered} | "
            f"{_fmt_pct(m.deadline_success_ratio_by_class.get(data_class, 0.0))} |"
        )
    lines.extend(
        [
            "",
            "### Deadline misses by class",
            "",
            "| Data class | Deadline misses |",
            "|---|---|",
        ]
    )
    for data_class, count in m.deadline_misses_by_class.items():
        lines.append(f"| {data_class} | {count} |")
    lines.append("")
    return "\n".join(lines)

def render_document(
    rows: list[BaselineRow],
    *,
    multi_seed: dict[str, AggregatedMetrics] | None = None,
) -> str:
    multi_seed = multi_seed or {}
    parts = [
        "<!-- Auto-generated by tools/generate_baseline_results.py from real "
        "sim.driver simulation runs (see that module's docstring for the "
        "seed/duration/dt used). Do not hand-edit. -->",
        "",
        "# Baseline Results",
        "",
        "Phase 4 (W8-9) exit-criterion baseline metrics for both shipped "
        "configs, computed by tools/generate_baseline_results.py from real "
        f"sim.driver.run_simulation() runs (seed={DEFAULT_SEED}, "
        f"duration_s={DEFAULT_DURATION_S}, dt_s={DEFAULT_DT_S}) aggregated "
        "by sim.metrics.compute_metrics().",
        "",
        "Two delivery figures are reported and they answer different "
        "questions. *Delivery success rate* counts every item downlinked "
        "before the end of the 48 h run, however late. *Deadline success "
        "ratio* counts only items downlinked at or before their own "
        "deadline (TT&C 300 s, SSTV 3600 s, CODEC2_M17 900 s after arrival; sim/data_arrival.py), divided by all "
        "generated items. Under sparse single-station passes most items "
        "are delivered late, so the two differ by an order of magnitude.",
        "",
        "Energy per delivered bit uses the explicit comms-state -> "
        "transmit-class power mapping of docs/decisions/"
        "0009-explicit-transmit-class-power-mapping.md: Config B/C's "
        "collapsed COMMS_ACTIVE state is charged the transmit draw of the "
        "data class it is serving (before decision 0009 it fell through to "
        "the idle draw).",
        "",
        "Config A and Config B's numbers below may now differ beyond "
        "energy per delivered bit: this driver fires real `PASS_END`/"
        "`POWER_LOW`/recovery events (Phase 5, Task 2), "
        "so Config A's autonomous safe-mode recovery and Config B's "
        "ground-only recovery (SIM-011) can now produce genuinely "
        "different outcomes.",
        "",
        "Config C (Phase 7D) is a synthetic third configuration — not a "
        "POQUITO/SomaiyaSat mission variant like Config A/B — added to "
        "test the engine's generality claim against a deployment x "
        "recovery-model axis combination neither shipped config "
        "represents (single-path deployment + autonomous-permitted "
        "recovery). Its row below is generated against the DUAL "
        "ground-station reference scenario (sim.scenario."
        "GROUND_STATIONS_DUAL, Phase 7B), not the single-station default "
        "Config A/B use — so Config C's numbers are not directly "
        "comparable to A/B's on ground-station coverage; see "
        "docs/decisions/0006-config-c-generality-axis.md for the full "
        "scope statement, including what Config C deliberately does NOT "
        "extend (policy comparison, the RQ1-RQ3 visualization dashboard).",
        "",
    ]
    for row in rows:
        parts.append(_render_row_section(row))
        agg = multi_seed.get(row.config_id)
        if agg is not None:
            parts.append(_render_multi_seed_section(row.config_id, agg))
    return "\n".join(parts)

def write_baseline_results(
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    *,
    seed: int = DEFAULT_SEED,
    duration_s: float = DEFAULT_DURATION_S,
    dt_s: float = DEFAULT_DT_S,
    eval_seeds: tuple[int, ...] | None = EVAL_SEEDS,
) -> None:
    config_a = load_config(REPO_ROOT / "config" / "config-a.yaml")
    config_b = load_config(REPO_ROOT / "config" / "config-b.yaml")
    config_c = load_config(REPO_ROOT / "config" / "config-c.yaml")
    configs = (config_a, config_b)

    rows = [
        run_baseline(cfg, seed=seed, duration_s=duration_s, dt_s=dt_s)
        for cfg in configs
    ]
    rows.append(
        run_baseline(
            config_c, seed=seed, duration_s=duration_s, dt_s=dt_s,
            ground_stations=GROUND_STATIONS_DUAL,
        )
    )
    configs = (config_a, config_b, config_c)

    multi_seed: dict[str, AggregatedMetrics] | None = None
    if eval_seeds:
        multi_seed = {
            cfg.config_id: run_baseline_multi_seed(
                cfg, seeds=eval_seeds, duration_s=duration_s, dt_s=dt_s,
                ground_stations=(
                    GROUND_STATIONS_DUAL if cfg.config_id == "config-c" else None
                ),
            )
            for cfg in configs
        }

    Path(output_path).write_text(render_document(rows, multi_seed=multi_seed))

def main() -> None:
    write_baseline_results(DEFAULT_OUTPUT_PATH)
    print(f"wrote {DEFAULT_OUTPUT_PATH}")

if __name__ == "__main__":
    main()
