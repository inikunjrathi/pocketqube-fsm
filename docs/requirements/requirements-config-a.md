# Config A — Requirements (R-01 .. R-34)

Cross-reference: states `S-xx` (`../state-machine/config-a-states.md`),
events `E-xx` (`../state-machine/config-a-events.md`), transitions `T-xx`
(`../state-machine/config-a-transitions.md`), parameters `P-xx`
(`../parameters.md`), conflict-resolution ranks `CR-xx`
(`../conflict-resolution.md`).

**Scope** column: `Engine` = a claim about the mission-agnostic engine,
testable identically on Config A and Config B once both exist (RQ1
evidence). `Config-A` = a claim specific to this configuration's structure
or numbers (e.g. four comms modes, autonomous recovery permitted) that need
not hold for Config B.

**Status** column: `Specified` (this week) / `Implemented` (Phase 2) /
`Verified` (Phase 3). All rows start `Specified`.

## Group: Deployment lifecycle (R-01 – R-08)

| ID | Statement | Scope | Related | Document basis | CSBS course(s) | Verification method | Status |
|---|---|---|---|---|---|---|---|
| R-01 | On `SEPARATION_DETECTED`, the engine starts the RF-inhibit silence timer and transitions to `RF_INHIBIT`. | Config-A | T-01, P-010 | Section 4: deployment confirmation mechanisms; section 5: RF-inhibit silence timer | Sem VI (UML state charts) | Unit test on `step()` for T-01 | Specified |
| R-02 | RF is not enabled until the RF-inhibit silence timer has elapsed by at least `P-010` seconds. | Config-A | T-02, P-010 | Section 5 | Sem VI | Unit test on T-02 guard boundary (elapsed = P-010 − 1, = P-010) | Specified |
| R-03 | Deployment confirmation requires both confirmation path A and path B to assert independently, in either order, before `deployment_confirmed` is set. | Config-A | T-03..T-06, P-011, P-012 | Section 4: dual-path deployment confirmation (separation switch + timer, and RF beacon) | Sem VI | Unit tests for both orderings (A-then-B, B-then-A) | Specified |
| R-04 | `deployment_confirmed` is a one-way latch: once set, no legal transition clears it. | Engine | T-04, T-06, T-22 | Section 5: one-way latch semantics | Sem VI | Fault-injection test (Phase 3, W7) — direct RQ2 evidence | Specified |
| R-05 | Commissioning begins only after the `deployment_confirmed` latch is set, including on exit from `SAFE_MODE` (a safe mode entered before the latch returns to `DEPLOY_CONFIRM_PENDING`). | Config-A | T-07, T-18, T-21, T-25, T-26 | Section 5 | Sem VI | Unit test: `ENTER_COMMISSIONING` illegal from S-01..S-03 | Specified |
| R-06 | The first nominal comms mode entered after commissioning completes is TT&C, consistent with the data-class priority order. | Config-A | T-08, P-001 | Section 4: TT&C highest data-class priority | Sem VI | Unit test on T-08 | Specified |
| R-07 | Deployment-confirmation path events (`DEPLOY_CONFIRM_PATH_A`/`_B`) are order-independent: the resulting state after both have fired is identical regardless of arrival order. | Engine | T-03..T-06 | Section 5 | Sem VI, Sem III (state modeling) | Property-based test over both orderings | Specified |
| R-08 | No transmission action is permitted while the FSM is in `STOWED` or `RF_INHIBIT`, regardless of any other pending event or guard state. | Engine | T-01, T-02; illegal-pair examples in transitions doc | Section 4, 5 | Sem VI | Unit test: all `SCHEDULER_SELECT_*` illegal from S-01/S-02 | Specified |

## Group: Comms-mode / mode exclusivity (R-09 – R-14)

