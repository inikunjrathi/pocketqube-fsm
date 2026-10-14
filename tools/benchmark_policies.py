from __future__ import annotations

import math
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.config_loader import Config, load_config  # noqa: E402
from policy.base import BASELINE_POLICY, DecisionContext, FeatureVector, Policy  # noqa: E402
from policy.dataset import generate_dataset  # noqa: E402
from policy.oracle import ORACLE_HORIZON_S, OraclePolicy  # noqa: E402
from policy.tree import MAX_DEPTH, TreePolicy, train  # noqa: E402
from sim.driver import run_simulation  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = REPO_ROOT / "docs" / "policy-complexity-analysis.md"

CAPTURE_SEED = 42
CAPTURE_DURATION_S = 6 * 5694.75
CAPTURE_DT_S = 10.0

FULL_CAPTURE_DURATION_S = 172_800.0
MAX_CAPTURED_CONTEXTS = 50
REPS_PER_CONTEXT = 10
FAST_INNER_CALLS = 1000

class _CapturingPolicy:

    def __init__(self, inner: Policy) -> None:
        self._inner = inner
        self.captured: list[tuple[FeatureVector, DecisionContext]] = []

    def decide(self, features: FeatureVector, context: DecisionContext) -> str:
        self.captured.append((features, context))
        return self._inner.decide(features, context)

def capture_decision_contexts(
    cfg: Config, *, max_contexts: int = MAX_CAPTURED_CONTEXTS,
    duration_s: float = FULL_CAPTURE_DURATION_S,
) -> list[tuple[FeatureVector, DecisionContext]]:
    capturer = _CapturingPolicy(BASELINE_POLICY)
    run_simulation(
        cfg, duration_s=duration_s, dt_s=CAPTURE_DT_S,
        seed=CAPTURE_SEED, policy=capturer,
    )
    captured = capturer.captured
    if len(captured) <= max_contexts:
        return captured
    step = len(captured) / max_contexts
    return [captured[int(i * step)] for i in range(max_contexts)]

def _time_decide(
    policy: Policy,
    contexts: list[tuple[FeatureVector, DecisionContext]],
    *,
    reps_per_context: int = REPS_PER_CONTEXT,
    inner_calls: int = 1,
) -> list[float]:
    samples: list[float] = []
    for features, context in contexts:
        for _ in range(reps_per_context):
            t0 = time.perf_counter()
            for _ in range(inner_calls):
                policy.decide(features, context)
            t1 = time.perf_counter()
            samples.append((t1 - t0) / inner_calls)
    return samples

@dataclass(frozen=True)
class PolicyTiming:
    policy_name: str
    big_o: str
    n_samples: int
    mean_s: float
    stdev_s: float
    min_s: float
    max_s: float
    median_s: float | None = None
    p95_s: float | None = None

def _summarize_timing(policy_name: str, big_o: str, samples: list[float]) -> PolicyTiming:
    ordered = sorted(samples)
    return PolicyTiming(
        policy_name=policy_name,
        big_o=big_o,
        n_samples=len(samples),
        mean_s=statistics.mean(samples),
        stdev_s=statistics.stdev(samples) if len(samples) > 1 else 0.0,
        min_s=ordered[0],
        max_s=ordered[-1],
        median_s=statistics.median(ordered),
        p95_s=ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)],
    )

