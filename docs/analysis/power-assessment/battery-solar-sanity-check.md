# Battery/Solar Constants Sanity Check

**Superseded by the POQUITO-sourced power update** (see `docs/parameters.md`
SIM-005 through SIM-012). The constants this document validates below are
the *prior placeholder values* (`BATTERY_CAPACITY_WH=10.0`,
`SOLAR_GEN_W=2.5`, flat `DRAW_W_*` held for an entire comms-mode pass
duration) — all now replaced by real POQUITO flight figures
(`BATTERY_CAPACITY_WH=4.5`, `SOLAR_GEN_W=0.4`, and a 156 s transmit-burst
model for comms draw; see `sim/scenario.py` and `sim/power.py`'s
`draw_for_state_category()`). Since the current values are `Confidence:
Cited` (sourced directly from Franzese et al. 2026) rather than
`Assumed`/"engineering judgment," this document's original purpose —
validating an assumed placeholder against DOD norms — no longer applies in
its original form, and the "draw held for the whole pass duration" framing
below no longer matches the burst-mode draw model. The current burst/idle
energy-balance picture (short 3.415-5.1225 W bursts costing ~3.3% DOD per
burst, closed by idle-mode recharge within the same orbit, matching
POQUITO's own published 410 mWh generated vs. 299 mWh consumed per orbit)
is analyzed in
`docs/analysis/mission-analysis-specialist/orbit-and-eclipse-crosscheck.md`'s
"Why this matters" section (§3) instead of here. The rest of this document
is retained unmodified as a historical record of the pre-update placeholder
validation.

---

Independent sanity-check of `sim/scenario.py`'s battery/solar constants
(SIM-005..SIM-010 in `docs/parameters.md`, currently labeled
`Confidence: Assumed` / "engineering judgment") against Li-ion
depth-of-discharge norms and this mission's actual eclipse exposure. This is a read-only
check — it does not modify `sim/scenario.py`, `docs/parameters.md`, or any
committed baseline results. It is a confirm-or-
challenge exercise on already-assumed constants, not a from-scratch EPS
architecture (bus voltage, MPPT vs. DET, harness losses, and battery
chemistry/vendor selection are all out of scope — not addressed by the
use-case document).

**Constants under check** (`sim/scenario.py`):
`BATTERY_CAPACITY_WH = 10.0`, `SOLAR_GEN_W = 2.5`,
`DRAW_W_IDLE = 0.3`, `DRAW_W_COMMS_TTC = 0.8`, `DRAW_W_COMMS_SSTV = 1.2`,
`DRAW_W_COMMS_VOICE = 1.0`.

**Eclipse input**: from the companion cross-check
(`docs/analysis/mission-analysis-specialist/orbit-and-eclipse-crosscheck.md`),
this orbit's beta angle swings between ~56° and ~79° over a year and
crosses into eclipse for a multi-month window each year. Two eclipse
duration figures are used below:
- **Theoretical absolute worst case** (β=0, edge-on to Sun — does not
  actually occur at this orbit's inclination per the year-scan, included
  only as a conservative upper bound): 35.61 min/orbit (37.2% of the
  5738.993 s period).
- **Realistic worst case actually found in the year scan** (β≈56.07°, the
  most-eclipsing point sampled at 30-day resolution): 24.24 min/orbit.

## 1. Depth-of-discharge check

Energy drawn during one worst-case eclipse pass, per FSM comms mode,
against the 10 Wh capacity:

| Mode | Draw (W) | Energy @ 35.61 min (theoretical worst) | DOD | Energy @ 24.24 min (realistic worst) | DOD |
|---|---|---|---|---|---|
| IDLE | 0.3 | 0.178 Wh | 1.78% | 0.121 Wh | 1.21% |
| COMMS_TTC | 0.8 | 0.475 Wh | 4.75% | 0.323 Wh | 3.23% |
| COMMS_SSTV | 1.2 | 0.712 Wh | 7.12% | 0.485 Wh | 4.85% |
| COMMS_VOICE | 1.0 | 0.594 Wh | 5.94% | 0.404 Wh | 4.04% |

Even at the theoretical (physically unreachable for this orbit) worst
case and the highest-draw mode (SSTV, 1.2 W), a single eclipse pass costs
**at most ~7% DOD**. `power-assessment`'s own reference DOD policy for a
high-cycle-count LEO Li-ion battery is 20–40% per cycle — this orbit's
worst-case single-eclipse draw is well under a third of even the
conservative end of that range.

**Assessment: the 10 Wh capacity is not undersized — if anything, it
carries comfortable headroom** relative to a single eclipse pass at any
modeled comms draw. This does not mean 10 Wh is wasteful: it also has to
cover multiple consecutive eclipse passes without full daylight recharge
in between (not modeled here, since `sim/driver.py`'s scheduler-driven
comms sessions are short relative to a pass, not continuous), cell aging,
and non-comms housekeeping loads this simulation doesn't model (OBC
baseline draw, ADCS if present, thermal heaters) — none of which are in
this project's scope. Read this as "not obviously
wrong," not "provably sufficient for a real spacecraft."

## 2. Energy-balance closure check

Does daylight solar generation recharge what a worst-case eclipse
deficit costs, within the same orbit?

- Daylight portion of the orbit at the theoretical worst case (β=0):
  60.04 min (62.8% of the period).
- Recharge available at `SOLAR_GEN_W = 2.5 W` over that daylight window:
  **2.502 Wh**.
- Worst-case eclipse deficit at the highest comms draw (SSTV, 1.2 W,
  theoretical worst-case 35.61 min eclipse): **0.712 Wh**.
- **Margin: +1.79 Wh (the daylight recharge is ~3.5x the worst-case
  eclipse deficit).**

**Assessment: the energy budget closes comfortably** even under the
theoretical worst-case eclipse/draw combination that doesn't actually
occur for this specific orbit. `SOLAR_GEN_W = 2.5 W` is not marginal
relative to the modeled draws.

## 3. Cross-check against the real committed baseline

Per the companion orbit analysis, `docs/baseline-results.md`'s actual 48h
run never enters eclipse at all (the fixed TLE epoch sits past the
critical beta angle for several months around that date) — so this
sanity check's eclipse-DOD numbers above describe a scenario the current
baseline doesn't exercise, not a re-derivation of anything already in
`docs/baseline-results.md`. The real baseline's battery behavior is
simpler than modeled here: net power is always positive (max draw 1.2 W
< 2.5 W solar, continuous sunlight), so SoC stays near 100% for the whole
48h run and the P-013 safe-mode threshold (25%) is never approached.

## Summary

| Check | Result |
|---|---|
| Single-eclipse DOD at max comms draw | ≤7.1% (theoretical worst case), ≤4.9% (realistic worst case) — comfortably under the 20-40% LEO Li-ion norm |
| Energy-balance closure (worst-case eclipse) | Closes with ~3.5x margin |
| Committed baseline's actual eclipse exposure | Zero — see orbit cross-check |

**Recommendation**: no change to `sim/scenario.py`'s SIM-005..SIM-010
values or their `docs/parameters.md` rationale — the existing "engineering
judgment" / `Confidence: Assumed` labeling is validated as reasonable by
this check, not merely asserted. If a future baseline variant wants to
exercise real eclipse-driven power stress (see the companion orbit
analysis's recommendation), these constants have enough headroom that
they would not need re-sizing to survive it — the interesting behavior to
watch for in that case would be *scheduling/delivery* effects during
eclipse (comms availability, not battery survival), not a power shortfall.
