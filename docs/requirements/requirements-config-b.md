# Config B — Requirements (RB-01 .. RB-12)

Cross-reference: `config/config-b.yaml`, `docs/state-machine/config-b-overview.md`.

Config B's requirement set is deliberately smaller than Config A's (34
requirements) because Config B's structure is smaller by design — this
document does not re-derive every Config-A-style requirement, only the ones
specific to Config B's own transitions plus the cross-config claims that
Config B is the actual evidence for (RB-02, RB-09, RB-10 in particular are
direct RQ1/RQ2 evidence: the same engine-generic properties, demonstrated
on a structurally different configuration).

| ID | Statement | Scope | Related | Document basis | CSBS course(s) | Verification method | Status |
|---|---|---|---|---|---|---|---|
| RB-01 | Deployment confirmation requires the single separation-switch event, followed by a debounce timer (`PB-002`) elapsing, before `deployment_confirmed` is set. Arming (`T-01`) and checking (`T-02`) the debounce are separate transitions. | Config-B | T-01, T-02, PB-001, PB-002 | Plan section 5: Config B is single-path | Sem VI | Unit test: T-01 arms the timer, T-02's guard is unsatisfiable before it elapses and satisfied after | Specified |
| RB-02 | `deployment_confirmed` is a one-way latch: once set, no legal transition clears it — identical engine-level guarantee to Config A's R-04, demonstrated on a structurally different deployment sequence. | Engine | T-02, T-13 | Section 5: one-way latch semantics; Section 2: RQ1 | Sem VI | Fault-injection test (Phase 3, W7), compared against Config A's R-04 result | Specified |
| RB-03 | Commissioning begins only after the `deployment_confirmed` latch is set. | Config-B | T-03 | Section 5 | Sem VI | Unit test: `ENTER_COMMISSIONING` illegal from S-01/S-02 | Specified |
| RB-04 | The single downlink mode (`COMMS_ACTIVE`) is entered once commissioning completes. | Config-B | T-04 | Section 5: single downlink mode | Sem VI | Unit test on T-04 | Specified |
| RB-05 | `SCHEDULER_SELECT_ACTIVE`/`SCHEDULER_SELECT_IDLE` are legal from either comms-mode state and switch/hold the mode accordingly; data-class arbitration among TT&C/SSTV/voice happens entirely inside the scheduler's item selection, not as separate FSM states. | Config-B | T-05, T-06 | Section 5: single downlink mode | Sem III (DSA — scheduler still applies `P-001` internally) | Unit test per event × per originating state | Specified |
| RB-06 | Once elevation drops below the configured minimum (`PB-006`), the FSM returns to `COMMS_IDLE` from either comms-mode state. | Config-B | T-07, PB-006 | Section 6: elevation-dependent link model | Sem VI | Unit test on T-07, guard boundary | Specified |
| RB-07 | A fault, low-power, or watchdog-timeout condition forces entry into `SAFE_MODE` from any deployment-complete state. | Config-B | T-08, T-09, T-10 | Section 3: watchdogs and fallback rule-based logic | Sem VI | Unit test per trigger × per originating state | Specified |
| RB-08 | A ground operator may force entry into, or hold within, `SAFE_MODE` from `S-03` onward (once RF is enabled) — the designed escalation path if deployment confirmation stalls, mirroring Config A's R-22. | Engine | T-11 | Section 3: Human-in-the-Loop | Sem VI | Unit test: T-11 from every state in its `From` set, illegal from S-01/S-02 | Specified |
| RB-09 | Exit from `SAFE_MODE` is ground-commanded only (`PB-010 = ground_only`, a documentation label — see `parameters.md` review note); Config B has no autonomous safe-mode-exit event or recovery-pending state, in direct structural contrast to Config A's `R-23`. | Config-B | T-12, PB-010 | Section 5: Config A vs. Config B contrast | Sem VI | Cross-config test in Phase 3 (W6): same harness, absent autonomous-recovery path, different observed behavior than Config A | Specified |
| RB-10 | `RESET` is legal from every state; `deployment_confirmed` survives any sequence of resets or corruptions — identical engine-level guarantee to Config A's R-27/R-29, demonstrated on a structurally different persistence target. | Engine | T-13 | Section 2: RQ2 (direct statement) | Sem VI | Fault-injection stress test (Phase 3, W7), compared against Config A's result | Specified |
| RB-11 | Every safe-mode transition and generic uplink command logs a rationale including the triggering event and relevant guard values. | Engine | T-08, T-09, T-10, T-11, T-12, T-14 | Section 3: Responsible AI | Sem VI | Log-content assertion in test suite | Specified |
| RB-12 | If RF is enabled and no ground telecommand is received for `PB-011` (2 days), the system autonomously resets to the last persisted known state — mirrors Config A's `R-34`. Does not fire from `SAFE_MODE`: exit from `SAFE_MODE` stays ground-commanded only, preserving RB-09. | Config B | T-15, PB-011 | Franzese et al. 2026, Sect. 3.7 (Software architecture) — real POQUITO radiation-mitigation feature; see `docs/parameters.md` P-025 (Config B mirrors it via PB-011 in `config/config-b.yaml`) | Sem VI | Unit test: T-15 fires from every state in `{S-03..S-06}`, illegal from S-01/S-02/S-07; guard satisfied only once `elapsed(ground_contact_timer) >= PB-011` | Specified |

**Week 1-2 review correction:** the original `T-01` used a single event
with a self-referential guard (`elapsed(switch_debounce) >= PB-002`) that
nothing ever armed, meaning deployment could never actually complete. Fixed
by splitting arm (`T-01`) and check (`T-02`) into separate transitions —
see `docs/state-machine/config-b-overview.md` and
`docs/decisions/0002-config-schema-stress-test.md`. All transition IDs from
`T-02` onward shifted by one as a result; the table above reflects the
corrected numbering.

## Note on RQ1 evidence

RB-02, RB-09, and RB-10 are the three rows that matter most for RQ1: they
state the *same* engine-level guarantee (latch integrity, ground-override
availability, reset legality) that Config A's requirements state, but
verified against a configuration with a different deployment sequence, no
RF-inhibit stage, one downlink mode instead of four, and no autonomous
safe-mode recovery path at all. If Phase 3's cross-config test harness
(W6) cannot exercise these identically on both configs without engine
changes, RQ1's answer is "no" — and that must be reported as such, not
worked around.
