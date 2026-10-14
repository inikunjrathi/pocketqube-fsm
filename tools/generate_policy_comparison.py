from __future__ import annotations

import math
import random
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sim.driver  # noqa: E402
from engine.config_loader import Config, load_config  # noqa: E402
from policy.base import BASELINE_POLICY, FEATURE_NAMES  # noqa: E402
from policy.bound import ScenarioBound, scenario_bound  # noqa: E402
from policy.oracle import ORACLE_HORIZON_S, OraclePolicy  # noqa: E402
from policy.tree import MAX_DEPTH, MIN_SAMPLES_LEAF, TreeNode, TreePolicy, export_text, fit  # noqa: E402
from sim.data_arrival import generate_arrivals  # noqa: E402
from sim.metrics import compute_metrics  # noqa: E402
from sim.power import draw_for_state_category  # noqa: E402
from sim.scenario import GROUND_STATIONS_DUAL  # noqa: E402
from tools.generate_worst_case_scenarios import (  # noqa: E402
    STORM_RATE_PER_CLASS_PER_HOUR,
    WORST_CASE_OVERRIDES_BY_CONFIG,
    with_overridden_parameters,
)

TTC_CLASS_NAME = "TTC"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = REPO_ROOT / "docs" / "policy-comparison-results.md"
CONFIG_PATHS = {
    "config-a": REPO_ROOT / "config" / "config-a.yaml",
    "config-b": REPO_ROOT / "config" / "config-b.yaml",
}

DEFAULT_DURATION_S = 172_800.0
DEFAULT_DT_S = 10.0
REFERENCE_SEED = 42
TRAIN_SEEDS: tuple[int, ...] = tuple(range(1000, 1020))
EVAL_SEEDS: tuple[int, ...] = tuple(range(6000, 6020))
SCENARIOS = ("reference", "worst-case", "two-station")
POLICY_NAMES = ("baseline-fifo", "baseline-edf", "lookahead", "tree")
BOOTSTRAP_RESAMPLES = 10_000
COMPARISONS = (
    ("baseline-edf", "baseline-fifo"),
    ("lookahead", "baseline-edf"),
    ("tree", "baseline-edf"),
    ("tree", "lookahead"),
)

def scenario_setup(cfg: Config, scenario: str) -> tuple[Config, dict]:
    if scenario == "reference":
        return cfg, {}
    if scenario == "worst-case":
        return (
            with_overridden_parameters(cfg, WORST_CASE_OVERRIDES_BY_CONFIG[cfg.config_id]),
            {"rate_per_class_per_hour": STORM_RATE_PER_CLASS_PER_HOUR},
        )
    if scenario == "two-station":
        return cfg, {"ground_stations": GROUND_STATIONS_DUAL}
    raise ValueError(f"unknown scenario {scenario!r}")

@lru_cache(maxsize=None)
def _scenario(config_id: str, scenario: str) -> tuple[Config, dict]:
    return scenario_setup(load_config(CONFIG_PATHS[config_id]), scenario)

def _fifo_key(item) -> float:
    return 0.0

@dataclass(frozen=True)
class RunResult:
    n_generated: int
    n_delivered: int
    n_on_time: int
    ttc_p95_s: float | None
    energy_per_bit_j: float | None
    n_decisions: int
    n_holds: int
    drawn_wh: float

    @property
    def window_delivery(self) -> float:
        return self.n_delivered / self.n_generated if self.n_generated else 0.0

    @property
    def deadline_success(self) -> float:
        return self.n_on_time / self.n_generated if self.n_generated else 0.0

