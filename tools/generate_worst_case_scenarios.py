from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.config_loader import Config, load_config  # noqa: E402
from sim.data_arrival import generate_arrivals  # noqa: E402
from sim.driver import run_simulation  # noqa: E402
from sim.metrics import compute_metrics  # noqa: E402
from sim.scenario import GROUND_STATIONS_DUAL  # noqa: E402
from tools.generate_baseline_results import (  # noqa: E402
    DEFAULT_DT_S,
    DEFAULT_DURATION_S,
    DEFAULT_SEED,
    TTC_CLASS_NAME,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = REPO_ROOT / "docs" / "worst-case-scenario-analysis.md"

CONFIG_PATHS: tuple[tuple[str, Path], ...] = (
    ("config-a", REPO_ROOT / "config" / "config-a.yaml"),
    ("config-b", REPO_ROOT / "config" / "config-b.yaml"),
    ("config-c", REPO_ROOT / "config" / "config-c.yaml"),
)

WORST_CASE_OVERRIDES_BY_CONFIG: dict[str, dict[str, float]] = {
    "config-a": {"P-013": 35.0, "P-014": 50.0, "P-015": 15.0, "P-019": 1.0},
    "config-b": {"PB-003": 35.0, "PB-006": 15.0, "PB-005": 1.0},
    "config-c": {"PC-003": 35.0, "PC-006": 15.0, "PC-005": 1.0, "PC-012": 45.0},
}

STORM_RATE_PER_CLASS_PER_HOUR: dict[str, float] = {
    "TTC": 80.0,
    "SSTV": 40.0,
    "CODEC2_M17": 40.0,
}

def with_overridden_parameters(cfg: Config, overrides: dict[str, float]) -> Config:
    new_parameters = dict(cfg.parameters)
    for param_id, new_value in overrides.items():
        if param_id not in new_parameters:
            raise KeyError(f"{param_id} not present in {cfg.config_id}'s parameters")
        new_parameters[param_id] = dataclasses.replace(
            new_parameters[param_id], value=new_value
        )
    return dataclasses.replace(cfg, parameters=new_parameters)

@dataclasses.dataclass(frozen=True)
class ScenarioResult:
    label: str
    delivery_success_rate: float
    ttc_latency_p95_s: float | None
    energy_per_delivered_bit_j: float | None
    deadline_success_ratio: float = 0.0

def run_scenario(
    cfg: Config,
    overrides: dict[str, float],
    *,
    seed: int,
    duration_s: float,
    dt_s: float,
    ground_stations: tuple[tuple[float, float, float], ...] | None,
    rate_per_class_per_hour: dict[str, float] | None = None,
    label: str = "baseline",
) -> ScenarioResult:
    scenario_cfg = with_overridden_parameters(cfg, overrides) if overrides else cfg
    result = run_simulation(
        scenario_cfg, duration_s=duration_s, dt_s=dt_s, seed=seed,
        ground_stations=ground_stations, rate_per_class_per_hour=rate_per_class_per_hour,
    )

    priority_order = list(scenario_cfg.data_class_priority)
    arrivals = generate_arrivals(
        priority_order, duration_s, seed, rate_per_class_per_hour=rate_per_class_per_hour,
    )
    size_bytes_by_item = {item.id: item.size_bytes for _, item in arrivals}
    metrics = compute_metrics(
        result.deliveries,
        ttc_class_name=TTC_CLASS_NAME,
        priority_order=priority_order,
        size_bytes_by_item=size_bytes_by_item,
    )
    return ScenarioResult(
        label=label,
        delivery_success_rate=metrics.delivery_success_rate,
        ttc_latency_p95_s=metrics.ttc_latency_p95_s,
        energy_per_delivered_bit_j=metrics.energy_per_delivered_bit_j,
        deadline_success_ratio=metrics.deadline_success_ratio,
    )

STRESS_CASES: tuple[tuple[str, str, dict], ...] = (
    (
        "ST-1 depleted start",
        "initial SoC 25.2% (just above the 25% entry threshold) at the TLE "
        "epoch, which is in eclipse; single station",
        {"initial_soc_pct": 25.2},
    ),
    (
        "ST-2 aged battery, two stations",
        "battery capacity 1.5 Wh (1/3 of the 4.5 Wh reference), dual "
        "station (more transmit bursts per orbit)",
        {"battery_capacity_wh": 1.5, "ground_stations": GROUND_STATIONS_DUAL},
    ),
    (
        "ST-3 injected fault",
        "fault_count = 3 (= every config's latched-fault threshold) for "
        "1800 s starting at t = 8.35 h (inside the first pass); single station",
        {"fault_episodes": ((30_060.0, 31_860.0, 3),)},
    ),
)

@dataclasses.dataclass(frozen=True)
class StressResult:
    label: str
    safe_entries: int
    safe_exits: int
    first_entry_h: float | None
    first_exit_h: float | None
    safe_dwell_s: float
    min_soc_pct: float
    delivery_success_rate: float
    deadline_success_ratio: float
    energy_per_delivered_bit_j: float | None

def run_stress_case(
    cfg: Config, label: str, kwargs: dict, *, seed: int, duration_s: float, dt_s: float,
) -> StressResult:
    min_soc = [100.0]
    safe_ticks = [0]

    def _hook(t: float, snap: dict) -> None:
        min_soc[0] = min(min_soc[0], snap["battery_soc_pct"])
        safe_ticks[0] += snap["fsm_state_category"] == "safe"

    result = run_simulation(
        cfg, duration_s=duration_s, dt_s=dt_s, seed=seed, tick_hook=_hook, **kwargs,
    )
    safe = {sid for sid, st in cfg.states.items() if st.category == "safe"}
    entries, exits = [], []
    for e in result.decision_log:
        if e.kind != "transition":
            continue
        frm, to = e.details["from_state"], e.details["to_state"]
        if frm not in safe and to in safe:
            entries.append(e.now)
        elif frm in safe and to not in safe:
            exits.append(e.now)

    priority_order = list(cfg.data_class_priority)
    arrivals = generate_arrivals(priority_order, duration_s, seed)
    metrics = compute_metrics(
        result.deliveries, ttc_class_name=TTC_CLASS_NAME, priority_order=priority_order,
        size_bytes_by_item={item.id: item.size_bytes for _, item in arrivals},
    )
    return StressResult(
        label=label, safe_entries=len(entries), safe_exits=len(exits),
        first_entry_h=entries[0] / 3600.0 if entries else None,
        first_exit_h=exits[0] / 3600.0 if exits else None,
        safe_dwell_s=safe_ticks[0] * dt_s, min_soc_pct=min_soc[0],
        delivery_success_rate=metrics.delivery_success_rate,
        deadline_success_ratio=metrics.deadline_success_ratio,
        energy_per_delivered_bit_j=metrics.energy_per_delivered_bit_j,
    )

def _render_stress_section(stress_by_config: dict[str, list[StressResult]]) -> str:
    def _h(v: float | None) -> str:
        return "—" if v is None else f"{v:.2f}"

    lines = [
        "## Battery and fault stress cases (not the reference scenario)",
        "",
        "The reference scenario never reaches the 25% safe-mode entry "
        "threshold, so it never exercises SAFE_MODE. These cases perturb one "
        "sim-side quantity each (no config/*.yaml value changes) via "
        "sim.driver.run_simulation()'s stress knobs:",
        "",
    ]
    lines += [f"- **{label}**: {desc}." for label, desc, _ in STRESS_CASES]
    lines += [
        "",
        "| Config | Case | SAFE entries | SAFE exits | First entry (h) | First exit (h) | "
        "Time in SAFE (s) | Min SoC | Delivery success rate | Deadline success ratio | "
        "Energy per delivered bit (J/bit) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for config_id, results in stress_by_config.items():
        for r in results:
            lines.append(
                f"| {config_id} | {r.label} | {r.safe_entries} | {r.safe_exits} | "
                f"{_h(r.first_entry_h)} | {_h(r.first_exit_h)} | {r.safe_dwell_s:,.0f} | "
                f"{r.min_soc_pct:.2f}% | {r.delivery_success_rate * 100:.2f}% | "
                f"{r.deadline_success_ratio * 100:.2f}% | {_fmt_energy(r.energy_per_delivered_bit_j)} |"
            )
    lines += [
        "",
        "Reading the table. ST-1 and ST-3 give exactly one entry and one "
        "exit, and the exit shows the recovery model: Config A (P-014, 40%) "
        "and Config C (PC-012, 35%) recover autonomously, while Config B "
        "(ground-only, PB-010) waits for the next AOS (SIM-011). In ST-3 "
        "recovery is withheld until the injected fault clears. ST-2 enters "
        "SAFE_MODE inside passes and chatters: SIM-011 models ground as "
        "releasing SAFE_MODE at any in-pass tick regardless of SoC, so the "
        "next transmit burst re-triggers POWER_LOW within a tick or two. "
        "That is an artefact of the SIM-011 ground-operator assumption, not "
        "of the FSM; a SoC-aware ground release rule would remove it.",
        "",
    ]
    return "\n".join(lines)

def _fmt_energy(value: float | None) -> str:
    return "—" if value is None else f"{value:.6g}"

def _fmt_s(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"

def _render_config_section(
    config_id: str, results: tuple[ScenarioResult, ScenarioResult]
) -> str:
    baseline, worst = results
    lines = [
        f"## {config_id}",
        "",
        "| Scenario | Delivery success rate | Deadline success ratio | "
        "TT&C latency p95 (s) | Energy per delivered bit (J/bit) |",
        "|---|---|---|---|---|",
    ]
    for r in (baseline, worst):
        lines.append(
            f"| {r.label} | {r.delivery_success_rate * 100:.2f}% | "
            f"{r.deadline_success_ratio * 100:.2f}% | "
            f"{_fmt_s(r.ttc_latency_p95_s)} | {_fmt_energy(r.energy_per_delivered_bit_j)} |"
        )
    lines.append("")
    delta_pp = (worst.delivery_success_rate - baseline.delivery_success_rate) * 100.0
    lines.append(
        f"Compounding every individually-adverse parameter value, plus a "
        f"data-arrival storm, changes delivery success rate by "
        f"{delta_pp:+.2f} percentage points for {config_id} relative to "
        "baseline -- this is the honest floor a one-at-a-time sweep cannot "
        "show."
    )
    lines.append("")
    return "\n".join(lines)

def render_document(
    rows_by_config: dict[str, tuple[ScenarioResult, ScenarioResult]],
    stress_by_config: dict[str, list[StressResult]] | None = None,
) -> str:
    parts = [
        "<!-- Auto-generated by tools/generate_worst_case_scenarios.py. "
        "Do not hand-edit. -->",
        "",
        "# Worst-Case Scenario Analysis",
        "",
        "Phase 7B.2: Phase 7A.3's one-at-a-time sensitivity sweep varies "
        "exactly one Config-A/B parameter at a time. This analysis "
        "compounds every individually-adverse parameter value "
        "simultaneously (P-013/P-014/P-015 at the less-favorable end of "
        "their Phase 7A.3 range, P-019 included for completeness despite "
        "its documented null result), plus a data-arrival-rate storm on "
        "top -- see this module's docstring for the exact overrides and "
        "the direction rationale for each.",
        "",
    ]
    for config_id, results in rows_by_config.items():
        parts.append(_render_config_section(config_id, results))

    parts.append("## Interpretation")
    parts.append("")
    parts.append(
        "A one-at-a-time sweep can miss compounding effects: two "
        "individually-modest degradations can interact (e.g. a stricter "
        "elevation mask shortens each pass window at the same time a "
        "longer safe-mode dwell reduces how many passes are even reached "
        "in comms-mode) to produce a worse outcome than either alone would "
        "predict by simple addition. Reporting this combined scenario "
        "alongside the one-at-a-time sweep gives an honest worst-case "
        "floor for this project's headline delivery-success-rate claim, "
        "not just a set of independent single-parameter perturbations."
    )
    parts.append("")
    if stress_by_config:
        parts.append(_render_stress_section(stress_by_config))
    return "\n".join(parts)

def write_worst_case_scenarios(
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    *,
    seed: int = DEFAULT_SEED,
    duration_s: float = DEFAULT_DURATION_S,
    dt_s: float = DEFAULT_DT_S,
) -> None:
    rows_by_config: dict[str, tuple[ScenarioResult, ScenarioResult]] = {}
    stress_by_config: dict[str, list[StressResult]] = {}
    for config_id, config_path in CONFIG_PATHS:
        cfg = load_config(config_path)
        baseline = run_scenario(
            cfg, {}, seed=seed, duration_s=duration_s, dt_s=dt_s, ground_stations=None,
            label="baseline",
        )
        worst = run_scenario(
            cfg, WORST_CASE_OVERRIDES_BY_CONFIG[config_id], seed=seed, duration_s=duration_s,
            dt_s=dt_s, ground_stations=None,
            rate_per_class_per_hour=STORM_RATE_PER_CLASS_PER_HOUR, label="worst-case",
        )
        rows_by_config[config_id] = (baseline, worst)
        stress_by_config[config_id] = [
            run_stress_case(cfg, label, kwargs, seed=seed, duration_s=duration_s, dt_s=dt_s)
            for label, _, kwargs in STRESS_CASES
        ]
    Path(output_path).write_text(render_document(rows_by_config, stress_by_config))

def main() -> None:
    write_worst_case_scenarios(DEFAULT_OUTPUT_PATH)
    print(f"wrote {DEFAULT_OUTPUT_PATH}")

if __name__ == "__main__":
    main()
