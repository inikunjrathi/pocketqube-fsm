# Decision Record 0009 — Explicit Comms-State → Transmit-Class Power Mapping

**Date:** 2026-10-11 (manuscript-review response, simulation track)

## What was done

The simulation's power model used to pick a comms state's transmit draw by
matching the FSM state's **name** against `COMMS_TTC` / `COMMS_SSTV` /
`COMMS_VOICE` (`sim/power.py::draw_for_state_category`, called from
`sim/driver.py` with `cfg.states[state].name`). Config A has one state per
data class, so its names matched. Config B and Config C collapse every
downlink into one `COMMS_ACTIVE` state (S-05). That name matched nothing and
fell through to the documented IDLE default. So every B/C downlink was
charged `DRAW_W_IDLE` (0.0996 W) instead of a 3.4–5.1 W transmit burst, and
B/C's energy per delivered bit came out as the run-independent constant
`DRAW_W_IDLE / LINK_DATA_RATE_BPS` = 1.0375e-05 J/bit (`sim/metrics.py`'s own
comment noted this). Their battery trajectory never saw a transmit burst
either. The manuscript reviewer flagged this, and it is a real defect.

Replaced the name match in `sim/driver.py` with an explicit, validated
mapping in `sim/power.py`:

- `STATE_TRANSMIT_CLASS[config_id][state_id]` gives each comms-mode state a
  fixed data class (`"TTC"`, `"SSTV"`, `"CODEC2_M17"`), `SERVED_CLASS` (the
  state transmits whichever class is being served), or `None` (no payload
  transmission, e.g. `COMMS_IDLE`). Config A: S-06/07/08 fixed, S-09 None.
  Config B/C: S-05 `SERVED_CLASS`, S-06 None. Deployment and safe states are
  not listed and always draw `DRAW_W_IDLE`, as before.
- `transmit_class_map(cfg)` validates the row against the loaded config. It
  raises `PowerModelError` if any of these hold: the config has no row; the
  row's state ids are not exactly the config's comms-mode states; a class is
  unknown; or the row contradicts the config's own scheduler-select
  transitions. Those transitions require a fixed-class state to be the target
  of exactly that class's select event, a `SERVED_CLASS` state to be the
  target of every class's select event, and a `None` state to be the target
  of none. The driver calls it once per run, so an unknown or missing comms
  state stops the run before the first tick.
- In the driver, the burst window (SIM-012, 156 s) is keyed on the **mode**
  = (state, active transmit class), not on the state alone. In Config B/C,
  switching data class inside `COMMS_ACTIVE` starts a new burst, just as
  Config A's switch between per-class states does. `served_class` is cleared
  whenever a non-delivery transition (POWER_LOW, recovery, PASS_END) changes
  the state.
- The burst-draw table stays `_COMMS_BURST_DRAW_W_BY_CATEGORY` (single source
  of truth, so `tools/generate_sensitivity_analysis.py`'s scoped monkeypatch
  of it still reaches the driver), and a data class is mapped onto it via
  `TRANSMIT_CATEGORY_BY_DATA_CLASS`.

## Why a sim-side table rather than a YAML schema field

Power draw is a property of the simulated spacecraft, not of the FSM
specification. Putting it in `config/*.yaml` would change the graded Phase 1
schema. The table lives under `sim/`, the evaluation
harness. The engine stays configuration-driven, and `sim/driver.py` still
never references `config_id` (its AST test still passes). The cost is that a
new config needs one row here, and the validator says so explicitly.

## Consequences (verified)

- **Config A: bit-identical.** In Config A the mode changes exactly when the
  state changes, so draws and energies are unchanged. A golden SHA-256 of
  Config A's seed-42 deliveries and per-tick SoC trace, captured with the old
  model, is asserted in `tests/test_power.py::
  test_config_a_seed42_is_bit_identical_to_pre_0009_name_mapping`. The
  one-station and two-station seed-42 runs were also compared field by field
  before and after the change: identical.
- **Config B/C:** delivery, latency, deadline outcomes and FSM state sequence
  are unchanged, field for field. Only `energy_wh` and the battery SoC trace
  change. Per-item energies now equal Config A's exactly. B's seed-42 energy
  per delivered bit goes from 1.0375e-05 to 3.38873e-04 J/bit. B/C's minimum
  SoC goes from 98.72% to 91.29% (one station) and to 70.65% (two stations).
  B/C SoC differs from A only for the first 70 ticks after t=0, when Config
  A's bootstrap lands in COMMS_TTC for one tick and draws a burst (a
  pre-existing artefact), until the battery saturates at 100%.

## What was deliberately NOT done, and why

1. **`policy/oracle.py` was not changed.** It is owned by the policy track,
   outside this change's scope. Its rollout still calls the legacy
   `draw_for_state_category(cfg.states[state].name, ...)` and
   `sim.driver._item_energy_wh`, both kept with unchanged signatures. So the
   oracle's *internal* rollout energy estimate for Config B still uses idle
   draw. Energy is only the third key of the oracle's lexicographic score
   (after TT&C and other deadline misses). Every number the driver reports
   under the oracle policy, including energy, uses the corrected model.
   Follow-up for the policy track: switch the rollout to
   `transmit_class_map` / `resolve_transmit_class` / `transmit_draw_w`.
2. **No change to config/*.yaml, SIM-0xx values, or the reference scenario.**
