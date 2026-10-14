# Conflict-Resolution Priority Ordering

This document defines how the engine picks which pending **event** to
service when more than one is pending at the same evaluation tick. It is
deliberately written and tested separately from the **data-class priority**
(section 4 of the plan: TT&C/housekeeping > SSTV imagery > Codec2/M17
voice/data), which governs a different decision. The two are easy to
conflate; they are not the same thing.

| | Data-class priority (`P-001`) | Conflict-resolution ordering (`CR-xx`, this document) |
|---|---|---|
| **Question it answers** | Given several *queued data items* eligible for downlink, which one goes next? | Given several *pending FSM events* at one tick, which one does the engine act on first? |
| **Owner** | The priority-queue scheduler (Phase 2, W4) | The transition-table interpreter (`step()`) itself |
| **Fixed by the mission document?** | Yes — TT&C > SSTV > Codec2/M17 is given, not assumed | No — unspecified by the use-case document; a configuration parameter, ranked here |
| **Config-swappable?** | Yes, but the *order itself* (TT&C first) is a fixed input from section 4 | Yes, fully — Config B may rank categories differently |

## Ranked categories

| Rank | ID | Category | Example events | Tie-break within category |
|---|---|---|---|---|
| 1 (highest) | CR-01 | Ground overrides / reset | `GROUND_SAFE_MODE_CMD`, `GROUND_OVERRIDE_EXIT_SAFE`, `RESET` | Event timestamp (earliest wins); `RESET` always wins ties against ground commands, since it represents an unconditional hardware-level event, not a policy choice |
| 2 | CR-02 | Fault / watchdog | `FAULT_DETECTED`, `WATCHDOG_TIMEOUT`, `POWER_LOW`, `AUTONOMOUS_RECOVERY_CONDITIONS_MET`, `COMMS_LOSS_TIMEOUT` | Event timestamp, then event ID lexical order |
| 3 | CR-03 | Deployment lifecycle | `SEPARATION_DETECTED`, `RF_INHIBIT_TIMER_EXPIRED`, `DEPLOY_CONFIRM_PATH_A`/`_B`, `ENTER_COMMISSIONING` | Event timestamp |
| 4 | CR-04 | Scheduler / data-class arbitration | `SCHEDULER_SELECT_TTC`/`_SSTV`/`_VOICE`/`_IDLE`, `PASS_END` | Internally ordered by the data-class priority (`P-001`); `PASS_END` outranks any `SCHEDULER_SELECT_*` within this category since it reflects a physical constraint, not a scheduling preference |
| 5 (lowest) | CR-05 | Routine / informational | `COMMISSIONING_COMPLETE`, `UPLINK_CMD_GENERIC` (when not mapped to a CR-01 command) | Event timestamp |

## Rule

Given multiple events pending at a tick, the engine selects the transition
for the event belonging to the **lowest-numbered category** (CR-01 is
serviced before CR-02, and so on). Ties within a category are broken as
specified in the category's "Tie-break" column above. All other pending
events remain queued for the next tick; they are not discarded.

This ordering governs *only* which event the FSM acts on first — it does
not itself select *which data item* is transmitted once a
`SCHEDULER_SELECT_*` event is chosen. That decision belongs entirely to the
data-class priority (`P-001`) inside the scheduler, per the comparison table
above.

## Worked examples

1. **Fault during an active SSTV downlink.** `FAULT_DETECTED` (CR-02) and
   `SCHEDULER_SELECT_SSTV` (CR-04, re-queued from a new imagery item
   arriving) are both pending. CR-02 outranks CR-04, so the engine
   transitions to `SAFE_MODE` (T-14) first; the SSTV request remains queued
   and is re-evaluated on the next tick once (if) the FSM exits safe mode.

2. **Ground safe-mode command during nominal TT&C downlink.**
   `GROUND_SAFE_MODE_CMD` (CR-01) and `PASS_END` (CR-04) are both pending.
   CR-01 outranks CR-04 regardless of the physical pass ending — the ground
   operator's command is serviced first (T-17), even though `PASS_END` would
   have produced a similar-looking transition to a non-transmitting state.
   This distinction matters for decision-rationale logging (R-31): the
   logged reason must say "ground override," not "pass ended."

