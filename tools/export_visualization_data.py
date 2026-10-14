from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.config_loader import Config, load_config  # noqa: E402
from sim.driver import run_simulation  # noqa: E402
from tools.generate_baseline_results import (  # noqa: E402
    DEFAULT_DT_S,
    DEFAULT_DURATION_S,
    DEFAULT_SEED,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

_AUTONOMOUS_RECOVERY_PARAM_NAME = "battery_soc_safe_mode_recovery_threshold_pct"

FAULT_INJECTION_TEST_FILES = (
    "tests/test_fault_injection.py",
    "tests/test_latch_fuzz.py",
    "tests/test_persistence.py",
)

def build_rq1_data(config_a: Config, config_b: Config) -> dict:

    def _summarize(cfg: Config) -> dict:
        param_names = {p.name for p in cfg.parameters.values()}
        return {
            "config_id": cfg.config_id,
            "name": cfg.name,
            "description": cfg.description,
            "state_count": len(cfg.states),
            "event_count": len(cfg.events),
            "transition_count": len(cfg.transitions),
            "autonomous_recovery_capable": _AUTONOMOUS_RECOVERY_PARAM_NAME in param_names,
        }

    return {"configs": [_summarize(config_a), _summarize(config_b)]}

def compute_rq2_data() -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *FAULT_INJECTION_TEST_FILES],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    summary_line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    passed_match = re.search(r"(\d+) passed", summary_line)
    if passed_match is None:
        raise RuntimeError(
            f"could not parse pytest summary line for RQ2 data: {summary_line!r}\n"
            f"full stdout:\n{result.stdout}\nfull stderr:\n{result.stderr}"
        )
    failed_match = re.search(r"(\d+) failed", summary_line)
    return {
        "test_files": list(FAULT_INJECTION_TEST_FILES),
        "passed": int(passed_match.group(1)),
        "failed": int(failed_match.group(1)) if failed_match else 0,
    }

