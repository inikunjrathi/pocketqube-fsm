# Decision Record 0003 — Week 1-2 Critical Review

**Date:** 2026-07-18, before Phase 2 (Week 3 engine implementation) began.

## Process

Before writing any engine code against `config/config-a.yaml` and
`config/config-b.yaml`, all Week 1-2 documents were reviewed critically —
by a reader without authorial investment in the material, followed by
independent verification of every claimed finding against the actual files
(re-reading the relevant lines, re-running cross-reference and reachability
checks) before accepting or fixing anything. Nothing below was fixed on
the reviewer's say-so alone; every item was confirmed against the source
files first.

This was worth doing now specifically because Week 3 turns these YAML
files load-bearing: a transition-table interpreter will execute
`step(state, event, context)` against them directly. A logic error here —
an unreachable state, an unarmed guard, a missing conflict-resolution
entry — becomes a real runtime bug once code depends on it, and is more
expensive to find once tests are being written against the (wrong)
expected behavior.

## Findings and resolutions

### Blocking (fixed)

1. **Config B's deployment sequence deadlocked permanently.** The original
   `T-01` used a single event with a guard —
   `elapsed(switch_debounce) >= PB-002` — that nothing ever armed; no
   transition started a `switch_debounce` timer anywhere. Deployment could
   never complete. **Fix:** split into `T-01` (arms the timer on
   `SEPARATION_DETECTED`) and a new `T-02` (checks elapsed, on a new
   `E-14 SWITCH_DEBOUNCE_ELAPSED` event), mirroring Config A's existing
   start/check pattern for its own RF-inhibit timer. Required inserting a
   new `S-02 DEPLOY_CONFIRM_PENDING` state, shifting all downstream
   state/transition IDs. Config B: 6→7 states, 13→14 transitions.

2. **`to: null` was used in both configs but not sanctioned by the
   schema.** `docs/config-schema.md` only documented a target-state-ID
   string or `"reload_from_persistence"` as legal values for
   `TransitionDef.to`. **Fix:** schema now documents `null` as a legal
   third value, meaning self-loop / no state change.

3. **`E-15 AUTONOMOUS_RECOVERY_CONDITIONS_MET` was absent from Config A's
   `conflict_resolution` ranking**, violating the schema's own stated
   invariant ("an event ID must appear in exactly one rank"). **Fix:**
   added to rank 2 (`fault_watchdog`), alongside the other monitor-sourced
   events it's symmetric with.

4. **`P-011`/`P-012` (deployment-confirmation timeout/window parameters)
   were declared but never consumed by any guard** — no escalation path
   existed if one confirmation path never asserted; the FSM would sit in
   `S-03` forever, and ground override wasn't reachable from `S-03` either
   (ground-override transition, then `T-17`, started at `S-05`). **Fix:**
   extended `T-17`'s `From` set to include `S-03`/`S-04` (RF is physically
   enabled from `S-03` onward, so ground commands can arrive there), giving
   ground operators an escalation path if confirmation stalls. Deliberately
   did **not** add an autonomous timeout transition — jumping FSM state on
   a single unconfirmed signal, with no second source agreeing, would
   itself be the kind of ungoverned autonomy the Human-in-the-Loop
   requirement cautions against. `P-011`/`P-012` remain defined as
   monitoring thresholds, documented as not guard-consumed.

5. **`S-11 SAFE_RECOVERY_PENDING` and transitions `T-19`/`T-20` were
   unreachable dead code in Config A as actually configured.** They
   modeled a `P-020 == "ground_only"` branch, but `P-020` is fixed to
   `autonomous_permitted_with_override` for this config — the branch could
   never fire. This also meant Phase 3's "every transition-table row
   exercised" exit criterion (W6) could not honestly be met for
   `T-19`/`T-20` without instantiating a hypothetical parameter override.
   **Fix:** removed `S-11`/`T-19`/`T-20` from Config A. `T-18` (autonomous
   recovery) is now unconditional — `P-020` (and Config B's `PB-010`) are
   reclassified as **documentation labels** describing which structural
   variant a config implements, not runtime-branched guard values. The
   ground-only structural variant is fully demonstrated by Config B, which
   never defines an autonomous-recovery event or state at all — a stronger
   piece of RQ1 evidence than a dead branch inside Config A would have
   been.

### Should-fix (fixed)

6. **R-22 claimed broader ground-override coverage than `T-17` actually
   provided** (missing `S-04`). Resolved by the `T-17` `From`-set fix in
   item 4 above; requirement wording updated to match.
7. **Ground-commanded safe-mode entry omitted the `suspend_non_ttc_downlink`
   / `suspend_downlink` action that every autonomous-entry transition
   included**, identically in both configs. Fixed by adding the action to
   the ground-override transition in both `config-a.yaml` (`T-17`) and
   `config-b.yaml` (`T-11`).
8. **R-10/R-14 said mode-select events were illegal "S-01..S-04"**, but the
   actual `From`-set boundary is `S-05` (commissioning) — mode-select only
   becomes legal at `S-06`. Wording corrected in both requirements.
9. **R-12/RB-06 claimed `PASS_END` returns to idle "unconditionally"**
   despite the transition carrying an explicit elevation guard. Reworded
   to describe the guard rather than contradict it.
10. **R-26 described `P-020` as "config-swappable" with Config B "differing
    on exactly this field,"** implying a shared field with two values, when
    Config B's `PB-010` was never actually read by any guard — the
    difference is structural (which events/states exist), not a value
    substitution. Reworded per the item 5 fix.

### Minor (fixed where cheap, otherwise left as noted)

11. Traceability was one-directional in places (e.g. `R-04` cited `T-22`,
    but `T-22`'s own `requirements` field didn't cite `R-04` back). Fixed
    for the `R-04`/`T-22` case since it was already being touched; not
    exhaustively re-audited for every pair given time constraints — worth
    a pass when the Phase 2 verification-matrix generator (W5) is built,
    since that tool will walk these links mechanically and any remaining
    gaps will surface then.
12. `conflict-resolution.md`'s worked example 3 mischaracterized rank
    precedence (CR-01 beats CR-04) as the intra-rank tie-break rule.
    Reworded for accuracy.
13. Config-local reuse of `T-01`, `T-02`, etc. across both configs for
    structurally unrelated transitions is schema-legal (IDs are
    config-local) but will read confusingly in a side-by-side verification
    matrix. Left as-is for Week 1-2; worth a config-qualified prefix
    (`A-T-01` / `B-T-01`) if the Phase 2 verification-matrix generator
    ends up presenting both configs in one table — deferred, not fixed,
    since it's a presentation concern, not a correctness one.

## What this changes for Phase 2

Nothing about the schema shape (`docs/config-schema.md`'s top-level
structure is unchanged from decision 0002 — only the documented value
space for `to` was widened). The transition interpreter can be built
against `config-a.yaml`/`config-b.yaml` as they now stand. State and
transition counts changed (Config A: 11→10 states, 23→21 transitions;
Config B: 6→7 states, 13→14 transitions) — any Week 1 narrative elsewhere
citing the old counts should be read as superseded by this record and by
`config-a-states.md`/`config-a-transitions.md`/`config-b-overview.md`,
which have been updated in place.