def run_policy(
    config_id: str, scenario: str, policy_name: str, seed: int, *,
    duration_s: float = DEFAULT_DURATION_S, dt_s: float = DEFAULT_DT_S,
    tree: TreeNode | None = None, record: bool = False,
):
    cfg, kwargs = _scenario(config_id, scenario)
    if policy_name in ("baseline-fifo", "baseline-edf"):
        policy = BASELINE_POLICY
    elif policy_name == "lookahead":
        policy = OraclePolicy(kwargs.get("ground_stations"))
    elif policy_name == "tree":
        policy = TreePolicy(tree)
    else:
        raise ValueError(policy_name)

    rows: list[tuple[tuple[float, ...], str]] = []
    hook = lambda features, decision: rows.append((features.as_tuple(), decision))  # noqa: E731
    key = _fifo_key if policy_name == "baseline-fifo" else sim.driver._edf_key
    drawn = {"wh": 0.0, "state": None, "entered": 0.0}

    def tick_hook(t, snap):
        if drawn["state"] is not None:
            name = cfg.states[drawn["state"]].name
            drawn["wh"] += draw_for_state_category(name, t - drawn["entered"]) * dt_s / 3600.0
        if snap["fsm_state_id"] != drawn["state"]:
            drawn["state"], drawn["entered"] = snap["fsm_state_id"], t

    with mock.patch.object(sim.driver, "_edf_key", key):
        result = sim.driver.run_simulation(
            cfg, duration_s=duration_s, dt_s=dt_s, seed=seed, policy=policy,
            record_hook=hook, tick_hook=tick_hook, **kwargs,
        )
    arrivals = generate_arrivals(
        list(cfg.data_class_priority), duration_s, seed,
        rate_per_class_per_hour=kwargs.get("rate_per_class_per_hour"),
    )
    m = compute_metrics(
        result.deliveries, ttc_class_name=TTC_CLASS_NAME,
        priority_order=list(cfg.data_class_priority),
        size_bytes_by_item={item.id: item.size_bytes for _, item in arrivals},
    )
    res = RunResult(
        n_generated=len(result.deliveries),
        n_delivered=sum(d.delivered for d in result.deliveries),
        n_on_time=sum(d.delivered and not d.deadline_missed for d in result.deliveries),
        ttc_p95_s=m.ttc_latency_p95_s,
        energy_per_bit_j=m.energy_per_delivered_bit_j,
        n_decisions=len(rows),
        n_holds=sum(d == "hold" for _, d in rows),
        drawn_wh=drawn["wh"],
    )
    return (res, rows) if record else res

def _bound(config_id, scenario, seed, duration_s, dt_s) -> ScenarioBound:
    cfg, kwargs = _scenario(config_id, scenario)
    return scenario_bound(cfg, seed=seed, duration_s=duration_s, dt_s=dt_s, **kwargs)

def paired_bootstrap_ci(
    diffs: list[float], *, n_resamples: int = BOOTSTRAP_RESAMPLES, seed: int = 0,
) -> tuple[float, float, float]:
    n = len(diffs)
    mean = statistics.fmean(diffs)
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(diffs, k=n)) for _ in range(n_resamples))
    return mean, means[int(0.025 * n_resamples)], means[int(0.975 * n_resamples) - 1]

@dataclass
class Experiment:
    scenarios: tuple[str, ...]
    config_ids: tuple[str, ...]
    eval_seeds: tuple[int, ...]
    train_seeds: tuple[int, ...]
    duration_s: float
    dt_s: float
    results: dict = field(default_factory=dict)
    bounds: dict = field(default_factory=dict)
    trees: dict = field(default_factory=dict)
    train_stats: dict = field(default_factory=dict)