def build_rq3_data() -> dict:
    path = REPO_ROOT / "docs" / "policy-comparison-results.md"
    text = path.read_text()
    lines = text.splitlines()

    rows: list[dict] = []
    in_table = False
    for line in lines:
        if not rows and line.startswith("| Config | Policy |"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("|---"):
            continue
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 5:
            raise RuntimeError(f"unexpected RQ3 table row shape in {path}: {line!r}")
        config_id, policy, delivery_pct, latency_s, energy_j = cells
        rows.append({
            "config_id": config_id,
            "policy": policy,
            "delivery_success_pct": float(delivery_pct.rstrip("%")),
            "ttc_latency_p95_s": None if latency_s == "—" else float(latency_s),
            "energy_per_bit_j": None if energy_j == "—" else float(energy_j),
        })
    if len(rows) != 6:
        raise RuntimeError(
            f"expected 6 RQ3 rows (2 configs x 3 policies) in {path}, got {len(rows)}"
        )

    answer_match = re.search(r"## RQ3 answer\n\n(.+?)(?:\n\n## |\Z)", text, re.DOTALL)
    if answer_match is None:
        raise RuntimeError(f"could not find '## RQ3 answer' section in {path}")

    return {"rows": rows, "answer": answer_match.group(1).strip()}

_CI_VALUE_RE = re.compile(
    r"^([-\d.eE+]+)\s*\(n=(\d+),\s*95% CI \[([-\d.eE+]+),\s*([-\d.eE+]+)\]\)$"
)

def _parse_ci_value(cell: str) -> dict:
    match = _CI_VALUE_RE.match(cell.strip())
    if not match:
        raise RuntimeError(f"unexpected CI-value cell shape: {cell!r}")
    return {
        "mean": float(match.group(1)),
        "n": int(match.group(2)),
        "ci_low": float(match.group(3)),
        "ci_high": float(match.group(4)),
    }

def build_multi_seed_baseline_data() -> dict:
    path = REPO_ROOT / "docs" / "baseline-results.md"
    lines = path.read_text().splitlines()

    header_re = re.compile(r"^### Config (\S+) .*multi-seed \((\d+) seeds\)$")
    configs: list[dict] = []
    current_config_id = None
    current_n_seeds = None
    current_metrics: dict = {}
    in_table = False

    def _flush() -> None:
        if current_config_id is not None and current_config_id in (
            "config-a", "config-b",
        ):
            configs.append({
                "config_id": current_config_id,
                "n_seeds": current_n_seeds,
                "metrics": dict(current_metrics),
            })

    for line in lines:
        header_match = header_re.match(line)
        if header_match:
            _flush()
            current_config_id = header_match.group(1)
            current_n_seeds = int(header_match.group(2))
            current_metrics = {}
            in_table = False
            continue
        if line == "| Metric | Mean (95% CI) |":
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("|---"):
            continue
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 2:
            raise RuntimeError(f"unexpected multi-seed baseline row shape in {path}: {line!r}")
        metric_name, value_cell = cells
        current_metrics[metric_name] = _parse_ci_value(value_cell)
    _flush()

    if len(configs) != 2:
        raise RuntimeError(f"expected 2 multi-seed baseline sections in {path}, got {len(configs)}")
    return {"configs": configs}

def build_multi_seed_policy_data() -> dict:
    path = REPO_ROOT / "docs" / "policy-comparison-results.md"
    lines = path.read_text().splitlines()

    rows: list[dict] = []
    in_table = False
    for line in lines:
        if line == "| Config | Policy | Delivery success (mean, 95% CI) | Energy/bit (mean, 95% CI) |":
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("|---"):
            continue
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 4:
            raise RuntimeError(f"unexpected multi-seed policy row shape in {path}: {line!r}")
        config_id, policy, delivery_cell, energy_cell = cells
        rows.append({
            "config_id": config_id,
            "policy": policy,
            "delivery_success": _parse_ci_value(delivery_cell),
            "energy_per_bit_j": _parse_ci_value(energy_cell),
        })
    if len(rows) != 6:
        raise RuntimeError(f"expected 6 multi-seed policy rows in {path}, got {len(rows)}")
    return {"rows": rows}

def build_complexity_data() -> dict:
    path = REPO_ROOT / "docs" / "policy-complexity-analysis.md"
    lines = path.read_text().splitlines()

    config_header_re = re.compile(r"^## Config (\S+)$")
    ratio_re = re.compile(r"~([\d,]+)x the tree's mean")
    configs: list[dict] = []
    current_config_id = None
    current_policies: list[dict] = []
    current_ratio = None
    in_table = False

    def _flush() -> None:
        if current_config_id is not None:
            configs.append({
                "config_id": current_config_id,
                "policies": list(current_policies),
                "oracle_to_tree_ratio": current_ratio,
            })

    for line in lines:
        header_match = config_header_re.match(line)
        if header_match:
            _flush()
            current_config_id = header_match.group(1)
            current_policies = []
            current_ratio = None
            in_table = False
            continue
        ratio_match = ratio_re.search(line)
        if ratio_match:
            current_ratio = int(ratio_match.group(1).replace(",", ""))
        if line == "| Policy | Big-O | Mean | Stdev | Min | Max | N |":
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("|---"):
            continue
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 7:
            raise RuntimeError(f"unexpected complexity table row shape in {path}: {line!r}")
        policy, big_o, mean, stdev, min_v, max_v, n = cells
        current_policies.append({
            "policy": policy, "big_o": big_o, "mean": mean, "stdev": stdev,
            "min": min_v, "max": max_v, "n": int(n),
        })
    _flush()

    if len(configs) != 2:
        raise RuntimeError(f"expected 2 complexity sections in {path}, got {len(configs)}")
    return {"configs": configs}

def build_sensitivity_data() -> dict:
    path = REPO_ROOT / "docs" / "sensitivity-analysis.md"
    lines = path.read_text().splitlines()

    param_header_re = re.compile(r"^## (P-\d+) `(\w+)`")
    section_stop_re = re.compile(
        r"^## (Interpretation|Parameters excluded from this sweep|Power-model uncertainty)"
    )
    parameters: list[dict] = []
    current_param_id = None
    current_param_name = None
    current_note = None
    current_rows: list[dict] = []
    in_table = False

    def _flush() -> None:
        if current_param_id is not None:
            parameters.append({
                "param_id": current_param_id,
                "param_name": current_param_name,
                "note": current_note,
                "rows": list(current_rows),
            })

    for line in lines:
        if section_stop_re.match(line):
            _flush()
            current_param_id = None
            in_table = False
            continue
        header_match = param_header_re.match(line)
        if header_match:
            _flush()
            current_param_id = header_match.group(1)
            current_param_name = header_match.group(2)
            current_note = None
            current_rows = []
            in_table = False
            continue
        if line.startswith("**Note:**"):
            current_note = line[len("**Note:** "):]
            continue
        if line == "| Value | Delivery success rate | Energy per delivered bit (J/bit) |":
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("|---"):
            continue
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 3:
            raise RuntimeError(f"unexpected sensitivity table row shape in {path}: {line!r}")
        value_cell, delivery_cell, energy_cell = cells
        current_rows.append({
            "value": value_cell.replace(" (baseline)", ""),
            "is_baseline": "(baseline)" in value_cell,
            "delivery_success_pct": float(delivery_cell.rstrip("%")),
            "energy_per_bit_j": None if energy_cell == "—" else float(energy_cell),
        })
    _flush()

    if len(parameters) != 4:
        raise RuntimeError(f"expected 4 swept parameters in {path}, got {len(parameters)}")

    interpretation = {}
    for param in parameters:
        rates = {r["delivery_success_pct"] for r in param["rows"]}
        interpretation[param["param_id"]] = (
            "real sensitivity" if len(rates) > 1 else "no movement"
        )

    return {"parameters": parameters, "interpretation": interpretation}

def build_power_uncertainty_data() -> dict:
    path = REPO_ROOT / "docs" / "sensitivity-analysis.md"
    lines = path.read_text().splitlines()

    class_header_re = re.compile(r"^### (\w+)$")
    range_re = re.compile(r"^Range: \[([-\d.eE+]+), ([-\d.eE+]+)\] J/bit")
    classes: list[dict] = []
    current_class = None
    current_rows: list[dict] = []
    current_range = None
    in_table = False
    in_section = False

    def _flush() -> None:
        if current_class is not None:
            classes.append({
                "data_class": current_class,
                "rows": list(current_rows),
                "range_low": current_range[0] if current_range else None,
                "range_high": current_range[1] if current_range else None,
            })

    for line in lines:
        if line.startswith("## Power-model uncertainty"):
            in_section = True
            continue
        if not in_section:
            continue
        header_match = class_header_re.match(line)
        if header_match:
            _flush()
            current_class = header_match.group(1)
            current_rows = []
            current_range = None
            in_table = False
            continue
        range_match = range_re.match(line)
        if range_match:
            current_range = (float(range_match.group(1)), float(range_match.group(2)))
            continue
        if line == "| Ratio (x TTC draw) | Draw (W) | Energy per delivered bit (J/bit) |":
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("|---"):
            continue
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 3:
            raise RuntimeError(f"unexpected power-uncertainty row shape in {path}: {line!r}")
        ratio, draw_w, energy = cells
        current_rows.append({
            "ratio": float(ratio), "draw_w": float(draw_w), "energy_per_bit_j": float(energy),
        })
    _flush()

    if len(classes) != 2:
        raise RuntimeError(f"expected 2 power-uncertainty classes in {path}, got {len(classes)}")
    return {"classes": classes}

def build_model_checking_data() -> dict:
    path = REPO_ROOT / "docs" / "model-checking.md"
    lines = path.read_text().splitlines()

    header = "| Config | States (declared) | Distinct (`pc`, latch) states reached | Max search depth | Result |"
    rows: list[dict] = []
    in_table = False
    for line in lines:
        if line == header:
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("|---"):
            continue
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 5:
            raise RuntimeError(f"unexpected model-checking row shape in {path}: {line!r}")
        config_id, states_declared, states_reached, max_depth, result = cells
        rows.append({
            "config_id": config_id,
            "states_declared": int(states_declared),
            "states_reached": int(states_reached),
            "max_depth": int(max_depth),
            "result": result,
        })
    if len(rows) != 2:
        raise RuntimeError(f"expected 2 model-checking rows in {path}, got {len(rows)}")
    return {"rows": rows}

def build_replay_data(cfg: Config, *, seed: int, duration_s: float, dt_s: float) -> dict:
    ticks: list[dict] = []

    def _tick_hook(t: float, snapshot: dict) -> None:
        ticks.append({"t": t, **snapshot})

    result = run_simulation(
        cfg, duration_s=duration_s, dt_s=dt_s, seed=seed, tick_hook=_tick_hook,
    )
    deliveries = [
        {
            "item_id": d.item_id,
            "data_class": d.data_class,
            "arrival_time_s": d.arrival_time_s,
            "delivered": d.delivered,
            "delivery_time_s": d.delivery_time_s,
            "latency_s": d.latency_s,
            "deadline_missed": d.deadline_missed,
        }
        for d in result.deliveries
    ]
    return {
        "config_id": cfg.config_id,
        "duration_s": duration_s,
        "dt_s": dt_s,
        "seed": seed,
        "ticks": ticks,
        "deliveries": deliveries,
    }

TEMPLATE_PATH = REPO_ROOT / "tools" / "templates" / "visualization_template.html"
DATA_PLACEHOLDER = "__DATA_JSON_PLACEHOLDER__"
DEFAULT_DATA_OUTPUT_PATH = REPO_ROOT / "report" / "visualization" / "data.json"
DEFAULT_HTML_OUTPUT_PATH = REPO_ROOT / "report" / "visualization" / "index.html"

def build_visualization_data(
    *, seed: int = DEFAULT_SEED, duration_s: float = DEFAULT_DURATION_S, dt_s: float = DEFAULT_DT_S,
) -> dict:
    config_a = load_config(REPO_ROOT / "config" / "config-a.yaml")
    config_b = load_config(REPO_ROOT / "config" / "config-b.yaml")
    return {
        "replay": build_replay_data(config_a, seed=seed, duration_s=duration_s, dt_s=dt_s),
        "rq1": build_rq1_data(config_a, config_b),
        "rq2": compute_rq2_data(),
        "rq3": build_rq3_data(),
        "multi_seed_baseline": build_multi_seed_baseline_data(),
        "multi_seed_policy": build_multi_seed_policy_data(),
        "complexity": build_complexity_data(),
        "sensitivity": build_sensitivity_data(),
        "power_uncertainty": build_power_uncertainty_data(),
        "model_checking": build_model_checking_data(),
    }

def render_html(data: dict) -> str:
    template = TEMPLATE_PATH.read_text()
    if DATA_PLACEHOLDER not in template:
        raise RuntimeError(f"template {TEMPLATE_PATH} is missing the {DATA_PLACEHOLDER!r} placeholder")
    return template.replace(DATA_PLACEHOLDER, json.dumps(data))

def write_visualization_data(
    *,
    data_output_path: str | Path = DEFAULT_DATA_OUTPUT_PATH,
    html_output_path: str | Path = DEFAULT_HTML_OUTPUT_PATH,
    seed: int = DEFAULT_SEED,
    duration_s: float = DEFAULT_DURATION_S,
    dt_s: float = DEFAULT_DT_S,
) -> None:
    data = build_visualization_data(seed=seed, duration_s=duration_s, dt_s=dt_s)
    Path(data_output_path).write_text(json.dumps(data, indent=2))
    Path(html_output_path).write_text(render_html(data))

def main() -> None:
    write_visualization_data()
    print(f"wrote {DEFAULT_DATA_OUTPUT_PATH}")
    print(f"wrote {DEFAULT_HTML_OUTPUT_PATH}")

if __name__ == "__main__":
    main()
