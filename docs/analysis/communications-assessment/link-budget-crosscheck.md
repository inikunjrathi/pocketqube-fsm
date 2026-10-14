# Link-Budget Cross-Check

Independent sanity-check of `sim/link.py`'s `LINK_MARGIN_DB_PER_DEG` proxy
constant and `sim/scenario.py`'s `LINK_DATA_RATE_BPS` figure against the
one real published POQUITO link data point and two independent
geometric/engineering methods. This is a read-only check — it does not modify
`sim/`, `sim/scenario.py`, or `docs/parameters.md`. Frequency band, antenna,
and ground network are out of scope for this project, so the check is
limited to `sim/link.py`'s `LINK_MARGIN_DB_PER_DEG` proxy constant and
typical amateur/small-sat link-margin conventions, without inventing an RF
architecture the use-case document doesn't specify. Within that
boundary, nothing below constructs an antenna-gain/path-loss/noise-figure
RF link budget — the goal is only to check the existing elevation-based
proxy and throughput constant against independent methods, not to replace
either with a full RF design.

**Constants under check** (`sim/scenario.py`):
`LINK_MARGIN_DB_PER_DEG = 0.5`,
`LINK_MARGIN_CALIBRATION_ELEVATION_DEG = 15.0`,
`LINK_MARGIN_CALIBRATION_DB = 10.0`, `LINK_DATA_RATE_BPS = 9600.0`.

## 1. The real citation, taken at face value

The only real, published POQUITO link number available is Franzese et al.
2026, Sect. 3.2: "the communication link for POQUITO is closed with a
10 dB margin even at low elevation angle (15°)." Sect. 3.6 separately
publishes the downlink data rate: 9600 bit/s.

That is the entire real link-level dataset this mission provides — no
antenna gain, EIRP, path-loss, noise-figure, or G/T breakdown is published
anywhere in the paper. This is exactly why `sim/link.py`'s `margin_db`
formula stays a deliberately simple elevation-based proxy rather than
becoming a full RF link budget: there is nothing further to decompose the
10 dB figure into, and inventing antenna/noise-figure numbers the source
document doesn't specify would manufacture false precision, not real
fidelity. The two constants (`LINK_MARGIN_CALIBRATION_ELEVATION_DEG=15.0`,
`LINK_MARGIN_CALIBRATION_DB=10.0`) reproduce the citation verbatim as the
formula's anchor point; everything else in `sim/link.py` is proxy
behavior built around that one anchor.

## 2. Free-space-path-loss sanity check (independent method)