def run_experiment(
    *, scenarios=SCENARIOS, config_ids=("config-a", "config-b"),
    train_seeds=TRAIN_SEEDS, eval_seeds=EVAL_SEEDS, include_reference_seed=True,
    duration_s=DEFAULT_DURATION_S, dt_s=DEFAULT_DT_S, workers=None,
) -> Experiment:
    seeds = tuple(eval_seeds) + ((REFERENCE_SEED,) if include_reference_seed else ())
    assert not set(train_seeds) & set(seeds), "train/eval seeds must be disjoint"
    exp = Experiment(tuple(scenarios), tuple(config_ids), tuple(seeds),
                     tuple(train_seeds), duration_s, dt_s)
    kw = {"duration_s": duration_s, "dt_s": dt_s}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        train_f = {
            (s, c, seed): pool.submit(run_policy, c, s, "lookahead", seed, record=True, **kw)
            for s in scenarios for c in config_ids for seed in train_seeds
        }
        eval_f = {
            (s, c, p, seed): pool.submit(run_policy, c, s, p, seed, **kw)
            for s in scenarios for c in config_ids for seed in seeds
            for p in POLICY_NAMES if p != "tree"
        }
        bound_f = {
            (s, c, seed): pool.submit(_bound, c, s, seed, duration_s, dt_s)
            for s in scenarios for c in config_ids for seed in seeds
        }
        for s in scenarios:
            rows = [row for (s2, _, _), f in train_f.items() if s2 == s for row in f.result()[1]]
            exp.trees[s] = fit(rows)
            exp.train_stats[s] = (len(rows), sum(lab == "hold" for _, lab in rows))
        tree_f = {
            (s, c, "tree", seed): pool.submit(run_policy, c, s, "tree", seed, tree=exp.trees[s], **kw)
            for s in scenarios for c in config_ids for seed in seeds
        }
        exp.results = {k: f.result() for k, f in {**eval_f, **tree_f}.items()}
        exp.bounds = {k: f.result() for k, f in bound_f.items()}
    return exp

_METRICS = (
    ("Window delivery", lambda r: r.window_delivery, lambda v: f"{v * 100:.2f}%", None),
    ("Deadline success", lambda r: r.deadline_success, lambda v: f"{v * 100:.2f}%", None),
    ("TT&C p95 latency (s)", lambda r: r.ttc_p95_s, lambda v: f"{v:,.1f}", None),
    ("Energy/bit (J/bit)", lambda r: r.energy_per_bit_j, lambda v: f"{v:.4g}", None),
    ("Energy drawn (Wh)", lambda r: r.drawn_wh, lambda v: f"{v:.4f}", {"config-a"}),
)

def _metrics_for(config_id):
    return [m for m in _METRICS if m[3] is None or config_id in m[3]]

def _render_summary(exp: Experiment, s: str, c: str) -> list[str]:
    seeds = [x for x in exp.eval_seeds if x != REFERENCE_SEED]
    metrics = _metrics_for(c)
    head = "| Policy | " + " | ".join(f"{m[0]} mean [95% CI]" for m in metrics) + " | Holds/decisions |"
    lines = [head, "|---" * (len(metrics) + 2) + "|"]
    for p in POLICY_NAMES:
        runs = [exp.results[(s, c, p, x)] for x in seeds]
        cells = []
        for _, get, fmt, _ in metrics:
            vals = [get(r) for r in runs if get(r) is not None]
            if not vals:
                cells.append("--")
                continue
            mean, lo, hi = paired_bootstrap_ci(vals)
            cells.append(f"{fmt(mean)} [{fmt(lo)}, {fmt(hi)}]")
        holds = sum(r.n_holds for r in runs)
        decisions = sum(r.n_decisions for r in runs)
        lines.append(f"| {p} | " + " | ".join(cells) + f" | {holds}/{decisions} |")
    b = [exp.bounds[(s, c, x)] for x in seeds]
    w = statistics.fmean(x.window_bound / x.n_generated for x in b)
    d = statistics.fmean(x.deadline_bound / x.n_generated for x in b)
    lines.append(f"| *relaxation bound* | {w * 100:.2f}% | {d * 100:.2f}% |"
                 + " -- |" * (len(metrics) - 2) + " -- |")
    return lines

