# Formal Verification via TLA+/TLC

`tools/generate_tla_spec.py` writes one TLA+ module and TLC config per
shipped configuration (`config-a`, `config-b`, `config-c`) into
`docs/tla/`; `tools/run_model_check.sh` regenerates them and runs TLC.
The pytest suite is not a substitute: it enumerates cases people chose,
while TLC explores every reachable state of the model below.

## What the model contains

| Aspect | Modelled as |
|---|---|
| Control state | `pc`, one of the declared states |
| Latches and boolean context flags (`path_a_confirmed`, ...) | Boolean variables, updated exactly as `engine/fsm.py::_apply_actions` / `_apply_latch_sets` do (a latch-clear action is a no-op on a latch) |
| Guards of the form `context.X ==/!= true/false` | Encoded exactly |
| All other guards (`elapsed()`, telemetry, parameters) | Nondeterministic: may be true or false on any step |
| First-matching-row rule | A row is disabled when an earlier row for the same event is certainly enabled (unguarded, or an exact guard that holds) |
| Persistence | `b_*` variables = last durable snapshot. Every legal step either saves or leaves the old snapshot (torn/lost save). `reload_from_persistence` restores pc and booleans from the snapshot, then applies the row's own actions. Before the first save the snapshot equals the initial values (engine: `load()` is `None`, boot fresh) |
| `ev` | Name of the event of the last step, so properties can say "only via event X" |
| Not modelled | Timers and numeric context, telemetry values, real time, the scheduler queue, conflict-rank arbitration, HMAC authentication, and the double fault where both banks are corrupt after the latch was saved |

Every abstraction adds behaviour relative to the engine, so a safety
property TLC proves here holds for the engine over the modelled
variables. Nothing here is a liveness or timing result.

## Properties

Generic, derived from the YAML (they say nothing the YAML could get wrong):

- `TypeOK`.
- `<latch>DurableNeverClears`: the persisted latch never goes TRUE to FALSE.
- `<latch>LiveOnceDurable` (invariant): once persisted, the live latch is TRUE.
- `<latch>NeverClears` (the in-RAM property earlier versions checked) is
  defined but not in the `.cfg`. With torn saves in the model it is false:
  a RESET that tears the save of the latch-setting step reloads the older
  snapshot (4-step counterexample on every config). This is the boundary
  documented in `engine/fsm.py`'s module docstring. `run_model_check.sh`
  checks that TLC still finds this counterexample, so the persistence model
  cannot silently become vacuous.

Hand-written, from `docs/tla/independent_requirements.yaml` (states and
events by name, written from `docs/requirements/`, not computed from the
YAML):

| Property | Kind | Requirement basis |
|---|---|---|
| `PostLatchStatesHaveLatch` | invariant | R-05, R-08, R-14 / RB-03 / RC-03 |
| `LatchRisesOnlyVia` | action | R-03 (Config A also requires both path flags) / RB-01 / RC-01 |
| `RfSilenceLeftOnlyVia` | action | R-02, R-08 |
| `SafeExitOnlyVia` | action | R-23, R-24 / RB-09, RB-12 / RC-09, RC-12 |
| `SafeEntryOnlyVia` | action | R-21, R-22 / RB-07, RB-08 / RC-07, RC-08 |
| `SchedulerOnlyInComms` | action | R-10, R-14 / RB-05 / RC-05 |
| `GroundSafeAvailableExactly` | invariant (`ENABLED`) | R-22 / RB-08 / RC-08, both directions |
| `ResetAlwaysAvailable` | invariant (`ENABLED`) | R-27 / RB-10 / RC-10 |

The same properties are checked against the real engine (real guards,
real persistence semantics, an environment grid for timers and telemetry)
by `tests/test_requirements_independent.py`.

## Results (TLC 2.19, 12 October 2026, after decision 0010)

| Config | Declared states | States generated | Distinct states | Depth | Result |
|---|---|---|---|---|---|
| config-a | 10 | 7,657 | 434 | 11 | No error |
| config-b | 7 | 1,798 | 121 | 9 | No error |
| config-c | 7 | 1,991 | 128 | 9 | No error |

Before decision 0010, config-a violated `PostLatchStatesHaveLatch`:
`STOWED -SEPARATION_DETECTED-> RF_INHIBIT -RF_INHIBIT_TIMER_EXPIRED->
DEPLOY_CONFIRM_PENDING -GROUND_SAFE_MODE_CMD-> SAFE_MODE
-AUTONOMOUS_RECOVERY_CONDITIONS_MET-> COMMISSIONING`, with the latch unset
(T-18/T-21 exited to S-05 unconditionally). T-18/T-21 are now guarded on
the latch, and T-25/T-26 return a latch-unset SAFE_MODE to
DEPLOY_CONFIRM_PENDING. See
`docs/decisions/0010-safe-mode-exit-respects-deployment-latch.md`.

Earlier, structural-only model (guards dropped, reset returned to the
initial state with the latch unchanged, no persistence, properties
`TypeOK` and in-RAM `NeverClears` only). That model's reset did not match
the engine, which restores the persisted state rather than the initial
state. Its numbers are kept below in the format
`tools/export_visualization_data.py` parses (A and B only); re-run on
11 October 2026 it gave config-a 177 generated / 19 / 7, config-b
59 / 9 / 6, and config-c 60 generated / 9 distinct / depth 6, all no error.

| Config | States (declared) | Distinct (`pc`, latch) states reached | Max search depth | Result |
|---|---|---|---|---|
| config-a | 10 | 19 | 7 | No error found |
| config-b | 7 | 9 | 6 | No error found |

## Running it

```
tools/run_model_check.sh
```

Requires Java and `tools/vendor/tla2tools.jar` (see the script header for
the one-time download). The generator's pure functions are unit-tested in
`tests/test_generate_tla_spec.py`; TLC itself stays outside the pytest run.
Config mutation testing that uses TLC as one oracle:
`.venv/bin/python -m tests.test_mutation_configs [--suite]`.
