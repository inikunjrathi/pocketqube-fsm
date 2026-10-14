from __future__ import annotations

from sim.scenario import ORBITAL_PERIOD_S
from tools.generate_policy_comparison import (
    paired_bootstrap_ci,
    run_policy,
    write_policy_comparison,
)

_DURATION_S = 6 * ORBITAL_PERIOD_S
_DT_S = 60.0

def test_run_policy_baselines_share_arrivals_and_never_hold():
    fifo = run_policy("config-a", "reference", "baseline-fifo", 12345,
                      duration_s=_DURATION_S, dt_s=_DT_S)
    edf = run_policy("config-a", "reference", "baseline-edf", 12345,
                     duration_s=_DURATION_S, dt_s=_DT_S)
    assert fifo.n_generated == edf.n_generated > 0
    assert fifo.n_holds == edf.n_holds == 0
    for r in (fifo, edf):
        assert 0.0 <= r.deadline_success <= r.window_delivery <= 1.0

def test_paired_bootstrap_ci_is_deterministic_and_brackets_mean():
    diffs = [0.1, -0.2, 0.3, 0.0, 0.05]
    mean, lo, hi = paired_bootstrap_ci(diffs, n_resamples=2000)
    assert (mean, lo, hi) == paired_bootstrap_ci(diffs, n_resamples=2000)
    assert lo <= mean <= hi
    assert paired_bootstrap_ci([0.0, 0.0, 0.0]) == (0.0, 0.0, 0.0)

def test_write_policy_comparison_writes_all_sections(tmp_path):
    out = tmp_path / "policy-comparison-results.md"
    exp = write_policy_comparison(
        out, scenarios=("reference",), train_seeds=(1,), eval_seeds=(2, 3),
        include_reference_seed=False, duration_s=_DURATION_S, dt_s=_DT_S, workers=2,
    )
    text = out.read_text()
    for needle in ("RQ3", "Multi-seed statistical treatment", "95% CI", "config-a",
                   "config-b", "baseline-fifo", "baseline-edf", "lookahead", "tree",
                   "relaxation bound", "Per-seed results", "|--- "):
        assert needle in text, needle
    for (s, c, p, seed), r in exp.results.items():
        b = exp.bounds[(s, c, seed)]
        assert r.n_delivered <= b.window_bound
        assert r.n_on_time <= b.deadline_bound
