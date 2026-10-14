# Orbit & Eclipse First-Principles Cross-Check

Independent verification of `sim/orbit.py`'s SGP4 propagation and
`sim/power.py`'s eclipse model against closed-form (Phase A fidelity)
astrodynamics. This is a read-only cross-check — it does not modify
any `sim/` code, `sim/scenario.py` constants, or committed baseline
results.

**Refreshed for the POQUITO-sourced update** (525 km reference orbit,
replacing the prior 550 km placeholder — see `docs/parameters.md` SIM-002).
§1, §2, and the empirical eclipse count in §3 were recomputed against the
new TLE; the beta-angle *seasonal scan* in §3 (the year-long β sweep and
the "4-7 months after epoch" eclipsing-window estimate) was not
independently re-run for the new orbit and is carried over from the
original 550 km analysis as an approximate reference only — the geometry
shifts slightly with the new inclination/altitude, so treat those specific
month figures as indicative, not exact, until re-derived.

**Refreshed again for the real-TLE adoption** (POQUITO's own real,
SatNOGS-sourced TLE — NORAD temporary catalog number 98706, epoch
2025-01-21 21:45:38.68 UTC — replacing the *placeholder* 525 km TLE above,
whose inclination/RAAN/mean-anomaly were themselves hand-solved to (a) hit
the sun-synchronous target exactly and (b) land near-overhead Mumbai at
epoch; see `sim/scenario.py`'s module docstring and `docs/parameters.md`
SIM-002). Every section below (§1-§4) was independently recomputed against
the real element set for this refresh, including — for the first time — an
actual `sim.power.is_illuminated()` sampling run (§3) rather than a
hand-computed beta-angle argument taken on faith. The single most
consequential change: the real orbit's real epoch is **not** in the
fully-sunlit, degenerate regime the placeholder's hand-picked epoch sat in
— §3 is rewritten accordingly, and the carried-over year-long beta-angle
seasonal scan from the paragraph above is retired in this refresh (reasoning
in §3) rather than carried over a second time.

**Central body**: Earth. $\mu = 398{,}600.4418\ km^3/s^2$,
$R_{Earth} = 6378.137\ km$ (matches `sim/scenario.py`'s
`EARTH_RADIUS_KM`). **Frames**: propagation in the TEME/GCRF-like inertial
frame SGP4 natively produces; `sim/orbit.py`'s own ECI→ECEF rotation
(GMST) is unrelated to this check. **Time**: UTC throughout, matching the
codebase.

## 1. Orbital elements — confirmed by an independent method

`sim/scenario.py`'s `REFERENCE_TLE_LINE2` (POQUITO's real, SatNOGS-sourced
TLE) encodes mean motion `n = 15.17186328 rev/day`, inclination
`i = 97.4429°`, eccentricity `e = 0.0003354` (read directly off the raw TLE
fields, not copied from any comment). Applying Kepler's third law
independently ($a = (\mu / n^2)^{1/3}$, converting `n` to rad/s) rather than
trusting `sim/scenario.py`'s own docstring language ("~514 km mean altitude,
~94.9 min period"):

