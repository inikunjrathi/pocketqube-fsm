# Decision Record 0005 — Real POQUITO TLE Adoption

**Date:** 2026-07-27

## What was done

Replaced `sim/scenario.py`'s `REFERENCE_TLE_LINE1` and `REFERENCE_TLE_LINE2` from a
synthetic placeholder TLE to POQUITO's real, SatNOGS-published TLE (NORAD temporary
catalog number 98706 / international designator 25009BY) at its real epoch
(2025-01-21 21:45:38.68 UTC, not "today"). The old placeholder's RAAN and
mean anomaly had been hand-solved to land the satellite near-overhead
Mumbai at epoch (its inclination was separately hand-solved to hit the
sun-synchronous condition exactly — see the framing in
`docs/analysis/mission-analysis-specialist/orbit-and-eclipse-crosscheck.md`);
the new TLE is transcribed verbatim from SatNOGS's only
published element set for this object, with no re-tuning of any field.

## Why

A real, actually-observed post-launch element set is more authentic than a
synthetic, hand-picked-for-convenience approximation. This change is consistent
with the project's existing "no live-fetch, frozen reference scenario"
philosophy — a principle explicitly stated in `sim/scenario.py`'s module
docstring and grounded in a design precedent from `sim/orbit.py`:

> No live earth-orientation data, no extra geodesy dependency beyond sgp4
> itself, matching the design spec's Global Constraints. (`sim/orbit.py`,
> module docstring, lines 12-14)

The same reasoning applies here: freezing the simulation at the TLE's own real
epoch (2025-01-21 UTC) rather than trying to propagate to "today" (18 months
later) follows the same principle. SGP4 accuracy degrades sharply beyond a few
weeks from its element set's epoch, especially for a decaying, low mass-to-area
PocketQube like POQUITO — an 18-month-ahead propagation would be *less*
physically meaningful than staying at the real epoch this element set actually
describes. This project's reference scenario has never claimed to represent
"today," only "real and self-consistent," so the epoch-frozen approach used
since the original Week 8-9 design continues unchanged, now anchored to a real
rather than a synthetic element set.

## The eclipse/beta-angle open question — addressed explicitly, not silently

The retired placeholder TLE sat in a fully-sunlit, degenerate regime (β ≈ 68.79°
against β_crit ≈ 67.51°, margin of only 1.28°), and that analysis flagged a
"genuine scope gap worth knowing about for whoever picks up Phase 5 or extends
the baseline scenario." With the real POQUITO TLE, this finding changes:

- **Beta angle at epoch:** 21.38°
- **Critical beta angle for this altitude:** 67.73°
- **Eclipse fraction over the real 48 h baseline window:** 36.46% (1,050 of 2,880
  samples)

This is now what POQUITO's real orbit actually does at its real epoch — an
honest fact, not a bug. It happens to close the previously-flagged "committed
baseline never exercises eclipse-driven power stress" scope gap as a *side
effect* of adopting real data, not as an engineered fix. Two things must be
stated explicitly:

1. **No epoch-hunting occurred.** POQUITO's real TLE has exactly one published
   epoch on SatNOGS — the only element set ever received for this object. There
   was no alternative epoch to choose between, and none was sought. Doing so
   would just reintroduce the same "hand-picked for convenience" problem the
   placeholder had, only with better cover ("we found a real epoch that happens
   to eclipse").

2. **No alternative epoch was substituted to chase a "better" regime.** The
   36.46% eclipse fraction reported here is what this one real, frozen epoch
   simply happens to show — a selection result would violate the project's own
   stated commitment to a fixed, not hand-optimized, reference scenario.

Details are independently verified in `docs/analysis/mission-analysis-specialist/
orbit-and-eclipse-crosscheck.md`, which was refreshed specifically for this
change (see its "Refreshed again for the real-TLE adoption" introduction).

## Considered and rejected

Two research directions surfaced during this work and were deliberately not
pursued. Recording them here prevents this research from being silently lost:

1. **CelesTrak's EOP/space-weather CSVs** (data/EOP-All.csv, EOP-Last5Years.csv,
   SW-All.csv, SW-Last5Years.csv, currently untracked in the repo): These provide
   high-precision polar-motion and atmospheric-density corrections for advanced
   propagators. This project uses plain SGP4 with its self-contained B* term for
   10°-elevation-mask scheduling, where the arcsecond-level precision EOP targets
   exceeds the simulator's needs. Not incorporated.

2. **github.com/AMSAT-EA/easat2-tle-lottery**: This mission-specific TLE-
   disambiguation technique was developed for DELFI-PQ/EASAT-2/HADES using Doppler-
   fitting methods. POQUITO's SatNOGS entry is a single, unambiguous match requiring
   no disambiguation, making this fallback technique inapplicable. Not used.

## Consequences

No simulation *engine* code was modified — the only production change is the
TLE constants in `sim/scenario.py`. Test code, however, did require real
changes: several fixtures had been anchored to a property of the placeholder
orbit that the real orbit simply does not have ("the satellite is
near-overhead Mumbai at t=0"). The real epoch is not inside a pass at all, so
every fixture that relied on that had to be re-anchored to the real orbit's
actual pass geometry. Six test files changed across Tasks 1 and 2
(`test_orbit.py`, `test_driver.py`, `test_oracle.py`, `test_dataset.py`,
`test_three_policies_integration.py`,
`test_generate_policy_comparison.py`); the suite now stands at 655 tests, all
passing.

- **Task 1/2 impact:** The re-anchoring covered (a) pass-geometry tests such as
  `test_elevation_at_subsatellite_point_is_near_90`, now scanning the real
  +8.3h–+8.5h first-pass window instead of ±5 min of the old placeholder
  epoch (and renamed accordingly where the old name asserted the
  overhead-at-epoch property); (b) fixed-arrival and short-run durations,
  which now have to reach the first real pass (~29930 s) before any
  comms-mode behavior appears; (c) `test_reference_tle_is_valid_leo`'s radius
  band, loosened from 6900–7000 km to 6800–7000 km to admit the real orbit's
  ~6886 km epoch radius; and (d) a hardcoded expected delivery count, which
  the TLE adoption moved from 160 → 279 (the later beacon-cadence change in
  Task 5 moved it again, 279 → 591 — a separate, non-TLE re-derivation noted
  here only for continuity). These are fixture re-anchorings, not behavioral
  relaxations — no assertion was weakened to hide a real-orbit consequence.

- **Task 4 impact:** `docs/analysis/mission-analysis-specialist/
  orbit-and-eclipse-crosscheck.md` was refreshed for this change, with every
  section (§1-§4) independently recomputed against the real TLE. That document
  is already committed and contains the authoritative eclipse/beta-angle numbers
  cited above.

- **Task 5 downstream:** arrival *generation* is unaffected by this change —
  `sim/data_arrival.py`'s `generate_arrivals()` is a pure function of
  `(priority_order, duration_s, seed)` and never consults the orbit, so the
  same item stream is produced before and after. What the new pass geometry
  (4 passes over 48 h, first at +8.3 h, instead of the placeholder's
  overhead-at-t=0 arrangement) changes is *delivery*: which of those items get
  downlinked, when, and hence the delivery-success and TT&C-latency figures in
  the baseline. This is a data consequence, not a code defect — tracked
  separately in Task 5's scope.