3. **Reset injected mid-write, simultaneous with a scheduler event.**
   `RESET` (CR-01) and any `SCHEDULER_SELECT_*` (CR-04) pending together —
   `RESET` wins because CR-01 outranks CR-04 (rank precedence, not the
   intra-rank tie-break rule, which only applies when two CR-01 events are
   pending against each other), since `RESET` is unconditional per R-27.

## Runtime implementation (R-19)

Until this section was added, the ranks above were only *validated* by
`engine/config_loader.py` (every event ranked exactly once). `step()`
handles one event per call, and `sim/driver.py` attempted its events in a
hard-coded order. The ordering is now executed at run time by
`engine/arbitration.py`. `step()` itself is unchanged.

**Ordering key** (lower first), built from each config's own
`conflict_resolution` rows and the `tie_break` text:

    (rank, class_key, timestamp, reset_key, event_id)

| `tie_break` text contains | Rule applied |
|---|---|
| `data_class_priority` (CR-04) | `class_key`: `PASS_END` = 0; `SCHEDULER_SELECT_<class>` = 1 + index in `data_class_priority`; any other `SCHEDULER_SELECT_*` (e.g. `_VOICE`, `_ACTIVE`) after those; `SCHEDULER_SELECT_IDLE` last. Data-class order dominates timestamp. |
| `RESET ... wins` (CR-01) | earliest timestamp, then `RESET` before any other event at the same timestamp (`reset_key`) |
| `timestamp` (CR-02/03/05) | earliest timestamp |
| anything else | `ArbitrationError` (no silent default) |

The event id (lexical) is the final key everywhere. That is CR-02's stated
rule, and it is the deterministic answer for an exact tie that "event
timestamp" alone leaves open in CR-03/CR-05.

**Servicing** (`step_many`): call `step()` on the pending events in that
order. The first one with a legal transition is serviced. Events ahead of
it that had no legal transition from the current state are dropped. Events
behind it remain queued and keep their original timestamp
(`merge_pending` keeps one copy per event id, the earliest). One event is
serviced per call. `describe()` builds a decision-log rationale that names
the serviced event's rank and category and what is still queued, so a
ground safe-mode command arbitrated over `PASS_END` reads as
`... GROUND_SAFE_MODE_CMD (rank 1 ground_override_reset) via T-17`
(worked example 2, R-31).

**Driver.** At each tick `sim/driver.py` raises the FSM events it models
(SAFE_MODE: `AUTONOMOUS_RECOVERY_CONDITIONS_MET` and/or
`GROUND_OVERRIDE_EXIT_SAFE`; otherwise `POWER_LOW`, `FAULT_DETECTED` while a
fault is injected, and `PASS_END` in a comms mode). It merges them with the
queue and services them through the same rule, via `_try_fire`, so signing,
persistence and logging are unchanged. `SCHEDULER_SELECT_*` events are
still raised one at a time by the scheduler's transmit loop *after* this
step, never simultaneously with the events above, so CR-04's
"`PASS_END` first" holds by construction. That loop was not re-routed.

**C port.** `mcu/firmware/app/src/engine_arbitration.c` implements
`engine_arbitrate()` with the same key. Its static part
(`engine_arbitration_table.c`) is generated from
`engine.arbitration.event_static_keys()` by
`mcu/host_bridge/codegen_arbitration_table.py`.
`tests/test_engine_arbitration_c.py` diffs the C order against Python on
about 2,400–2,800 generated pending sets per config (A, B and C). Only the
ordering function is ported. The UART bridge still injects one event per
`INJECT`, so the firmware does not yet call it, and the linker drops it
from the image.

**Effect on recorded results.** On the seed-42 reference runs of Configs A,
B and C, the metrics, deliveries and decision logs are identical before and
after the driver was routed through arbitration. The same holds for the 20
evaluation seeds (5000–5019, all three configs) and the worst-case
parameter scenarios. The 35,763-call Config A trace is line-for-line
identical to the committed evidence. Only the battery/fault stress cases
change, because there two events really are pending together. See
`build/review/D-security.md`, "Arbitration".

## Relationship to Week 2

This ranking is itself one of the config-swappable fields named in section
5 ("conflict-resolution priority ordering"). This document is the Week 1
prose design; Week 2's config schema formalizes the same five-category,
tie-break structure as a YAML list, and Config B's specification will
either reuse this ordering or deviate from it explicitly — a deviation here
would be a genuine test of the schema's generality, not an oversight.