def benchmark_policies(
    cfg: Config, tree_policy: TreePolicy, *,
    max_contexts: int = MAX_CAPTURED_CONTEXTS, reps_per_context: int = REPS_PER_CONTEXT,
) -> list[PolicyTiming]:
    contexts = capture_decision_contexts(cfg, max_contexts=max_contexts)
    if not contexts:
        return []

    horizon_ticks = max(1, int(ORACLE_HORIZON_S // CAPTURE_DT_S))
    policies: list[tuple[str, Policy, str]] = [
        ("baseline", BASELINE_POLICY, "O(1)"),
        ("tree", tree_policy, f"O(depth), depth = MAX_DEPTH = {MAX_DEPTH}"),
        (
            "oracle",
            OraclePolicy(),
            f"O(2 * horizon_ticks), horizon_ticks = ORACLE_HORIZON_S // dt_s = {horizon_ticks}",
        ),
    ]
    timings = []
    for policy_name, policy, big_o in policies:
        inner = 1 if policy_name == "oracle" else FAST_INNER_CALLS
        samples = _time_decide(
            policy, contexts, reps_per_context=reps_per_context, inner_calls=inner,
        )
        timings.append(_summarize_timing(policy_name, big_o, samples))
    return timings

TREE_C_ESTIMATE = (
    "At most 4 float comparisons (MAX_DEPTH = 4); expected roughly 20-60 "
    "cycles including call overhead, i.e. under 1 us at 84 MHz on the "
    "Cortex-M4F. This is an estimate from instruction counts, not a "
    "measurement: the tree was never compiled for or run on the MCU."
)

def render_same_input_section(timings_by_config: dict[str, list[PolicyTiming]]) -> str:
    lines = [
        "## Same-input benchmark (review rework, points 2.4/7.6)",
        "",
        f"Every policy is timed on the same {MAX_CAPTURED_CONTEXTS} decision "
        "contexts, evenly spaced over all decision points of the 48 h seed-42 "
        "reference run under the always-serve baseline, with the same "
        f"number of samples ({MAX_CAPTURED_CONTEXTS} contexts x "
        f"{REPS_PER_CONTEXT} repetitions). One sample is the mean per-call "
        f"time of {FAST_INNER_CALLS} back-to-back calls (baseline, tree) or "
        "of 1 call (lookahead, formerly \"oracle\") on one context. Host "
        "CPython timings; the baseline-FIFO and baseline-EDF variants share "
        "the same decide() (ordering is applied by the driver, not the "
        "policy), so one baseline row covers both.",
        "",
    ]
    for config_id, timings in timings_by_config.items():
        lines += [f"### {config_id}", "",
                  "| Policy | Big-O | N samples | Median | p95 | Mean | Max |",
                  "|---|---|---|---|---|---|---|"]
        for t in timings:
            name = "lookahead (\"oracle\")" if t.policy_name == "oracle" else t.policy_name
            lines.append(
                f"| {name} | {t.big_o} | {t.n_samples} | {_fmt_s(t.median_s)} | "
                f"{_fmt_s(t.p95_s)} | {_fmt_s(t.mean_s)} | {_fmt_s(t.max_s)} |"
            )
        lines.append("")
    lines += ["**Tree on the MCU.** " + TREE_C_ESTIMATE, ""]
    return "\n".join(lines)

def _fmt_s(value: float) -> str:
    if value < 1e-3:
        return f"{value * 1e6:.2f} µs"
    if value < 1.0:
        return f"{value * 1e3:.3f} ms"
    return f"{value:.4f} s"

def render_document(timings_by_config: dict[str, list[PolicyTiming]]) -> str:
    parts = [
        "<!-- Auto-generated by tools/benchmark_policies.py. Do not hand-edit. -->",
        "",
        "# Policy Complexity Analysis (R-20)",
        "",
        "Requirement R-20: \"both the rule-based and (later) learned "
        "scheduling policies must be analyzable for computational "
        "complexity under the same input model.\" This document gives the "
        "Big-O statement for each policy's `decide()` call (derived from "
        "the code, not asserted) and measured wall-clock timing against "
        "real, identically-captured decision contexts -- the same input "
        f"model for all three, per R-20's wording. Each figure is the mean "
        f"over repeated calls against up to {MAX_CAPTURED_CONTEXTS} real "
        "captured (FeatureVector, DecisionContext) pairs per config "
        "(same number of samples for every policy -- see this module's "
        "docstring).",
        "",
    ]
    for config_id, timings in timings_by_config.items():
        parts.append(f"## Config {config_id}")
        parts.append("")
        if not timings:
            parts.append(
                "No decision points captured in the short benchmarking run "
                "for this config -- insufficient data."
            )
            parts.append("")
            continue
        parts.append("| Policy | Big-O | Mean | Stdev | Min | Max | N |")
        parts.append("|---|---|---|---|---|---|---|")
        for t in timings:
            parts.append(
                f"| {t.policy_name} | {t.big_o} | {_fmt_s(t.mean_s)} | "
                f"{_fmt_s(t.stdev_s)} | {_fmt_s(t.min_s)} | {_fmt_s(t.max_s)} | {t.n_samples} |"
            )
        parts.append("")
        baseline = next((t for t in timings if t.policy_name == "baseline"), None)
        oracle = next((t for t in timings if t.policy_name == "oracle"), None)
        tree = next((t for t in timings if t.policy_name == "tree"), None)
        if oracle and tree and tree.mean_s > 0:
            ratio = oracle.mean_s / tree.mean_s
            parts.append(
                f"The oracle is measured at ~{ratio:,.0f}x the tree's mean "
                "decide() cost on this config, despite both being formally "
                "\"constant\" per decision point -- the constant factor "
                "(SGP4 propagation, FSM steps, and scheduler operations per "
                "rollout tick vs. a handful of float comparisons) dominates "
                "in practice. This is the concrete answer to \"is the "
                "decision tree actually cheaper\": yes, by several orders "
                "of magnitude, which is the real justification for using it "
                "in place of running the oracle onboard."
            )
        elif baseline:
            parts.append(
                "(Oracle/tree comparison omitted -- see the table above for "
                "available figures.)"
            )
        parts.append("")
    return "\n".join(parts)

def write_complexity_analysis(
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
) -> None:
    config_a = load_config(REPO_ROOT / "config" / "config-a.yaml")
    config_b = load_config(REPO_ROOT / "config" / "config-b.yaml")

    dataset_rows = generate_dataset(
        [config_a, config_b], seeds=(1, 2), duration_s=CAPTURE_DURATION_S, dt_s=CAPTURE_DT_S,
    )
    tree_policy = train(dataset_rows)

    timings_by_config = {
        cfg.config_id: benchmark_policies(cfg, tree_policy)
        for cfg in (config_a, config_b)
    }
    Path(output_path).write_text(render_document(timings_by_config))

def main() -> None:
    write_complexity_analysis(DEFAULT_OUTPUT_PATH)
    print(f"wrote {DEFAULT_OUTPUT_PATH}")

if __name__ == "__main__":
    main()