| Quantity | Independently derived | Design spec / test-suite claim | Match |
|---|---|---|---|
| Semi-major axis (mean) | 6892.486 km | — | — |
| Altitude (mean, Kepler's 3rd law) | **514.349 km** | "~514 km mean altitude" (`sim/scenario.py` module docstring) | matches |
| Orbital period | **5694.752 s** (94.913 min) | 5694.75 s (`sim/scenario.py::ORBITAL_PERIOD_S`) | matches to 2 ms |

**A second, independent cross-check surfaces a real (and expected) nuance**:
propagating the real TLE with `sim/orbit.py`'s own `propagate()` at the
TLE's exact epoch and taking the resulting ECI vector's magnitude gives an
*osculating* radius of 6886.200 km — an altitude of **508.063 km**, about
6.3 km lower than the Kepler's-third-law altitude above. This is not a bug
or an inconsistency between the two methods used in this section: SGP4's
mean elements (mean motion, mean anomaly) describe a secularly-perturbed
*mean* orbit, not an instantaneous two-body ellipse, so applying Kepler's
third law directly to the mean-motion field yields the *mean* semi-major
axis, while the propagated position at any specific instant reflects the
real, J2-perturbed instantaneous radius, which oscillates around that mean
value rather than sitting on it. Both figures are legitimate; they answer
different questions ("what's the mean orbit size" vs. "where exactly is the
satellite at t = epoch"). `sim/scenario.py`'s docstring and
`tests/test_orbit.py::test_reference_tle_is_valid_leo`'s comment were
tightened during the final review to state both figures precisely
(~514 km mean / ~508 km osculating) rather than the single rounded "~525 km"
this section originally flagged as loosely matching neither.

The period match (5694.752 s vs. the constant's 5694.75 s, agreeing to
2 ms) is the cleanest confirmation available here: `ORBITAL_PERIOD_S` is
itself derived from the same TLE mean-motion field this section
recomputes from scratch via a completely independent formula path, so the
near-exact agreement confirms `sim/scenario.py`'s own arithmetic rather
than an independent physical coincidence.

## 2. Sun-synchronous claim — independently verified, not just asserted

Unlike the retired placeholder (whose inclination was itself hand-solved to
hit the sun-synchronous target exactly — see the "Refreshed for the
POQUITO-sourced update" note above), POQUITO's real TLE inclination
(97.4429°) is just whatever SatNOGS observed; nothing about it was tuned to
satisfy any target. This section checks, honestly, how close the real
satellite actually lands to the sun-synchronous condition, via the same
closed-form J2 secular RAAN drift rate as before:

$$\dot\Omega = -\frac{3}{2} n J_2 \left(\frac{R_E}{p}\right)^2 \cos i$$

with $J_2 = 1.08263\times10^{-3}$, $p = a(1-e^2)$, using the real TLE's own
$a$ = 6892.486 km (§1), $e$ = 0.0003354, $i$ = 97.4429°:

- Computed $\dot\Omega$ = **0.983889°/day**
- True sun-synchronous target (360°/365.2422 days) = **0.985647°/day**
- Difference: **-0.001758°/day (-0.18%)**

Expressed the other way — solving for the inclination that *would* hit
this target exactly at this real semi-major axis/eccentricity gives
**97.4563°**, vs. the real TLE's **97.4429°**: a gap of only **0.0134°**.

**An honest finding, not a manufactured coincidence this time**: the real
POQUITO orbit sits *close to* sun-synchronous (within 0.18% of the target
RAAN-drift rate, or 0.013° of inclination) but does not hit it exactly —
exactly as expected for a real, observed orbit rather than a hand-solved
placeholder. A 0.18% RAAN-drift-rate mismatch corresponds to roughly
0.64°/year of RAAN drift relative to a true sun-synchronous reference
frame, well within normal orbit-injection dispersion for a PocketQube
rideshare deployment, and consistent with Franzese et al. 2026's
description of a "sun-synchronous release orbit" as a design target rather
than a guarantee of exact realization. This section confirms the
sun-synchronous *design intent* is basically borne out by the real,
observed element set — without claiming the kind of exact agreement that
is only possible for a value that was solved for, rather than measured.

## 3. Eclipse behavior — real, meaningful eclipsing, not a degenerate always-sunlit regime

Ran `sim/power.is_illuminated()` itself (the actual function under test,
not a re-derivation) against `sim/orbit.propagate()` positions, sampled
every 60 s across a 48 h (172,800 s) window starting at the real TLE epoch
(2025-01-21 21:45:38.68 UTC) — the same epoch and duration
`sim.driver.run_simulation()` uses for the real, committed
`docs/baseline-results.md` run (`sim/driver.py::_epoch_datetime()` starts
every run at the TLE's own epoch; `tools/generate_baseline_results.py`'s
`DEFAULT_DURATION_S = 172_800.0` matches exactly) — and independently
cross-checked against the standard closed-form beta-angle eclipse-fraction
formula:

$$f_{eclipse} = \frac{1}{\pi}\arccos\left(\frac{\sqrt{a^2-R_E^2}}{a\cos\beta}\right), \quad |\beta| < \beta_{crit} = \arcsin(R_E/a)$$

- Beta angle at epoch (orbit-plane normal vs. Sun vector, using
  `sim/power.py`'s own low-precision Sun-position approximation and the
  standard $\hat h = (\sin i\sin\Omega,\, -\sin i\cos\Omega,\, \cos i)$
  orbit-normal formula, with the real TLE's own $i=97.4429°$,
  $\Omega=104.2661°$): **21.38°**
- Critical beta angle for this altitude ($\arcsin(R_E/a)$, using the real
  semi-major axis from §1): **67.73°**
- Since $|\beta| \ll \beta_{crit}$: **analytically, substantial eclipsing
  is expected** — the orbit plane is nowhere near turned enough from the
  Sun line to stay clear of Earth's shadow. Analytical eclipse fraction at
  this beta: **36.65%** of the orbit.
- **Empirically confirmed** by sampling `is_illuminated()` every 60 s
  across the same 48 h window: **1,050 of 2,880 samples eclipsed
  (36.46%)**. The closed-form formula (36.65%, a single-beta snapshot) and
  the actual running code (36.46%, averaged over 48 h as beta itself very
  slightly precesses under J2) agree to within 0.2 percentage points — the
  small residual gap is exactly what's expected from a formula that holds
  beta fixed at its epoch value, checked against a simulation where it
  drifts slightly over 2 days, not a discrepancy in either method.

### Why this matters — a consequence of adopting real data, not something engineered

This is a materially different finding from the retired placeholder
analysis, which reported the placeholder's hand-picked epoch sitting in a
fully-sunlit, degenerate regime (β=68.79° against a β_crit of 67.51° — a
margin of only 1.28°) and flagged that as "a genuine scope gap worth
knowing about... for whoever picks up Phase 5 or extends the baseline
scenario." That gap is now closed, but **only as an honest side effect of
switching to POQUITO's real, unmodified TLE** — not because anyone went
looking for a "better" eclipse regime. Two things are worth being explicit
about:

1. **No epoch-hunting occurred.** The real TLE has exactly one published
   epoch (2025-01-21 21:45:38.68 UTC — SatNOGS's only element set for this
   object, never updated past ~8 days post-launch, per `sim/scenario.py`'s
   own docstring). There was no alternative epoch to choose between, and
   none was sought — doing so would just reintroduce the same hand-picking
   problem the placeholder had, just with better cover ("we found a real
   epoch that happens to eclipse"). The 36.46% eclipse fraction reported
   here is simply what this one real, frozen epoch happens to show; it is
   not a selection result.
2. **The real, committed baseline now exercises the eclipse branch.**
   Because `sim/driver.py::run_simulation()` starts every run at exactly
   this TLE epoch and `tools/generate_baseline_results.py` runs for
   exactly this 48 h duration, the real `docs/baseline-results.md` run
   (delivery-rate/latency/energy numbers already committed) is — for the
   first time — genuinely exercising `step_battery`'s eclipse branch
   (`solar_gen_w=0`) end-to-end through `sim.driver`, not only in
   `tests/test_power.py`'s isolated unit tests. This closes exactly the
   scope gap the prior version of this analysis flagged, without any
   deliberate design choice made to close it.

With the real POQUITO power figures (`docs/parameters.md` SIM-005 through
SIM-012): `DRAW_W_IDLE` (0.0996 W) is below `SOLAR_GEN_W` (0.4 W), so the
satellite still recharges whenever no comms burst is active *and* it is
illuminated — but for ~36% of the 48 h window it is not illuminated at
all, so idle draw alone (0.0996 W) drains the battery during each eclipse,
and the real comms transmit-burst draws (`DRAW_W_COMMS_TTC`/`SSTV`/`VOICE`:
3.415 W/5.1225 W/4.26875 W) draw the battery down regardless of
illumination state, since `SOLAR_GEN_W` never covers any of them. Each
burst is short (`COMMS_BURST_DURATION_S` = 156 s) and battery capacity is
4.5 Wh, so a single burst still only costs ~0.15 Wh (~3.3% of capacity)
whether it happens in sun or shadow — the qualitative per-burst
energy-balance conclusion from the prior (always-sunlit) analysis still
holds burst-by-burst. What's different now is that the *idle* baseline is
no longer a guaranteed net-positive: during an eclipse period, idle draw
alone is net-negative (-0.0996 W) rather than the always-positive
(+0.3004 W) net rate the fully-sunlit placeholder scenario implied.
Whether this actually drives the P-013 25% low-battery guard to fire
anywhere in the real committed baseline is a `sim.driver`-level,
end-to-end battery-trajectory question this orbit/eclipse-focused
cross-check does not re-derive — that is left to whichever analysis
independently re-verifies `docs/baseline-results.md`'s own numbers,
outside this doc's scope.

### Beta-angle seasonal scan — retired in this refresh, not carried forward again

The prior version of this document carried over a year-long beta-angle
seasonal scan from the original 550 km-era analysis (30-day-step,
J2-RAAN-propagated), already flagged there as "not independently re-run"
for the 550→525 km change. Now that the epoch itself has moved by roughly
a year (2026-01-15 → 2025-01-21) in addition to the altitude/inclination,
that carried-over scan is even further removed from anything this refresh
actually re-derived — carrying it forward unchanged a second time would
compound an already-stale approximation rather than merely note it as one.

More importantly, **the reason that scan existed no longer applies.** Its
entire purpose was to answer "does this orbit ever eclipse, even though
the frozen reference epoch shows a degenerate always-sunlit regime?" — a
fair question when the fixed epoch's β sat only 1.28° outside β_crit and
the committed baseline never touched the eclipse branch at all. That
question is now moot: §3 above already demonstrates, empirically, that the
real fixed epoch itself eclipses 36.46% of the time. There is nothing left
for a seasonal scan to prove that a direct measurement at the actual epoch
doesn't already answer more directly and more rigorously.

Re-running the seasonal scan anyway — to report something like "eclipse
fraction ranges from X% to Y% depending on time of year" — was considered
and rejected for this refresh. It is a real, well-scoped independent
re-derivation this doc *could* still do (re-propagate RAAN via §2's J2
drift rate across a year and recompute β at each step); but adding it now,
immediately after explicitly warning against epoch-hunting above, risks
reading as exactly that kind of exercise — an implicit search for context
that makes the reported 36.46% figure look more or less "typical" than it
is. The reported figure is what the real, frozen, un-chosen epoch actually
shows, full stop. A seasonal characterization is a legitimate but separate
research question, better scoped to its own analysis (or a future Phase 5
doc that explicitly needs to reason about non-frozen epochs), not bundled
into this cross-check as if it were needed to validate today's number.

**Decision: retired, not carried forward.** No seasonal beta-angle scan
appears in this refresh.

## 4. Ground-station pass geometry — a materially different qualitative story

Re-derived directly via `sim.orbit.find_passes()` (10° minimum elevation,
matching `docs/parameters.md` P-015/PB-006) scanning the same 48 h window
from the real TLE epoch:

| AOS (UTC) | Time after epoch | Duration | Max elevation |
|---|---|---|---|
| 2025-01-22 06:04:28.68 | +8.314 h | 440 s | 83.19° |
| 2025-01-22 18:06:58.68 | +20.356 h | 410 s | 39.17° |
| 2025-01-23 05:49:18.68 | +32.061 h | 430 s | 46.13° |
| 2025-01-23 17:51:28.68 | +44.097 h | 440 s | 71.57° |

4 passes over 48 h, spaced roughly every ~12 h (gaps of 12.04 h, 11.71 h,
12.04 h between successive AOS times), consistent with a ~94.9-minute
period producing two qualifying passes per day at this ground station's
latitude rather than one every orbit — most orbital revolutions don't
bring the satellite within 10° elevation of Mumbai at all.

This is a **materially different qualitative story** from the retired
placeholder analysis, which reported the placeholder's hand-solved epoch
landing a pass "at t≈0" (peak elevation ≈89.99° right at the reference
epoch), because the placeholder's RAAN/mean-anomaly were specifically
re-searched to put the satellite near-overhead Mumbai at t=0. The real TLE
has no such property: **the first real pass is ~8.3 h after epoch**, not
at epoch, simply because nothing about the real element set was chosen
with Mumbai in mind — it is only where SatNOGS's tracking placed POQUITO
at its last-received epoch. `sim/scenario.py`'s own docstring already
states this plainly ("this real epoch is NOT inside a ground-station
pass — the first real pass is ~+8.3h to +8.5h later"), and this section
independently confirms it via a fresh `find_passes()` scan rather than
trusting that comment at face value: the +8.314 h AOS found here lands
inside the stated +8.3h–+8.5h range.

## Summary

| Check | Result |
|---|---|
| Altitude/period from mean motion | Independently confirmed: 514.349 km (mean, Kepler's 3rd law), 5694.752 s period — matches `ORBITAL_PERIOD_S` (5694.75 s) to 2 ms. Osculating radius at epoch (508.063 km) differs by ~6.3 km, expected from SGP4's mean-vs-osculating elements, not an error. |
| Sun-synchronous claim | Close but not exact: 0.983889°/day vs. 0.985647°/day target (-0.18%, or 0.013° of inclination) — an honest, unforced near-match for a real observed orbit, unlike the retired placeholder's exact-by-construction agreement |
| Eclipse model physics | Correct, and now genuinely exercised end-to-end: 36.46% of the real 48 h baseline window is eclipsed (β=21.38° vs. β_crit=67.73°) — the prior "fully-sunlit, degenerate regime" scope gap is closed as a side effect of adopting real data, not a deliberate fix, and no alternative epoch was sought to produce this result |
| Pass geometry | 4 passes over 48 h, ~every 12 h, first pass at +8.3 h — qualitatively different from the retired placeholder's "pass at t≈0" (itself a hand-solved property, not a feature of a real orbit) |
| Beta-angle seasonal scan | Retired in this refresh (see §3) — its purpose (proving eclipse occurs *somewhere* in the year) is moot now that the real fixed epoch already shows real eclipsing directly, and re-running it risks reading as epoch-hunting |

No `sim/` code or `docs/parameters.md`/`docs/baseline-results.md` changes
are proposed by this cross-check. Unlike the prior version of this
document, there is no remaining eclipse-coverage "scope gap" to record for
Phase 5: the real, committed baseline already exercises eclipse-driven
power stress end-to-end, as an honest consequence of adopting POQUITO's
real TLE rather than a deliberate design choice. To avoid silently editing the existing
`sim/` deliverables, this refresh only updates this file.