| ID | Statement | Scope | Related | Document basis | CSBS course(s) | Verification method | Status |
|---|---|---|---|---|---|---|---|
| R-09 | Exactly one of the four comms modes (`COMMS_TTC`, `COMMS_SSTV`, `COMMS_VOICE`, `COMMS_IDLE`) is active at any time. | Engine | S-06..S-09, P-018 | Section 5: mode exclusivity constraints | Sem VI | Invariant check after every transition in test suite | Specified |
| R-10 | Scheduler mode-select events are legal only once commissioning has completed (i.e. from `S-06` onward, once `E-05` has fired), never before or during deployment/commissioning. | Config-A | T-08..T-13 | Section 5 | Sem VI | Unit test: `SCHEDULER_SELECT_*` illegal from S-01..S-05 | Specified |
| R-11 | A `SCHEDULER_SELECT_*` event is legal from any nominal comms-mode state or from commissioning-complete, and switches (or holds) the active mode accordingly. | Config-A | T-09..T-12 | Section 5 | Sem III (DSA — priority queue integration) | Unit test per event × per originating state | Specified |
| R-12 | Once elevation drops below the configured minimum (`P-015`), the FSM returns to `COMMS_IDLE` from any active comms-mode state. | Config-A | T-13, P-015 | Section 6: elevation-dependent link model | Sem VI | Unit test on T-13, guard boundary | Specified |
| R-13 | Every comms-mode switch logs the previous mode, the new mode, and the triggering event. | Engine | T-09..T-12 | Section 3: Responsible AI — logged rationale | Sem VI | Log-content assertion in test suite | Specified |
| R-14 | Any `SCHEDULER_SELECT_*` event is illegal (no-op) while `deployment_confirmed` is unset, and remains illegal through commissioning until the first `COMMISSIONING_COMPLETE`. | Config-A | Closed-world rule; T-09..T-12 vs. S-01..S-05 | Section 5 | Sem VI | Unit test: illegal-pair no-op assertion | Specified |

## Group: Scheduling / priority (R-15 – R-20)

| ID | Statement | Scope | Related | Document basis | CSBS course(s) | Verification method | Status |
|---|---|---|---|---|---|---|---|
| R-15 | The scheduler selects the highest-priority eligible data-class item per the fixed order TT&C > SSTV > Codec2/M17. | Engine | P-001; E-06..E-09 | Section 4 (fixed); Section 3: onboard AI scheduler/router | Sem III (DSA) | Scheduler unit test with mixed-class queue | Specified |
| R-16 | The priority queue supports dynamic reordering as new items arrive mid-pass. | Engine | Scheduler (Phase 2, W4) | Section 3: priority queue with dynamic reordering | Sem III (DSA) | Scheduler unit test: insert during active service | Specified |
| R-17 | A newly-eligible TT&C item preempts an in-progress SSTV or voice downlink. | Config-A | T-09 legal from S-07/S-08 | Section 4: TT&C highest priority | Sem III (DSA) | Scheduler + FSM integration test | Specified |
| R-18 | The scheduler selects idle (`COMMS_IDLE`) when no eligible item is queued. | Engine | T-12 | Section 5 | Sem III (DSA) | Scheduler unit test: empty queue | Specified |
| R-19 | FSM-level event arbitration (which pending event is serviced first) is governed by the conflict-resolution ordering (`CR-xx`), which is distinct from and does not override the data-class priority ordering (`P-001`), which governs item selection *within* the scheduler. | Engine | `conflict-resolution.md` | Section 5: conflict-resolution priority ordering vs. data-class priority ordering | Sem VI | Unit test with simultaneous pending events of different categories | Specified |
| R-20 | Both the rule-based and (later) learned scheduling policies must be analyzable for computational complexity under the same input model. | Engine | Forward reference: Phase 5, W12 | Section 2: RQ3; Sem IV, Analysis of Algorithms | Sem IV | Complexity analysis in Phase 5 report section | Specified |

## Group: Safe-mode / override (R-21 – R-26)

| ID | Statement | Scope | Related | Document basis | CSBS course(s) | Verification method | Status |
|---|---|---|---|---|---|---|---|
| R-21 | A fault, low-power, or watchdog-timeout condition forces entry into `SAFE_MODE` from any deployment-complete state. | Config-A | T-14, T-15, T-16 | Section 3: watchdogs and fallback rule-based logic (AI Security & Trustworthiness) | Sem VI | Unit test per trigger × per originating state | Specified |
| R-22 | A ground operator may force entry into, or hold within, `SAFE_MODE` at any time from `S-03` onward (i.e. wherever RF is enabled, including before deployment is fully confirmed — the designed escalation path if deployment confirmation stalls). | Engine | T-17 | Section 3: Human-in-the-Loop — ground operators retain override | Sem VI | Unit test: T-17 from every state in its `From` set, illegal from S-01/S-02 | Specified |
| R-23 | Config A permits autonomous exit from `SAFE_MODE` once recovery conditions are met (`E-15`); no additional policy gate or pending state exists in this config. The exit goes to `COMMISSIONING` if `deployment_confirmed` is set, otherwise back to `DEPLOY_CONFIRM_PENDING` (decision 0010). | Config-A | T-18, T-25 | Section 5 (Config A vs. Config B contrast) | Sem VI | Unit test on T-18 | Specified |
| R-24 | A ground operator may always override and force exit from safe mode, independent of the autonomous-recovery path (to `COMMISSIONING` with the latch set, else to `DEPLOY_CONFIRM_PENDING`; decision 0010). | Engine | T-21, T-26 | Section 3: Human-in-the-Loop | Sem VI | Unit test T-21 | Specified |
| R-25 | Safe-mode entry and recovery use separate battery state-of-charge thresholds (`P-013` entry, `P-014` recovery) such that recovery threshold > entry threshold, preventing rapid entry/exit chattering. | Config-A | T-15, T-18, P-013, P-014 | Section 6: power model | Sem IV (constrained optimisation framing) | Parameter validation check: `P-014 > P-013`; simulated chattering test in Phase 4 | Specified |
| R-26 | Whether safe-mode exit is autonomous-with-override or ground-only is a structural property of a configuration (which events/states it defines), documented per-config via `P-020`/`PB-010` as a design label rather than a runtime-branched value; Config A implements the autonomous-with-override structure, Config B implements ground-only with no autonomous path at all. | Engine | P-020 | Section 5: Config A vs. Config B contrast | Sem VI | Cross-config test in Phase 3 (W6): same harness, structurally different transition sets, different observed behavior | Specified |

