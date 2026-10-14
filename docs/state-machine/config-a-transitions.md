# Config A — Transition Table

Cross-reference: states use `S-xx` IDs (`config-a-states.md`), events use
`E-xx` IDs (`config-a-events.md`), parameters use `P-xx` IDs
(`../parameters.md`), requirements use `R-xx` IDs
(`../requirements/requirements-config-a.md`), conflict-resolution ranks use
`CR-xx` IDs (`../conflict-resolution.md`).

## Closed-world rule

**Any `(state, event)` pair not listed in this table is illegal.** The
engine must resolve an illegal pair to a **no-op**: the state is unchanged,
no action fires, and a rationale ("illegal pair: `(S-xx, E-yy)`") is written
to the decision log. This is the exact property Week 6's test suite
exercises: every row below is exercised as a positive case, and every
`(state, event)` combination *not* below is exercised as a no-op assertion.

Where a "From" cell lists a **set** of states (e.g. `{S-06, S-07, S-08,
S-09}`), the row is shorthand for one transition per member of the set —
this compact form is a Week 1 documentation convenience; Week 2's config
schema will require each to be enumerated as an individual data row.

## Table

| ID | From | Event | Guard | To | Actions | Req(s) |
|---|---|---|---|---|---|---|
| T-01 | S-01 `STOWED` | E-01 `SEPARATION_DETECTED` | none | S-02 `RF_INHIBIT` | start `rf_inhibit_timer` (`P-010`) | R-01 |
| T-02 | S-02 `RF_INHIBIT` | E-02 `RF_INHIBIT_TIMER_EXPIRED` | `elapsed(rf_inhibit_timer) >= P-010` | S-03 `DEPLOY_CONFIRM_PENDING` | enable RF | R-02 |
| T-03 | S-03 `DEPLOY_CONFIRM_PENDING` | E-03 `DEPLOY_CONFIRM_PATH_A` | `context.path_b_confirmed == false` | S-03 (self) | set `context.path_a_confirmed = true` | R-03, R-07 |
| T-04 | S-03 `DEPLOY_CONFIRM_PENDING` | E-03 `DEPLOY_CONFIRM_PATH_A` | `context.path_b_confirmed == true` | S-04 `DEPLOYED_CONFIRMED` | set `context.path_a_confirmed = true`; **set `deployment_confirmed` latch (one-way)** | R-03, R-04, R-07 |
| T-05 | S-03 `DEPLOY_CONFIRM_PENDING` | E-04 `DEPLOY_CONFIRM_PATH_B` | `context.path_a_confirmed == false` | S-03 (self) | set `context.path_b_confirmed = true` | R-03, R-07 |
| T-06 | S-03 `DEPLOY_CONFIRM_PENDING` | E-04 `DEPLOY_CONFIRM_PATH_B` | `context.path_a_confirmed == true` | S-04 `DEPLOYED_CONFIRMED` | set `context.path_b_confirmed = true`; **set `deployment_confirmed` latch (one-way)** | R-03, R-04, R-07 |
| T-07 | S-04 `DEPLOYED_CONFIRMED` | E-19 `ENTER_COMMISSIONING` | none | S-05 `COMMISSIONING` | — | R-05 |
| T-08 | S-05 `COMMISSIONING` | E-05 `COMMISSIONING_COMPLETE` | none | S-06 `COMMS_TTC` | begin TT&C downlink (first nominal mode) | R-06 |
| T-09 | `{S-06, S-07, S-08, S-09}` | E-06 `SCHEDULER_SELECT_TTC` | none | S-06 `COMMS_TTC` | switch/continue TT&C downlink; log mode change | R-11, R-13, R-17 |
| T-10 | `{S-06, S-07, S-08, S-09}` | E-07 `SCHEDULER_SELECT_SSTV` | none | S-07 `COMMS_SSTV` | switch/continue SSTV downlink; log mode change | R-11, R-13 |
| T-11 | `{S-06, S-07, S-08, S-09}` | E-08 `SCHEDULER_SELECT_VOICE` | none | S-08 `COMMS_VOICE` | switch/continue voice downlink; log mode change | R-11, R-13 |
| T-12 | `{S-06, S-07, S-08, S-09}` | E-09 `SCHEDULER_SELECT_IDLE` | none | S-09 `COMMS_IDLE` | end active downlink if any; log mode change | R-11, R-13, R-18 |
| T-13 | `{S-06, S-07, S-08, S-09}` | E-10 `PASS_END` | `elevation < P-015` | S-09 `COMMS_IDLE` | end downlink; log pass end | R-12 |
| T-14 | `{S-05, S-06, S-07, S-08, S-09}` | E-11 `FAULT_DETECTED` | `fault_count >= P-019` | S-10 `SAFE_MODE` | suspend non-TTC downlink; log rationale (CR-02) | R-21, R-31 |
| T-15 | `{S-05, S-06, S-07, S-08, S-09}` | E-12 `POWER_LOW` | `battery_soc <= P-013` | S-10 `SAFE_MODE` | suspend non-TTC downlink; log rationale (CR-02) | R-21, R-25, R-31 |
| T-16 | `{S-05, S-06, S-07, S-08, S-09}` | E-17 `WATCHDOG_TIMEOUT` | none | S-10 `SAFE_MODE` | suspend non-TTC downlink; log rationale (CR-02) | R-21, R-31 |
| T-17 | `{S-03, S-04, S-05, S-06, S-07, S-08, S-09, S-10}` | E-13 `GROUND_SAFE_MODE_CMD` | none | S-10 `SAFE_MODE` | suspend non-TTC downlink; log rationale: ground override (CR-01, highest rank) | R-22, R-31 |
| T-18 | S-10 `SAFE_MODE` | E-15 `AUTONOMOUS_RECOVERY_CONDITIONS_MET` | `context.deployment_confirmed == true` | S-05 `COMMISSIONING` | resume nominal rotation; log rationale | R-05, R-23, R-25, R-31 |
| T-21 | S-10 `SAFE_MODE` | E-14 `GROUND_OVERRIDE_EXIT_SAFE` | `context.deployment_confirmed == true` | S-05 `COMMISSIONING` | resume nominal rotation; log rationale | R-05, R-24, R-31 |
| T-25 | S-10 `SAFE_MODE` | E-15 `AUTONOMOUS_RECOVERY_CONDITIONS_MET` | `context.deployment_confirmed == false` | S-03 `DEPLOY_CONFIRM_PENDING` | resume deployment confirmation (path flags kept); log rationale | R-05, R-23, R-31 |
| T-26 | S-10 `SAFE_MODE` | E-14 `GROUND_OVERRIDE_EXIT_SAFE` | `context.deployment_confirmed == false` | S-03 `DEPLOY_CONFIRM_PENDING` | resume deployment confirmation (path flags kept); log rationale; restart ground-contact timer | R-05, R-24, R-31 |
| T-22 | `{S-01 .. S-10}` (any state) | E-16 `RESET` | none (unconditional; injectable mid non-volatile write) | reloaded from persisted A/B bank (target state per last-valid persisted record) | reload from NVM; `deployment_confirmed` latch preserved if previously set; select surviving bank via CRC32 + monotonic sequence number | R-04, R-27, R-28, R-29 |
| T-23 | `{S-01 .. S-10}` (any state) | E-18 `UPLINK_CMD_GENERIC` | none | `null` (self-loop, no state change) | log command received; no state change unless the ground-command decoder maps it to E-13/E-14 (out of FSM scope) | R-31, R-33 |
| T-24 | `{S-03 .. S-10}` (RF enabled onward) | E-20 `COMMS_LOSS_TIMEOUT` | `elapsed(ground_contact_timer) >= P-025` (2 days) | reloaded from persisted A/B bank (same mechanism as T-22) | reload from NVM; restart ground-contact timer | R-34 |

