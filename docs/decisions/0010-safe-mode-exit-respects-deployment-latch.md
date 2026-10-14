# Decision Record 0010 — SAFE_MODE Exit Respects the Deployment Latch (Config A)

**Date:** 2026-10-12 (manuscript-review response, verification track)

## What was done

The refined TLC model (`tools/generate_tla_spec.py`, with the hand-written
properties in `docs/tla/independent_requirements.yaml`) found that Config A
violated R-05 ("Commissioning begins only after the `deployment_confirmed`
latch is set"). The trace takes five steps:

```
STOWED -SEPARATION_DETECTED-> RF_INHIBIT -RF_INHIBIT_TIMER_EXPIRED->
DEPLOY_CONFIRM_PENDING -GROUND_SAFE_MODE_CMD (T-17)-> SAFE_MODE
-AUTONOMOUS_RECOVERY_CONDITIONS_MET (T-18) or GROUND_OVERRIDE_EXIT_SAFE (T-21)->
COMMISSIONING -COMMISSIONING_COMPLETE-> COMMS_TTC   (deployment_confirmed still false)
```

The real engine reproduced it. It came from the decision 0003 / Week 1-2
review fix. That fix started T-17 at S-03 so that ground could escalate a
stalled confirmation. T-18 and T-21 still sent every SAFE_MODE exit to S-05
unconditionally. Configs B and C are not affected, because their
ground safe-mode row starts at DEPLOYED_CONFIRMED.

Changes to `config/config-a.yaml`:

- T-18 and T-21 gain the guard `context.deployment_confirmed == true`.
  Their targets, actions and order are unchanged.
- New T-25 (E-15) and T-26 (E-14), from S-10, with the guard
  `context.deployment_confirmed == false`, target S-03
  DEPLOY_CONFIRM_PENDING. Actions are `resume_deployment_confirmation`
  (opaque), `log_rationale`, and for the ground path
  `start_ground_contact_timer`. Requirements are R-05, R-23 or R-24, and R-31.
  They are listed after T-18/T-21, so first-match order only reaches them
  when the latch is unset. The path flags (`path_a_confirmed` and
  `path_b_confirmed`) stay in context, so a path that asserted before the
  escalation does not need to assert again.
- IDs: T-19 and T-20 stay retired (decision 0002) and are not reused. The
  next free IDs are T-25 and T-26.
- Conflict ranking: unchanged. Both new rows use E-14 and E-15, which are
  already ranked.

Follow-on edits:
- `docs/requirements/requirements-config-a.md`: R-05, R-23 and R-24
  wording and their related-transition lists. No new requirement ID was
  added, because R-05 already states the obligation.
- `docs/state-machine/config-a-transitions.md`: rows plus a correction note.
- `docs/state-machine/config-a-diagram.md`: regenerated.
- `mcu/firmware/app/src/engine_config_table.{c,h}`: regenerated, 24
  transitions.
- Test fixtures and count guards: T-18/T-21 fixtures now set the latch, and
  T-25/T-26 have fixtures. The guarded-row count in
  `tests/test_engine_guards_c.py` is now 24. `tests/test_driver.py`'s
  Config A autonomous-recovery test now starts with the latch set.
- `docs/tla/independent_requirements.yaml`: SAFE_MODE added to Config A's
  `pre_latch_states`, since R-22 explicitly allows safe mode before the
  latch.

## Alternatives rejected

- **Start T-17 at S-04.** This removes the defect but also the only escalation
  for a stalled confirmation, which R-22 asks for. P-011 and P-012 are
  still read by no guard.
- **A second safe state for pre-latch safe mode.** It would also work, but
  it adds a state, events and conflict-rank entries for what one guard per
  exit already expresses.
- **Exit to S-02 or S-01.** RF is already enabled once S-03 has been
  reached. Re-entering the inhibit timer would silence the beacon path for
  no safety benefit.

## Consequences (verified)

- TLC (2.19): Config A now passes every property, including
  `PostLatchStatesHaveLatch`: 7,657 states generated, 434 distinct,
  depth 11. B and C are unchanged (1,798/121/9 and 1,991/128/9). The
  pre-fix Config A checked against the same requirements file still fails
  with the 5-step trace above.
- The seed-42 Config A reference run never enters SAFE_MODE. The
  recaptured Python step() trace (35,763 calls) is identical, entry for
  entry, to the archived
  `mcu/host_bridge/evidence/task8_baseline_seed42/config-a/python_trace.jsonl.gz`.
  The Renode firmware replay was not rerun.
- Simulation outputs: see `build/review/B-verification.md`, "Config A fix".

## What was deliberately NOT done

- `docs/verification-matrix.md` was not regenerated, because it has
  uncommitted user edits.
- `engine/` was not touched. The fix is config data only, which is the
  point of the architecture.
