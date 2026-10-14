# Decision Record 0006 — Config C's Generality-Axis Choices and Explicit Scope Boundary

**Date:** 2026-08-02/03 (Phase D, Phase 7 critique-response plan)

## What was done

Authored `config/config-c.yaml` and `docs/requirements/requirements-config-c.md`
(RC-01..RC-13), then registered Config C in the shared cross-config test harness
(`tests/fixtures/transition_cases.py`, `tests/fixtures/event_chains.py`,
`test_config_loader.py`, `test_rq1_cross_config.py`, `test_fault_injection.py`),
added driver-level tests proving `sim/driver.py::_maybe_recover_from_safe_mode`
required zero code changes for Config C's autonomous recovery, and wired Config C
into `tools/generate_baseline_results.py` with a dual-ground-station reference
scenario. `tools/generate_verification_matrix.py` and `tools/generate_diagrams.py`
then auto-discovered `config/config-c.yaml` and produced a 13-row `## Config C`
section and a 7-state/16-transition Mermaid diagram with zero code changes,
matching the same generality claim already demonstrated for Config B in decision
0002.

## Decision

Config C combines Config B's single-path deployment (one separation switch plus
debounce, no dual-path context-flag bookkeeping) with Config A's
autonomous-permitted-with-override recovery model (`SAFE_MODE` exits either
autonomously once `battery_soc` clears `PC-012`, mirroring Config A's R-23, or
via ground override at any time, mirroring Config B's RB-09's transition though
not its "ground-only" claim) — the deployment×recovery-model axis. Config C also
adopts the Phase 7B dual-ground-station set as its own reference scenario in
`tools/generate_baseline_results.py`, rather than Config A/B's single-station
baseline — the ground-station-coverage axis. Both axes were chosen because they
required zero `engine/`/`sim/driver.py` code changes: both mechanisms were
already built generically in Phases B and C respectively, making this the
lowest-risk way to add real generality evidence beyond what two configs can show.

## What was deliberately NOT done, and why

1. **`data_class_priority` was kept identical to Config A/B.** It is a *cited*
   real mission fact (P-001), not a free design axis — varying it would
   misrepresent Config C as claiming a different real citation rather than being
   an honest synthetic config exploring structural axes only.

2. **Config C was NOT added to `tools/generate_policy_comparison.py`'s
   oracle/tree training set.** Extending the RQ3 policy-comparison pipeline to a
   third config is a significant separate effort that would invalidate
   already-reported RQ3 numbers (mean/CI figures computed over exactly two
   configs). Config C's actual purpose — structural/engine generality — is
   already fully served by the baseline-results, verification-matrix, and
   shared-test-harness evidence; it does not need a policy-comparison result to
   make that case.

3. **Config C was NOT added to `tools/export_visualization_data.py`'s dashboard.**
   Both `build_multi_seed_baseline_data()` and `build_complexity_data()`
   deliberately parse only `config-a`/`config-b` sections from their source
   documents (the former explicitly skips a `config-c` section that now exists
   alongside it in `docs/baseline-results.md`; the latter never had a
   `config-c` section to skip, since `docs/policy-complexity-analysis.md` is
   itself scoped to A/B only, per item 2 above). Same reasoning as item 2 — the
   RQ1-RQ3 dashboard is a downstream consumer of the policy-comparison work
   this decision explicitly excludes Config C from, not a separate scope
   decision.

4. **`docs/parameters.md` was not extended with Config C's `PC-*` rows.** This
   follows the same convention Config B already established: its `PB-*` rows
   live only in `config/config-b.yaml`'s own `rationale` fields, not in the
   shared parameters document. Config C's `PC-*` rows follow the identical
   pattern.

## Evidence this decision produced

`sim/driver.py::_maybe_recover_from_safe_mode` required zero code changes to
correctly drive Config C's autonomous recovery — proven by the driver-level
tests (`test_bootstrap_reaches_operational_state_config_c`,
`test_maybe_recover_autonomous_config_c`). This is the single strongest piece of
evidence for the mission-agnostic-engine claim this whole Phase 7 critique-
response plan has produced, because it wasn't designed in after the fact for
Config C: it's the same generic parameter-name-detection logic already in place
for Config A, working unmodified on a config it never anticipated. The same
zero-code-change pattern repeated for `tools/generate_verification_matrix.py`
and `tools/generate_diagrams.py` (both glob `config/*.yaml`/
`docs/requirements/*.md` and required no Config-C-specific branch), and for
`tests/test_rq1_cross_config.py`'s `test_shared_harness_files_never_branch_on_config_id`,
which continues to pass with Config C registered — the shared harness files
still contain no `config_id ==` branch anywhere.