def _render_legacy_tables(exp: Experiment) -> list[str]:
    if "reference" not in exp.scenarios or REFERENCE_SEED not in exp.eval_seeds:
        return []
    names = (("baseline", "baseline-edf"), ("oracle", "lookahead"), ("tree", "tree"))
    seeds = [x for x in exp.eval_seeds if x != REFERENCE_SEED]
    out = [f"## Reference scenario, seed {REFERENCE_SEED} (paper table)", "",
           "In the two tables below \"oracle\" is the lookahead policy (label kept "
           "for tools/export_visualization_data.py) and \"baseline\" is "
           "baseline-edf.", "",
           "| Config | Policy | Delivery success | TT&C latency p95 (s) | Energy/bit (J/bit) |",
           "|---|---|---|---|---|"]
    for c in exp.config_ids:
        for shown, p in names:
            r = exp.results[("reference", c, p, REFERENCE_SEED)]
            p95 = "—" if r.ttc_p95_s is None else f"{r.ttc_p95_s:.3f}"
            e = "—" if r.energy_per_bit_j is None else f"{r.energy_per_bit_j:.6g}"
            out.append(f"| {c} | {shown} | {r.window_delivery * 100:.2f}% | {p95} | {e} |")
    out += ["", f"Reference scenario over the {len(seeds)} evaluation seeds "
            "(bootstrap 95% CI of the mean):", "",
            "| Config | Policy | Delivery success (mean, 95% CI) | Energy/bit (mean, 95% CI) |",
            "|---|---|---|---|"]
    for c in exp.config_ids:
        for shown, p in names:
            runs = [exp.results[("reference", c, p, x)] for x in seeds]
            cells = []
            for vals in ([r.window_delivery for r in runs],
                         [r.energy_per_bit_j for r in runs if r.energy_per_bit_j is not None]):
                m, lo, hi = paired_bootstrap_ci(vals)
                cells.append(f"{m:.6g} (n={len(vals)}, 95% CI [{lo:.6g}, {hi:.6g}])")
            out.append(f"| {c} | {shown} | {cells[0]} | {cells[1]} |")
    return out + [""]

def _render_paired(exp: Experiment, s: str, c: str) -> list[str]:
    seeds = [x for x in exp.eval_seeds if x != REFERENCE_SEED]
    lines = ["| Comparison | Metric | Mean paired diff | 95% bootstrap CI | A better / tie / B better |",
             "|---|---|---|---|---|"]
    for a, b in COMPARISONS:
        for label, get, fmt, _ in _metrics_for(c):
            pairs = [(get(exp.results[(s, c, a, x)]), get(exp.results[(s, c, b, x)])) for x in seeds]
            diffs = [va - vb for va, vb in pairs if va is not None and vb is not None]
            if not diffs:
                continue
            lower_is_better = "latency" in label or "Energy" in label
            better = sum((d < 0) if lower_is_better else (d > 0) for d in diffs)
            worse = sum((d > 0) if lower_is_better else (d < 0) for d in diffs)
            mean, lo, hi = paired_bootstrap_ci(diffs)
            if "%" in fmt(0.5):
                g = lambda v: f"{v * 100:+.3f} pp"  # noqa: E731
            elif "latency" in label:
                g = lambda v: f"{v:+.1f} s"  # noqa: E731
            else:
                g = lambda v: f"{v:+.3g}"  # noqa: E731
            lines.append(f"| {a} - {b} | {label} | {g(mean)} | [{g(lo)}, {g(hi)}] | "
                         f"{better} / {len(diffs) - better - worse} / {worse} (n={len(diffs)}) |")
    return lines

