# Config A — State Table

Config A is the PocketQube reference configuration: deployer-ejected,
RF-inhibit silence timer, dual-path deployment confirmation, four comms
modes, sub-1W power budget (section 5 of the project plan).

Cross-reference: events use `E-xx` IDs (`config-a-events.md`), transitions
use `T-xx` IDs (`config-a-transitions.md`), parameters use `P-xx` IDs
(`../parameters.md`), requirements use `R-xx` IDs
(`../requirements/requirements-config-a.md`).

## Design decision: safe-mode exit policy

Config A permits **autonomous safe-mode recovery, bounded by ground
override** — the FSM transitions itself out of safe mode once recovery
conditions are met (`E-15`, unconditional — see `P-014
battery_soc_safe_mode_recovery_threshold_pct`), and a ground operator may
force entry into or hold within safe mode at any time via uplinked command
(from `S-03` onward, once RF is enabled), per the Human-in-the-Loop
governance requirement (section 3 of the plan). This is a deliberate design
choice, not the only legal one — Config B (section 5) is defined by
contrast as **ground-commanded safe-mode exit only**, with no autonomous
recovery path at all. This asymmetry is one of the two configurations'
structural differences that RQ1 tests the engine against.

`P-020 safe_mode_exit_policy` records *which* structural variant a config
implements (a documentation/design label), not a value a guard branches on
at runtime — Config A simply never defines the events/states that a
ground-only variant would need (no `SAFE_RECOVERY_PENDING` state, no
guarded branch on `E-15`). **Week 1-2 review correction:** an earlier draft
modeled this as a single shared transition table with `P-020` checked by a
guard, which left the "ground_only" branch (a `SAFE_RECOVERY_PENDING`
state and its transitions) permanently unreachable dead code within
Config A specifically, since `P-020`'s value here is fixed. That branch is
removed from this config; see
`docs/decisions/0002-config-schema-stress-test.md`.

## States

| ID | Name | Category | Description | One-way latch? | Entry actions | Notes |
|---|---|---|---|---|---|---|
| S-01 | `STOWED` | Deployment | Pre-separation. RF silent by construction (stowed, not yet powered for TX). Deployment not confirmed. Initial state. | No | — | Initial state on cold boot / first power-on. |
| S-02 | `RF_INHIBIT` | Deployment | Separation detected; RF-inhibit silence timer running (`P-010`). No transmission permitted regardless of any other condition. | No | Start `rf_inhibit_timer` | RF inhibit is a hardware/logic AND with all comms-mode states; see T-xx notes in transitions table. |
| S-03 | `DEPLOY_CONFIRM_PENDING` | Deployment | Silence timer expired; RF enabled; awaiting both deployment-confirmation paths (separation switch + timer, and short-duration RF beacon) to independently agree. | No | Enable RF | Dual-path: both `E-03` and `E-04` must fire before advancing (see T-04). |
| S-04 | `DEPLOYED_CONFIRMED` | Deployment | Both confirmation paths agreed. `deployment_confirmed` context flag is set. | **Yes — `deployment_confirmed`** | Set `deployment_confirmed` latch | Subject of RQ2: no sequence of resets or corruptions may clear this flag once set. |
| S-05 | `COMMISSIONING` | Deployment | Initial checkout (housekeeping-only downlink, health checks) before nominal comms rotation begins. | No | — | Transitions to nominal comms modes on `E-05`. |
| S-06 | `COMMS_TTC` | Comms-mode | Nominal mode 1 — TT&C/housekeeping downlink active. Highest data-class priority (section 4). | No | — | Mutually exclusive with S-07/S-08/S-09 (`P-018 mode_exclusivity_ruleset`). |
| S-07 | `COMMS_SSTV` | Comms-mode | Nominal mode 2 — SSTV imagery downlink active. | No | — | Mutually exclusive with S-06/S-08/S-09. |
| S-08 | `COMMS_VOICE` | Comms-mode | Nominal mode 3 — Codec2/M17 voice/data downlink active. Lowest data-class priority. | No | — | Mutually exclusive with S-06/S-07/S-09. |
| S-09 | `COMMS_IDLE` | Comms-mode | Nominal mode 4 — no active downlink; scheduler awaiting next queued item or next pass. | No | — | Default/rest comms-mode state; mutually exclusive with S-06/S-07/S-08. |
| S-10 | `SAFE_MODE` | Safe | Entered on fault, power-low, watchdog timeout, or ground command. Minimal footprint: TT&C-only, reduced power draw. | No | Suspend non-TTC downlink, log rationale | Reachable from `S-03` onward (once RF is enabled) — see closed-world rule in transitions table. Autonomous exit back to `S-05` requires only that recovery conditions are met (`E-15`); no separate pending/gated state exists in this config. Also exited via the autonomous comms-loss reset (`T-24`/`E-20`), which reloads from the persisted A/B bank (same mechanism as `T-22`) rather than returning to `S-05`. |

## State categories

- **Deployment** (S-01–S-05): one-way progression toward `DEPLOYED_CONFIRMED`, then commissioning. No state in this category is re-enterable once `DEPLOYED_CONFIRMED` is latched, except via the fault-injection `RESET` event or the autonomous comms-loss reset (`T-24`), both of which must still preserve the latch (RQ2).
- **Comms-mode** (S-06–S-09): the four nominal modes named in section 5. Exactly one is active at a time (mode exclusivity, `P-018`).
- **Safe** (S-10 only): reachable from `S-03` onward — i.e. from any state where RF is enabled, including the deployment-confirmation-pending stage itself (ground override is the designed escalation path if deployment confirmation stalls; see `P-011`/`P-012` notes in `parameters.md`). Not reachable from `S-01`/`S-02`, where RF is physically inhibited and no uplink can arrive.