**Week 1-2 review correction:** T-17's `From` set now starts at `S-03`
(not `S-05`), and its actions now include `suspend non-TTC downlink` to
match T-14/T-15/T-16 (an earlier draft had the ground-commanded entry path
omit this action while every autonomous entry path included it — an
inconsistency, not an intentional difference). T-19 and T-20 (a
`SAFE_RECOVERY_PENDING` state and its exit) are retired: they modeled a
`P-020 == "ground_only"` branch that was permanently unreachable in this
config, since `P-020` is fixed to `autonomous_permitted_with_override` here
— see `docs/decisions/0002-config-schema-stress-test.md`. T-18's guard is
now `none`: recovery is unconditional once `E-15` fires (the event itself
already encodes "conditions are met"; there is no second policy check to
gate on in this config).

**Decision 0010 correction:** T-18 and T-21 now carry the guard
`context.deployment_confirmed == true`, and T-25/T-26 return a
latch-unset SAFE_MODE to `S-03`. Because T-17 starts at `S-03`, SAFE_MODE
is reachable before the latch is set; the earlier unconditional exits to
`S-05` let commissioning and nominal comms start with
`deployment_confirmed` false (found by TLC, see
`docs/decisions/0010-safe-mode-exit-respects-deployment-latch.md`). The
guard on T-18 is a latch check, not a recovery-policy gate: E-15 still
means "conditions met".

## Explicitly excluded (illegal) examples

These are called out because they are easy to get wrong when the engine is
implemented — they must resolve to a no-op, not to an exception or a silent
success:

- `(S-01 STOWED, E-06 SCHEDULER_SELECT_TTC)` — no comms mode may be selected before RF inhibit even starts.
- `(S-02 RF_INHIBIT, any SCHEDULER_SELECT_*)` — RF is inhibited by construction; the scheduler must not be able to force a transmit state during this window regardless of priority.
- `(S-02 RF_INHIBIT, E-13 GROUND_SAFE_MODE_CMD)` — RF is inhibited, so no uplink can physically arrive; a ground command cannot be received in this state. Ground override becomes legal at `S-03`, once RF is enabled — this is the deployment-confirmation-stall escalation path (see `../parameters.md` notes on `P-011`/`P-012`).
- `(S-02 RF_INHIBIT, E-20 COMMS_LOSS_TIMEOUT)` — RF is not yet enabled, so `ground_contact_timer` has never been armed and no comms-loss condition can exist yet. `T-24` becomes legal at `S-03`, once RF is enabled, same as `E-13` above.
- `(S-03 DEPLOY_CONFIRM_PENDING, E-19 ENTER_COMMISSIONING)` — commissioning cannot start before both confirmation paths agree (`deployment_confirmed` latch must be set first).
- `(S-01 STOWED, E-15 AUTONOMOUS_RECOVERY_CONDITIONS_MET)` — safe-mode recovery is meaningless before deployment.
