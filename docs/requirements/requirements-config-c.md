# Config C — Requirements (RC-01 .. RC-13)

Cross-reference: `config/config-c.yaml`.

Config C is a **synthetic third configuration** (Phase 7D), not a
POQUITO/SomaiyaSat mission variant like Config A/B — see
`docs/decisions/0006-config-c-generality-axis.md` for the full rationale.
Its requirement set mirrors Config B's (`requirements-config-b.md`)
closely, since Config C reuses Config B's deployment sequence verbatim,
except for RC-09 (which now states a two-path recovery model instead of
Config B's ground-only one) and the new RC-13 (the autonomous-recovery
capability itself, which Config B structurally lacks).

| ID | Statement | Scope | Related | Document basis | CSBS course(s) | Verification method | Status |
|---|---|---|---|---|---|---|---|
| RC-01 | Deployment confirmation requires the single separation-switch event, followed by a debounce timer (`PC-002`) elapsing, before `deployment_confirmed` is set. Arming (`T-01`) and checking (`T-02`) the debounce are separate transitions. | Config-C | T-01, T-02, PC-001, PC-002 | Mirrors Config B's RB-01 | Sem VI | Unit test: T-01 arms the timer, T-02's guard is unsatisfiable before it elapses and satisfied after | Specified |
| RC-02 | `deployment_confirmed` is a one-way latch: once set, no legal transition clears it — identical engine-level guarantee to Config A's R-04/Config B's RB-02, demonstrated on a third structurally distinct configuration. | Engine | T-02, T-13 | Mirrors Config B's RB-02 | Sem VI | Fault-injection test (`tests/test_fault_injection.py`, parametrized generically over `ALL_CONFIGS`) | Specified |
| RC-03 | Commissioning begins only after the `deployment_confirmed` latch is set. | Config-C | T-03 | Mirrors Config B's RB-03 | Sem VI | Unit test: `ENTER_COMMISSIONING` illegal from S-01/S-02 | Specified |
| RC-04 | The single downlink mode (`COMMS_ACTIVE`) is entered once commissioning completes. | Config-C | T-04 | Mirrors Config B's RB-04 | Sem VI | Unit test on T-04 | Specified |
| RC-05 | `SCHEDULER_SELECT_ACTIVE`/`SCHEDULER_SELECT_IDLE` are legal from either comms-mode state and switch/hold the mode accordingly. | Config-C | T-05, T-06 | Mirrors Config B's RB-05 | Sem III (DSA — scheduler applies `P-001` internally) | Unit test per event x per originating state | Specified |
| RC-06 | Once elevation drops below the configured minimum (`PC-006`), the FSM returns to `COMMS_IDLE` from either comms-mode state. | Config-C | T-07, PC-006 | Mirrors Config B's RB-06 | Sem VI | Unit test on T-07, guard boundary | Specified |
| RC-07 | A fault, low-power, or watchdog-timeout condition forces entry into `SAFE_MODE` from any deployment-complete state. | Config-C | T-08, T-09, T-10 | Mirrors Config B's RB-07 | Sem VI | Unit test per trigger x per originating state | Specified |
| RC-08 | A ground operator may force entry into, or hold within, `SAFE_MODE` from `S-03` onward (once RF is enabled). | Engine | T-11 | Mirrors Config B's RB-08 | Sem VI | Unit test: T-11 from every state in its `From` set, illegal from S-01/S-02 | Specified |
| RC-09 | Exit from `SAFE_MODE` has TWO legal paths: autonomous recovery once `battery_soc` recovers above `PC-012` (`T-16`, mirroring Config A's `R-23`), or ground override at any time (`T-12`, mirroring Config B's `RB-09`'s transition though not its "ground-only" claim). This is the defining structural contrast that distinguishes Config C from both Config A (dual-path deployment + autonomous recovery) and Config B (single-path deployment + ground-only recovery): single-path deployment combined WITH autonomous recovery — a combination neither shipped config represents. | Config-C | T-12, T-16, PC-010, PC-012 | Section 5 (Config A vs. B contrast), extended by Phase 7D | Sem VI | Cross-config test: `sim/driver.py::_maybe_recover_from_safe_mode` attempts the autonomous path first (detected generically by parameter name, zero driver.py changes), falling back to ground override | Specified |
| RC-10 | `RESET` is legal from every state; `deployment_confirmed` survives any sequence of resets or corruptions — identical engine-level guarantee to Config A's R-27/R-29 and Config B's RB-10, demonstrated on a third structurally distinct configuration. | Engine | T-13 | Mirrors Config B's RB-10 | Sem VI | Fault-injection stress test (`tests/test_fault_injection.py`, parametrized generically) | Specified |
| RC-11 | Every safe-mode transition and generic uplink command logs a rationale including the triggering event and relevant guard values. | Engine | T-08, T-09, T-10, T-11, T-12, T-14, T-16 | Mirrors Config B's RB-11 | Sem VI | Log-content assertion in test suite | Specified |
| RC-12 | If RF is enabled and no ground telecommand is received for `PC-011` (2 days), the system autonomously resets to the last persisted known state. Does not fire from `SAFE_MODE`, preserving RC-09's two dedicated recovery paths. | Config-C | T-15, PC-011 | Mirrors Config B's RB-12 | Sem VI | Unit test: T-15 fires from every state in `{S-03..S-06}`, illegal from S-01/S-02/S-07 | Specified |
| RC-13 | Autonomous safe-mode recovery: once `battery_soc` recovers to/above `PC-012` while in `SAFE_MODE`, the FSM autonomously exits to `COMMISSIONING` without requiring a ground command — mirrors Config A's `R-23`, demonstrated here on Config B's structurally simpler chassis (single-path deployment, one downlink mode) rather than Config A's dual-path/four-mode one, proving the recovery-model axis is independent of the deployment/downlink-mode axes. | Config-C | T-16, E-16, PC-012 | Phase 7D — the new axis Config C adds relative to Config B | Sem VI | Unit test: `_maybe_recover_from_safe_mode` recovers via T-16 when `battery_soc >= PC-012`; `sim/driver.py::run_simulation` reaches this path autonomously with zero code changes | Specified |

## Note on RQ1 evidence

RC-02, RC-09, RC-10, and RC-13 are the rows that matter most for RQ1:
RC-02/RC-10 state the *same* engine-level guarantees (latch integrity,
reset legality) that Config A's/Config B's requirements state, verified
on a third structurally distinct configuration with zero engine-level
special-casing. RC-09/RC-13 state a genuinely *new* claim — that the
autonomous-recovery mechanism itself is independent of which deployment
sequence or downlink-mode count a config uses — which Config A alone
cannot demonstrate (it only ever pairs autonomous recovery with dual-path
deployment) and Config B cannot demonstrate at all (it has no autonomous
recovery). Config C isolates that one variable.

**Explicitly out of scope for Config C** (see
`docs/decisions/0006-config-c-generality-axis.md`): `tools/
generate_policy_comparison.py`'s oracle/decision-tree training set and
`tools/export_visualization_data.py`'s RQ1-RQ3 dashboard remain
Config-A/B-only — extending either to a third config is a separate,
larger effort that would invalidate already-reported RQ3 numbers, not a
gap in this requirement set.
