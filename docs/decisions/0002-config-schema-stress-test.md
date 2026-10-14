# Decision Record 0002 — Config Schema Design and Config B Stress Test

**Date:** 2026-07-18 (Week 2 work, plan section 7)

> **Superseded in part by decision 0003.** A critical review conducted the
> same day found and fixed several defects in the configs described below
> (a deployment deadlock in Config B, unreachable dead code in Config A,
> and others). The state/transition/event counts quoted in this record are
> the **pre-review** counts and no longer match the current
> `config/config-a.yaml`/`config/config-b.yaml`. See
> `docs/decisions/0003-w1-2-critical-review.md` for the current counts and
> the full list of fixes. The schema-generality conclusion below (no
> structural schema change was needed) still holds.

## What was done

1. Formalized Config A's Week 1 prose documents (`docs/state-machine/`,
   `docs/parameters.md`, `docs/conflict-resolution.md`) into
   `docs/config-schema.md` — a schema defining states, events, transitions,
   parameters, latches, data-class priority, conflict-resolution ordering,
   and mode-exclusivity groups as YAML data.
2. Wrote `config/config-a.yaml` as a full instance of that schema (11
   states, 19 events, 23 transitions, 19 tunable parameters).
3. Designed Config B — single-path deployment switch, no RF inhibit, single
   downlink mode, ground-commanded safe-mode exit only (plan section 5) —
   directly against the schema, without a Week-1-style prose pass first
   (`config/config-b.yaml`, 6 states, 13 events, 13 transitions, 14
   tunable parameters; overview in
   `docs/state-machine/config-b-overview.md`, requirements in
   `docs/requirements/requirements-config-b.md`).

## Result: did Config B force a schema change?

**No.** Config B loads under the same top-level schema shape as Config A
with zero structural additions:

- Fewer states/events/transitions is handled natively — the schema has no
  minimum-count assumptions anywhere.
- The single-downlink-mode structure required no new field: `COMMS_ACTIVE`
  is just a state like any other, and `mode_exclusivity_groups` degrades
  gracefully to a two-member group (`[COMMS_ACTIVE, COMMS_IDLE]`) instead
  of Config A's four-member group — the schema doesn't special-case group
  size.
- Removing the autonomous-recovery path (no `AUTONOMOUS_RECOVERY_CONDITIONS_MET`
  event, no `SAFE_RECOVERY_PENDING` state) required no schema change —
  event and state lists are config-local; a config simply omits what it
  doesn't need.
- The dual-path-to-single-path deployment confirmation collapsed from 4
  transition rows with context-flag bookkeeping (Config A's T-03..T-06) to
  1 row with a debounce guard (Config B's T-01) — again no schema change,
  just fewer rows.
- `conflict_resolution`'s five-rank structure carried over unchanged, just
  with different `member_events` lists per config — this is direct evidence
  that separating conflict-resolution ordering from data-class priority
  (as `docs/conflict-resolution.md` argues) was the right schema-level
  decision, not just a Config-A convenience.

This is the honest result the plan asks for (section 5: "If Config B
forces an engine change, the engine is not general — report that
honestly"). No engine exists yet to change, but the schema — the contract
the engine will be built against — held without modification.

## One correction made *because of* this exercise

Writing Config B's parameter list surfaced that `P-021`
(`persistence_bank_swap_policy`) had been scoped as a Config-A parameter in
`docs/parameters.md` (Week 1). Re-reading plan section 5 while deciding
whether Config B needed its own version of this parameter showed that the
persistence layer (A/B banks, CRC32, monotonic sequence number) is listed
under **Engine (mission-agnostic)**, not **Configuration (mission-specific)**.
It is therefore not something Config B — or any config — should carry as
tunable data.

**Fix applied:** `P-021` remains documented in `docs/parameters.md` (its
literature basis is still worth recording) but is now explicitly marked as
an Engine-level, shared-across-configs policy rather than a Config-A
parameter, and it is *not* included in either `config/config-a.yaml` or
`config/config-b.yaml`'s `parameters` list. This is a Week 1 scoping
mistake caught during Week 2 review, not a schema defect — worth recording
because it's exactly the kind of error the "write two dissimilar configs"
exercise is designed to catch.

## No other schema revisions were necessary

The schema as designed in `docs/config-schema.md` is unchanged from its
first draft. Both configs currently validate as well-formed YAML with all
internal ID cross-references (`S-`, `E-`, `T-`, `P-`/`PB-`) resolving,
checked by ad hoc script during this session (not yet a permanent test —
that's Phase 3, W6).
