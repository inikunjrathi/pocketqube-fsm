# Config Schema — Week 2 Design

This document defines what a state, event, guard, transition, latch, and
priority ordering look like **as data**, so a mission-specific
configuration is a YAML file the (not-yet-written) engine loads and passes
in — no mission constant ever appears in engine code (the plan's hard rule,
section 5).

This schema is derived by formalizing Config A's Week 1 prose documents
(`docs/state-machine/`, `docs/parameters.md`, `docs/conflict-resolution.md`)
into data, then stress-tested by writing Config B directly against it
(`config/config-b.yaml`) before any engine exists. See
`docs/decisions/0002-config-schema-stress-test.md` for the result of that
stress test.

## Top-level structure

```yaml
meta:
  config_id: string            # e.g. "config-a"
  name: string
  description: string
  version: string               # semantic, e.g. "0.1.0"

states: [ StateDef ]
events: [ EventDef ]
transitions: [ TransitionDef ]
parameters: [ ParameterDef ]
latches: [ LatchDef ]
data_class_priority: [ string ]        # ordered list of data-class names, highest first
conflict_resolution: [ ConflictRankDef ]  # ordered list, rank 1 = highest
mode_exclusivity_groups: [ ModeGroupDef ]
```

## `StateDef`

| Field | Type | Notes |
|---|---|---|
| `id` | string | Config-local ID, e.g. `S-01`. Unique within the config. |
| `name` | string | e.g. `STOWED` |
| `category` | string | Free-text grouping (e.g. `deployment`, `comms-mode`, `safe`) — used for documentation/diagram grouping only, not consumed by guard logic. |
| `description` | string | |
| `entry_actions` | `[string]` | Action identifiers fired on entry. May be empty. |
| `is_initial` | bool | Exactly one state per config must have `is_initial: true`. |

Latch membership is **not** a field on `StateDef` — it lives in the
top-level `latches` list (below) so a latch's "which states set it" and
"how it survives reset" logic is defined once, not scattered across state
entries. (This was a specific design question during Week 2 schema design —
see `docs/decisions/0002-config-schema-stress-test.md`.)

## `EventDef`

| Field | Type | Notes |
|---|---|---|
| `id` | string | e.g. `E-01` |
| `name` | string | e.g. `SEPARATION_DETECTED` |
| `source` | string | One of `onboard`, `ground`, `scheduler`, `harness`. |
| `description` | string | |

## `TransitionDef`