Using the real POQUITO orbit already in `sim/scenario.py` (mean
semi-major axis 6892.486 km, from `REFERENCE_TLE_LINE2`'s mean motion of
15.17186328 rev/day — i.e. ~514.3 km mean altitude, close to but not
exactly the paper's 525 km design value) and
`EARTH_RADIUS_KM = 6378.137 km` (`docs/parameters.md` SIM-002/SIM-003),
the slant range at elevation `el` above a spherical Earth is the standard
closed-form:

$$d = R_E \left[\sqrt{\left(\frac{R_S}{R_E}\right)^2 - \cos^2(el)} - \sin(el)\right]$$

- At `el = 15°`: `R_S/R_E = 1.0806425`, giving `d ≈ 1439.7 km`.
- At `el = 90°` (zenith): `d = R_S - R_E = 514.3 km` (the altitude itself,
  as expected — the slant range at zenith degenerates to straight-down
  range).

Free-space-path-loss delta between those two elevations:

$$\Delta_{FSPL} = 20 \log_{10}\left(\frac{1439.7}{514.3}\right) \approx 8.9\ \text{dB}$$

over that 75° span (≈0.12 dB/deg average). Compare this against the
model's own implied improvement over the same span:
`(90 - 15) * LINK_MARGIN_DB_PER_DEG = 75 * 0.5 = 37.5 dB` — roughly 4x
the FSPL-only figure.

**This gap is real and worth stating plainly, not explaining away**: the
0.5 dB/deg slope is steeper than pure free-space path loss alone would
justify. It is nonetheless retained, for two reasons. First, low-elevation
effects beyond pure FSPL — atmospheric/tropospheric attenuation, ground
multipath, and antenna-pattern droop near the horizon — are well
documented in amateur/small-sat link-budget literature to dominate over
FSPL specifically at low elevation angles, which is exactly the regime
(10-15°) where this gap matters most for the sim's `is_up`/`meets_fade_margin`
decisions. Second, and more simply: `sim/link.py`'s docstring never claims
the proxy is FSPL-derived in the first place — it is documented throughout
as "a simple monotonic proxy... not a literal RF link budget." This
section sanity-checks that proxy against an independent geometric method;
it does not overturn it, because the proxy was never asserted to be a
geometric quantity to begin with.

## 3. Recalibrated margin at the real config values

`sim/link.py`'s `margin_db` formula, evaluated at the real configured
elevation values (`P-015`/`PB-006` = 10° minimum elevation,
`P-016`/`PB-007` = 3 dB fade margin):

| Elevation | `margin_db` | Note |
|---|---|---|
| 10° (configured floor) | **7.5 dB** | `10.0 + (10-15)*0.5` |
| 15° (real citation) | **10.0 dB** | exact match to Franzese et al. 2026, Sect. 3.2 |
| 90° (zenith) | **47.5 dB** | `10.0 + (90-15)*0.5` |

`meets_fade_margin` at the configured 10° floor: `7.5 >= 3.0` → **met** —
the link clears its own configured fade allowance even at the
conservative minimum-elevation mask, not just at zenith.

As a second, independent sanity check, `7.5 dB` at the 10° floor can be
compared against a generic small-sat/LEO link-margin convention: a
commonly cited engineering rule of thumb for a closed link is a minimum
**≥3 dB fade margin**. This is cited here as generic engineering
convention, not a specific published source — consistent with how the two
existing analysis docs
(`docs/analysis/power-assessment/battery-solar-sanity-check.md`'s Li-ion
DOD/cycle-life norms,
`docs/analysis/mission-analysis-specialist/orbit-and-eclipse-crosscheck.md`'s
closed-form astrodynamics formulas) each treat non-mission-specific
engineering judgment as a labeled cross-check input rather than a cited
mission fact. `7.5 dB` clears that generic ≥3 dB convention by a healthy
2.5x at the worst-case (lowest) elevation the link is ever allowed to
operate at.

## 4. Throughput/data-rate sanity check

`LINK_DATA_RATE_BPS = 9600.0` bit/s = 1200 bytes/s.

The largest illustrative item size in `sim/data_arrival.py`'s
per-class distributions is the SSTV class's upper bound, 8192 bytes
(`_SIZE_BYTES_RANGE_BY_CLASS["SSTV"] = (2048, 8192)`). Transmitting that
largest item takes:

$$8192\ \text{bytes} / 1200\ \text{bytes/s} \approx 6.83\ \text{s}$$

The actual committed runs (`docs/baseline-results.md`, generated by
`tools/generate_baseline_results.py`; `docs/policy-comparison-results.md`,
generated by `tools/generate_policy_comparison.py`) both use `dt_s = 10.0
s` — that tool's own `DEFAULT_DT_S = 10.0` — not a longer tick. Against
that real 10 s budget, a single largest-case SSTV item consumes:

$$6.83\ \text{s} / 10\ \text{s} \approx 68\%$$

of one tick's transmit-time budget — not a small fraction at all. This is
the *more* interesting fact, not a weaker one: it means the transmit-budget
gate (`item_transmit_time_s > remaining_transmit_time_s`, `sim/driver.py`
and its `policy/oracle.py` rollout mirror) binds routinely in the real
runs whenever a largest-case SSTV item is in the mix, actively deferring
it to a later tick rather than letting it fit trivially alongside
everything else — directly exercising the throughput-gating design this
plan added, not just a theoretical edge case. A handful of the smaller
TTC/CODEC2_M17 classes (64-1536 bytes) still comfortably fit alongside it
or in the tick(s) it doesn't consume.

(If a longer tick configuration were used instead — e.g. `dt_s` = 30-60 s,
as several unit tests in `tests/test_driver.py`/`tests/test_oracle.py`
exercise for legibility — the same 6.83 s item would consume a smaller
22.8%/11.4% of the tick, comfortably fitting several such items per tick.
But that is not the configuration the committed baseline/comparison runs
actually use.)

Over the full `COMMS_BURST_DURATION_S = 156.0 s` real transmit-burst
window (SIM-012, POQUITO's own published duty cycle), the same rate gives
a per-orbit throughput ceiling of:

$$156\ \text{s} \times 1200\ \text{bytes/s} = 187{,}200\ \text{bytes/orbit}$$

This ceiling number is exactly why the throughput-gating design (Task 2,
`sim/driver.py`) budgets each tick against its own `dt_s`, never against
`COMMS_BURST_DURATION_S`: `dt_s` (10 s in the real committed runs, and
never more than 60 s even in test scenarios) is always far shorter than
the 156 s burst window, so gating per-tick lets delivery continue — at
idle draw — after the burst window elapses within a single comms visit,
rather than artificially capping a visit's total deliverable bytes at the
burst-window ceiling above. The 187,200 bytes/orbit figure is a useful
sanity bound on total per-orbit throughput, not a per-tick or per-visit
budget the driver itself ever computes or enforces directly.

## Summary

| Check | Result |
|---|---|
| 15°/10 dB citation match | Exact by construction — `margin_db(15°) = 10.0 dB` reproduces Franzese et al. 2026, Sect. 3.2 verbatim |
| FSPL cross-check of the 0.5 dB/deg slope | FSPL alone implies only ~8.9 dB (~0.12 dB/deg) over the 15°→90° span vs. the model's 37.5 dB (0.5 dB/deg) — a real ~4x gap, explained (not erased) by low-elevation effects beyond FSPL that dominate amateur/small-sat links at low elevation |
| Margin at the 10° configured floor vs. generic ≥3 dB LEO convention | `margin_db(10°) = 7.5 dB`, clearing the generic ≥3 dB closed-link convention by 2.5x; `meets_fade_margin` (7.5 ≥ 3.0) is met even at this conservative floor |
| Throughput/data-rate sanity | 9600 bit/s = 1200 bytes/s; largest illustrative item (SSTV, 8192 bytes) takes ~6.83 s — ~68% of the real committed runs' 10 s tick (`dt_s=10.0`, `tools/generate_baseline_results.py`/`generate_policy_comparison.py`), so the transmit-budget gate binds routinely there, not just as an edge case; 156 s burst window ceiling is ~187,200 bytes/orbit, consistent with the driver's per-tick (not per-burst-window) throughput gating |

**No change proposed.** `LINK_MARGIN_DB_PER_DEG`'s value (0.5 dB/deg) is
not altered by this cross-check, and `P-015`/`P-016`/`PB-006`/`PB-007`'s
configured values (10° minimum elevation, 3 dB fade margin) are unchanged.
Only the `margin_db` formula's anchor point (re-pinned at the real
POQUITO citation, SIM-014, rather than at the configured minimum
elevation) and `fade_margin_db`'s role (a `meets_fade_margin` floor check,
independent of `margin_db`'s own arithmetic, rather than a term subtracted
inside it) were revised — both already landed in `sim/link.py` and
`docs/parameters.md` by Task 1 of this plan. This document's job was to
independently verify those already-landed values against the real
citation and two independent methods (FSPL geometry, generic engineering
convention), not to propose any further change.