def _render_per_seed(exp: Experiment, s: str, c: str) -> list[str]:
    short = {"baseline-fifo": "FIFO", "baseline-edf": "EDF", "lookahead": "LA", "tree": "Tree"}
    P = POLICY_NAMES

    def table(cols, row_fn):
        out = ["| " + " | ".join(cols) + " |", "|---" * len(cols) + "|"]
        for x in exp.eval_seeds:
            r = {p: exp.results[(s, c, p, x)] for p in P}
            label = str(x) + (" (ref)" if x == REFERENCE_SEED else "")
            out.append("| " + " | ".join([label, *row_fn(x, r)]) + " |")
        return out

    def counts(x, r):
        b = exp.bounds[(s, c, x)]
        return [str(b.n_generated), str(b.window_bound), *(str(r[p].n_delivered) for p in P),
                str(b.deadline_bound), *(str(r[p].n_on_time) for p in P)]

    def other(x, r):
        return [*("--" if r[p].ttc_p95_s is None else f"{r[p].ttc_p95_s:.0f}" for p in P),
                *("--" if r[p].energy_per_bit_j is None else f"{r[p].energy_per_bit_j:.4g}" for p in P),
                *(f"{r[p].drawn_wh:.3f}" if c == "config-a" else "--" for p in P),
                *(str(r[p].n_holds) for p in ("lookahead", "tree"))]

    c1 = ["Seed", "Gen", "Bound W", *(f"{short[p]} W" for p in P),
          "Bound D", *(f"{short[p]} D" for p in P)]
    c2 = ["Seed", *(f"{short[p]} p95 (s)" for p in P), *(f"{short[p]} J/bit" for p in P),
          *(f"{short[p]} Wh" for p in P), "LA holds", "Tree holds"]
    return [*table(c1, counts), "", *table(c2, other)]

def render_document(exp: Experiment) -> str:
    n_eval = len([x for x in exp.eval_seeds if x != REFERENCE_SEED])
    parts = [
        "<!-- Auto-generated by tools/generate_policy_comparison.py. Do not hand-edit. -->",
        "",
        "# Policy Comparison Results (RQ3)",
        "",
        "Four serve/hold policies on paired seeds (identical arrivals for every "
        "policy at a given scenario and seed):",
        "",
        "- **baseline-fifo**: always serve, within-class order = queue insertion "
        "order (a deferred item re-enters at the back of its class).",
        "- **baseline-edf**: always serve, within-class order = earliest deadline "
        "first. This is the repo's BASELINE_POLICY; sim/driver.py applies EDF to "
        "every policy, so the previously reported \"baseline\" was already this one.",
        f"- **lookahead** (code: OraclePolicy, formerly called \"oracle\"): rolls "
        f"the simulator forward {ORACLE_HORIZON_S:.0f} s under serve and under hold, "
        "with a serve-when-possible EDF tail, and picks the better lexicographic "
        "score. A heuristic, not an upper bound.",
        f"- **tree**: CART, Gini splits, max depth {MAX_DEPTH}, min {MIN_SAMPLES_LEAF} "
        "samples per leaf, trained per scenario on the lookahead policy's "
        "(features, action) pairs from both configs.",
        "",
        f"Seeds: training {exp.train_seeds[0]}-{exp.train_seeds[-1]} "
        f"({len(exp.train_seeds)} seeds); evaluation "
        f"{', '.join(str(x) for x in exp.eval_seeds if x != REFERENCE_SEED)} "
        f"({n_eval} seeds; disjoint from training). Seed {REFERENCE_SEED} (the "
        "paper's single-seed run) is shown in the per-seed tables but excluded "
        f"from the means. Duration {exp.duration_s:.0f} s, dt {exp.dt_s:g} s.",
        "",
        "Metrics: window delivery = delivered by end of run / generated; deadline "
        "success = delivered at a tick t <= deadline / generated; TT&C p95 latency "
        "over delivered TT&C items; energy per delivered bit as sim/metrics.py "
        "attributes it (each item is charged its transmit-time slice of the "
        "draw at delivery) and, for Config A only, total load energy drawn over "
        "the run (what the battery pays), both under decision 0009's transmit-class power "
        "mapping (sim/power.py), which the lookahead rollout now also uses. CIs: percentile bootstrap, "
        f"{BOOTSTRAP_RESAMPLES} resamples, over the {n_eval} evaluation seeds.",
        "",
        "Relaxation bound (policy/bound.py): an offline clairvoyant schedule that "
        "knows every arrival and link-up tick, keeps only the per-tick link "
        "budget, and drops power, safe mode, FSM, priority order and "
        "non-preemption. No policy can exceed it. Window bound is exact for that "
        "relaxation (Moore-Hodgson); deadline bound is the floored fluid optimum.",
        "",
        *_render_legacy_tables(exp),
        "## Multi-seed statistical treatment",
        "",
    ]
    for s in exp.scenarios:
        for c in exp.config_ids:
            parts += [f"### {s} / {c}", "", *_render_summary(exp, s, c), "",
                      "Paired differences (A - B, same seed):", "",
                      *_render_paired(exp, s, c), ""]
    parts += ["## RQ3 answer", "", _rq3_verdict(exp), "", "## Learned trees", ""]
    parts.append("Features (in order): " + ", ".join(f"`{n}`" for n in FEATURE_NAMES) + ".")
    parts.append("")
    for s in exp.scenarios:
        n_rows, n_holds = exp.train_stats[s]
        parts += [f"### {s}", "", f"{n_rows} training rows, {n_holds} labelled hold.", "",
                  "```", export_text(exp.trees[s]).rstrip(), "```", ""]
    parts += ["## Per-seed results", "",
              "Counts of items. W = delivered by end of run, D = delivered by deadline.", ""]
    for s in exp.scenarios:
        for c in exp.config_ids:
            parts += [f"### {s} / {c}", "", *_render_per_seed(exp, s, c), ""]
    return "\n".join(parts)