| Field | Type | Notes |
|---|---|---|
| `id` | string | e.g. `T-01` |
| `from` | `[string]` or `"*"` | List of state IDs this row applies from, or the literal string `"*"` meaning every state in the config (used for `RESET` and similar universal events). |
| `event` | string | Event ID. |
| `guard` | string or `null` | A boolean expression over `context` and parameter IDs (e.g. `"context.path_b_confirmed == true"`, `"elapsed(rf_inhibit_timer) >= P-010"`). `null` means unconditional. The **expression grammar itself is not fixed by this schema** — Week 3's guard evaluator defines what operators/functions are legal; this schema only fixes where the expression string lives and what it's evaluated against (`context`, parameter values). |
| `to` | string, `"reload_from_persistence"`, or `null` | Target state ID; the literal sentinel `"reload_from_persistence"` for reset-type transitions whose destination is determined by the persistence layer, not by this table; or `null` meaning **self-loop — no state change**, used for rows that only log/act without transitioning (e.g. a generic uplinked command that doesn't itself change FSM state). |
| `actions` | `[string]` | Action identifiers, executed in list order. |
| `requirements` | `[string]` | Requirement IDs this row is traceable to (report/verification-matrix use, not consumed by the engine). |

**Closed-world rule (schema-level, not just Config-A-specific):** any
`(state, event)` pair with no matching `TransitionDef` — after expanding
`from: "*"` and multi-member `from` lists, and after evaluating guards — is
illegal and the engine must no-op with a logged reason. This is a property
of the schema/engine contract, not something each config re-states.

## `ParameterDef`

| Field | Type | Notes |
|---|---|---|
| `id` | string | e.g. `P-010` |
| `name` | string | e.g. `rf_inhibit_silence_timer_s` |
| `value` | any | The default value. Type is implied by usage (number, string, list, enum). |
| `applies_to` | string | `both`, or a config ID. |
| `source` | string | Citation or `"engineering judgment"` or `"TBD"`. |
| `confidence` | string | `cited`, `assumed`, or `tbd`. |
| `rationale` | string | Required for every `assumed` row (section 4's rule carries forward from `parameters.md` into the schema unchanged). |

## `LatchDef`

| Field | Type | Notes |
|---|---|---|
| `name` | string | e.g. `deployment_confirmed` |
| `description` | string | |
| `set_by` | `[string]` | Transition IDs that set this latch. |
| `one_way` | bool | Always `true` for a latch by definition; kept explicit rather than implied, so the schema can be extended later with non-latching persisted flags without ambiguity. |
| `survives_reset` | bool | Must be `true` for every latch — this is the schema-level statement of RQ2's requirement, checked structurally (a latch defined with `survives_reset: false` would not be a latch and should not be declared here). |

## `ConflictRankDef`

| Field | Type | Notes |
|---|---|---|
| `rank` | int | 1 = highest priority. Must be unique and contiguous within a config. |
| `category` | string | e.g. `ground_override`, `fault_watchdog`. |
| `member_events` | `[string]` | Event IDs belonging to this category. An event ID must appear in exactly one rank. |
| `tie_break` | string | Free-text description of the tie-break rule within this rank (e.g. `"timestamp, then event ID lexical order"`). Not a machine-evaluated field in Week 2 — formalizing tie-break as data is deferred to Phase 2 if the engine needs it structurally; Week 1–2 treat it as documentation carried through from `conflict-resolution.md`. |

**Explicit note:** `data_class_priority` (top-level, a flat ordered list)
and `conflict_resolution` (this section) are kept as two separate top-level
keys, never merged, to preserve the distinction established in
`docs/conflict-resolution.md` — one governs *which data item* the scheduler
picks, the other governs *which pending event* the FSM services first.

## `ModeGroupDef`

| Field | Type | Notes |
|---|---|---|
| `group_name` | string | e.g. `comms_modes` |
| `member_states` | `[string]` | State IDs that are mutually exclusive — at most one member state may be "active" at a time. For Config A this is the four `COMMS_*` states; a config with only one downlink mode may declare a group with a single member (trivially exclusive) or omit the group entirely. |

## Guard expression grammar (Week 3, `engine/guards.py`)

Every guard in `config-a.yaml`/`config-b.yaml`/`config-c.yaml` is a single
binary comparison — no config currently needs boolean `and`/`or`
combinators, so the evaluator does not support them yet (a real
requirement would extend this grammar, not work around it with string
hacks).

```
guard      := operand operator operand
operator   := "==" | "!=" | ">=" | "<=" | "<" | ">"
operand    := context_ref | telemetry_ref | param_ref | elapsed_call | literal
context_ref   := "context." IDENTIFIER        # e.g. context.path_a_confirmed
telemetry_ref := IDENTIFIER                    # e.g. fault_count, battery_soc, elevation
param_ref     := /[A-Z]+-\d{3}/                # e.g. P-010, PB-002, PC-012
elapsed_call  := "elapsed(" IDENTIFIER ")"     # e.g. elapsed(rf_inhibit_timer)
literal       := NUMBER | "true" | "false" | QUOTED_STRING
```

Two distinct operand kinds that look similar are deliberately not merged:

- **`context.*`** — FSM-internal state that persists across `step()` calls
  and is mutated only by actions (e.g. `context.path_a_confirmed`, set by
  an action string of the form `"set context.<name> = <value>"`). This is
  what the persistence layer (Phase 2, W4) saves and restores.
- **Bare identifiers** (`fault_count`, `battery_soc`, `elevation`) —
  telemetry/environment values supplied fresh by the caller on every
  `step()` invocation (sensor readings, simulation output). The FSM never
  writes these; it only reads them.

`elapsed(<timer_id>)` reads a context-persisted start timestamp. The
convention: an action named `start_<timer_id>` (e.g.
`start_rf_inhibit_timer`) arms the timer by recording the current time
under that exact name in `context`; `elapsed(<timer_id>)` must reference
the identical `<timer_id>` string. **Week 3 correction:** Config B
originally armed `start_switch_debounce_timer` but checked
`elapsed(switch_debounce)` — a naming mismatch that would have made the
guard never resolve the timer it meant to read. Fixed by aligning the
`elapsed()` argument to the action name exactly.

## Action string semantics (Week 3, `engine/fsm.py`)

Two forms of action string are recognized:

- **Context mutation**: `"set context.<name> = <value>"` — parsed and
  applied by the engine (updates the returned context dict). This is the
  only action form with engine-interpreted meaning.
- **Opaque identifier**: anything else (`enable_rf`, `log_rationale`,
  `suspend_non_ttc_downlink`, `start_<timer>`, ...) — the engine records
  these in the decision log verbatim but does not simulate their real-world
  effect (radio state, telemetry suppression, etc.). `start_<timer_id>` is
  the one opaque-looking identifier the engine *does* special-case, per
  the `elapsed()` convention above. Wiring opaque actions to real
  hardware/telemetry side effects is out of scope for this project
  (software-only, section "Constraint" of the plan); the decision log is
  the evidence that the correct action *would* have fired.

## What this schema deliberately does not fix yet

- **File layout / whether one file or multiple files per config** — both
  `config-a.yaml` and `config-b.yaml` are single files for Week 1–2; this
  may be revisited if a config grows large enough to warrant splitting
  (not expected at this project's scale).
- **Persistence-layer wiring for `RESET`** — Week 3's `step()` accepts an
  explicit `persisted` snapshot argument as a stand-in for the real A/B
  bank/CRC32/sequence-number persistence layer, which is Week 4 scope. See
  `engine/fsm.py` module docstring.