## Group: Persistence / reset / latch integrity (R-27 – R-30)

| ID | Statement | Scope | Related | Document basis | CSBS course(s) | Verification method | Status |
|---|---|---|---|---|---|---|---|
| R-27 | `RESET` is a legal event from every state, unconditionally. | Engine | T-22 | Section 5: fault-injection harness (reset at arbitrary points) | Sem VI | Fault-injection test: RESET from all 10 states | Specified |
| R-28 | A `RESET` occurring mid non-volatile write does not corrupt persisted state; the engine recovers to the last verifiably-consistent bank via CRC32 and a monotonic sequence number across A/B banks. | Engine | T-22; persistence layer (Phase 2, W4) | Section 5: persistence layer design; NASA NEPP / JPL MNOS EEPROM references (section 10) | — (implementation detail; cites external references, not a course row) | Fault-injection test: RESET injected at every byte-offset boundary of a simulated write (Phase 3, W7) | Specified |
| R-29 | No sequence of resets or corruptions clears the `deployment_confirmed` latch once set. | Engine | T-22, R-04 | Section 2: RQ2 (direct statement) | Sem VI | Fault-injection stress test: randomized RESET sequences post-latch (Phase 3, W7) | Specified |
| R-30 | Every `(state, event)` pair absent from the transition table resolves to a no-op with a logged reason, never to an exception or unintended transition. | Engine | Closed-world rule, transitions doc | Section 5 (implied by transition-table interpreter contract); RQ1 | Sem VI | Exhaustive test: all illegal pairs asserted no-op (Phase 3, W6) | Specified |

## Group: Decision-rationale logging (R-31 – R-33)

| ID | Statement | Scope | Related | Document basis | CSBS course(s) | Verification method | Status |
|---|---|---|---|---|---|---|---|
| R-31 | Every safe-mode entry, safe-mode exit, and ground-override transition logs a rationale including the triggering event and relevant guard values. | Engine | T-14, T-15, T-16, T-17, T-18, T-21, T-23 | Section 3: Responsible AI — logged rationale for prioritisation choices | Sem VI | Log-content assertion for each transition family | Specified |
| R-32 | Every scheduler arbitration decision (data-class item selection) logs its rationale, including the competing candidates considered and the priority rule applied. | Engine | Scheduler (Phase 2, W4); P-001 | Section 3: Responsible AI; onboard AI scheduler/router | Sem III (DSA) | Log-content assertion in scheduler test suite | Specified |
| R-33 | The decision log is queryable/exportable in a form the verification-matrix generator (Phase 2, W5) can consume to produce requirement → test → pass/fail mappings. | Engine | Decision logger (Phase 2, W4); generators (Phase 2, W5) | Deliverable 5: verification matrix | Sem VI | Generator smoke test: log → matrix round-trip | Specified |

## Group: Autonomous comms-loss recovery (R-34)

| ID | Statement | Scope | Related | Document basis | CSBS course(s) | Verification method | Status |
|---|---|---|---|---|---|---|---|
| R-34 | If RF is enabled and no ground telecommand is received for `P-025` (2 days), the system autonomously resets to the last persisted known state. | Config A | T-24, P-025 | Franzese et al. 2026, Sect. 3.7 (Software architecture) — real POQUITO radiation-mitigation feature; see `docs/parameters.md` P-025 | Sem VI | Unit test: T-24 fires from every state in `{S-03..S-10}`, illegal from S-01/S-02; guard satisfied only once `elapsed(ground_contact_timer) >= P-025` | Specified |