def _rq3_verdict(exp: Experiment) -> str:
    seeds = [x for x in exp.eval_seeds if x != REFERENCE_SEED]
    out = []
    for s in exp.scenarios:
        for c in exp.config_ids:
            diffs = [exp.results[(s, c, "tree", x)].window_delivery
                     - exp.results[(s, c, "baseline-edf", x)].window_delivery for x in seeds]
            mean, lo, hi = paired_bootstrap_ci(diffs)
            verdict = "beats" if lo > 0 else "loses to" if hi < 0 else "ties"
            out.append(f"{s}/{c}: tree {verdict} baseline-edf on window delivery "
                       f"({mean * 100:+.3f} pp, CI [{lo * 100:+.3f}, {hi * 100:+.3f}])")
    return "; ".join(out) + "."

def write_policy_comparison(output_path: str | Path = DEFAULT_OUTPUT_PATH, **kwargs) -> Experiment:
    exp = run_experiment(**kwargs)
    Path(output_path).write_text(render_document(exp))
    return exp

COMPLEXITY_DOC = REPO_ROOT / "docs" / "policy-complexity-analysis.md"
_SECTION_MARK = "<!-- same-input benchmark (tools/generate_policy_comparison.py) -->"

def append_same_input_benchmark(tree: TreeNode, path: Path = COMPLEXITY_DOC) -> str:
    from tools.benchmark_policies import benchmark_policies, render_same_input_section

    timings = {cid: benchmark_policies(load_config(p), TreePolicy(tree))
               for cid, p in CONFIG_PATHS.items()}
    section = render_same_input_section(timings)
    text = path.read_text()
    text = text.split(_SECTION_MARK)[0].rstrip() + "\n\n" + _SECTION_MARK + "\n\n" + section
    path.write_text(text)
    return section

def main() -> None:
    exp = write_policy_comparison(DEFAULT_OUTPUT_PATH)
    print(f"wrote {DEFAULT_OUTPUT_PATH}")
    append_same_input_benchmark(exp.trees["reference"])
    print(f"updated {COMPLEXITY_DOC}")

if __name__ == "__main__":
    main()
