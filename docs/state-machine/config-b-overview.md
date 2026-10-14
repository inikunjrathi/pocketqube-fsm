# Config B — Overview (deliberately dissimilar)

Per section 5 of the plan, Config B is written **directly against the
schema** (`docs/config-schema.md`) rather than through a Week-1-style prose
state/event/transition table set — the point of Week 2 is to test whether
the schema is expressive enough without that scaffolding. The authoritative
Config B specification is `config/config-b.yaml`; this document is a short
orientation, not a duplicate of the YAML.

## Structural differences from Config A

| Axis | Config A | Config B |
|---|---|---|
| Deployment confirmation | Dual-path (separation switch + timer, AND short-duration RF beacon) — both must agree | **Single-path**: one separation switch closure confirms deployment directly (after a short debounce) |
| RF inhibit | Silence timer before RF is enabled | **No RF inhibit** — RF is enabled as soon as the (much shorter) debounce timer elapses, not gated by a separate safety silence period |
| Downlink modes | Four (TT&C, SSTV, voice/data, idle) as distinct FSM states | **Single downlink mode** (active/idle only) — data-class arbitration happens entirely inside the scheduler's item selection, not as separate FSM states |
| Safe-mode exit | Autonomous recovery permitted, bounded by ground override (`P-020 = autonomous_permitted_with_override`) | **Ground-commanded exit only** (`PB-010 = ground_only`) — no autonomous safe-mode-exit event, no recovery-pending state |
| State count | 10 | 7 |
| Transition count | 22 | 15 |

Both configs' deployment sequences split "arm a timer" and "check the timer
elapsed" into two separate transitions (Config A: `T-01`/`T-02` for RF
inhibit; Config B: `T-01`/`T-02` for switch debounce) — this is a shared,
physically-necessary pattern (any timer needs a start event and a check
event), not a re-introduction of Config A's RF-inhibit *safety* mechanism
into Config B. The dissimilarity axes above are otherwise unaffected.

## Result

Config B loads under the same top-level schema (`meta`, `states`, `events`,
`transitions`, `latches`, `parameters`, `data_class_priority`,
`conflict_resolution`, `mode_exclusivity_groups`) with no structural
additions required. See
`docs/decisions/0002-config-schema-stress-test.md` for the full stress-test
finding, including corrections made as a result of designing Config B: the
persistence bank-swap policy was mis-scoped as a per-config parameter when
the plan places it under the mission-agnostic Engine (section 5), and a
Week 1-2 self-review (prompted by re-reading this file's own YAML with
fresh eyes) found that Config B's original `T-01` used a self-referential
guard that could never be satisfied — nothing armed the debounce timer it
checked — meaning deployment could never complete as originally written.
Fixed by splitting start-timer and check-elapsed into separate transitions,
matching Config A's own pattern for its RF-inhibit timer.

## Parameter ID namespace

Config A's assumed parameters use `P-01x`; Config B's use `PB-00x` to avoid
implying two configs share a numeric value they don't. Mission-wide fixed
parameters given directly by the use-case document (`P-001`, `P-002`,
`P-004`, `P-005`) are reused verbatim across both configs, since they are
genuinely shared, not independently assumed.
