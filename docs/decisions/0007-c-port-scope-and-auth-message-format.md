# Decision Record 0007 — C-Port Auth Message-Format Scope

**Date:** 2026-08-04 (Phase 8, Task 5 — `engine/auth.py` port)

## What was done

Pre-work decision for `mcu/firmware/app/src/engine_auth.c`'s real HMAC-SHA256
implementation (Phase 8, Task 5
Step 1), made and recorded here **before** writing the golden-vector test
that checks the C implementation against `engine.auth.sign_command()`'s real
output, per that plan step's explicit instruction.

## The problem

`engine/auth.py::sign_command()` (never modified — it is this port's
ground-truth oracle, per the plan's Global Constraints) signs the exact byte
string `f"{event_id}:{now}".encode("utf-8")`, where `now` is a Python
`float`. Python's `str(float)`/f-string formatting of a float is a
shortest-round-trip decimal representation (effectively the historical
David Gay / more recent Ryu-family dtoa algorithm CPython ships), which is
materially more than "print the digits": `now=100` (an `int` widened to
`float` at the call site, or a literal `100.0`) serializes as `"100.0"`, not
`"100"`. Reproducing that general algorithm byte-for-byte in C, for
*arbitrary* floats, is a nontrivial undertaking (correct rounding, shortest
representation, the switch to scientific notation past a magnitude
threshold, `-0.0` handling, etc.) that is disproportionate to what this
system actually needs.

## Investigation: is `now` ever genuinely fractional in this codebase?

Checked every real caller of `now` before deciding, per the plan's own
instruction not to guess:

- `sim/driver.py`'s tick loop computes `t = i * dt_s` (`run_simulation`,
  `~line 297`) — `i` is always a Python `int` loop counter, and every
  `dt_s` value actually passed anywhere in this repository is itself a
  whole number of seconds: `10.0` (`tools/generate_baseline_results.py`'s
  `DEFAULT_DT_S`, `policy/dataset.py`'s `DATASET_DT_S`,
  `tools/generate_policy_comparison.py`'s/`tools/generate_worst_case_scenarios.py`'s
  `DEFAULT_DT_S`), `60.0` (every `dt_s=` call site in
  `tests/test_generate_baseline_results.py`,
  `tests/test_generate_worst_case_scenarios.py`,
  `tests/test_generate_ground_station_analysis.py`), or `3600.0`
  (`sim/driver.py`'s own `_BOOTSTRAP_STEP_S`, used for `now = len(path) *
  _BOOTSTRAP_STEP_S` in the transition-path search). `i * dt_s` for an
  integer `i` and an integral `dt_s` is always itself an exactly
  representable integral `float` — there is no accumulated floating-point
  drift here since both factors are small whole numbers well within
  `float64`'s exact-integer range.
- `sim/driver.py::_try_fire()` itself (`~line 638`) is the only call site of
  `sign_command()`/`verify_command()` in the whole codebase
  (`grep -rn "sign_command\|verify_command" sim/ engine/ tests/ tools/`
  confirms this) — it receives whatever `now` its own caller threads
  through, which is always one of the tick-loop or bootstrap values above.
- `tests/fixtures/transition_cases.py`'s `TransitionFixture.now` field is a
  hand-authored `int` literal in every one of its ~150 entries (`grep -n
  "TransitionFixture(" tests/fixtures/transition_cases.py` — every third
  positional field is a bare integer like `0`, `900`, `1800`; a search for
  any fixture containing a decimal point in this field found none).
- `mcu/firmware/app/src/main.c`'s own `format_double()` (Task 4, written
  independently for the `DECISION <now> ...` UART reply field) already
  special-cases exact integers to print without a trailing `.0` — an
  independent piece of evidence that every `now` value this system's wire
  protocol has ever needed to carry in practice is a whole number of
  seconds; Task 4 made that call for float-formatting simplicity on the
  embedded target, not for auth purposes, but it corroborates the same
  underlying fact about the domain.

Conclusion: in every real and test call site in this repository, `now` is a
whole number of seconds (a `float` that exactly equals its own truncation),
by construction of how simulated time advances (`i * dt_s` with both
integral) — never a genuinely fractional value like `100.5`.

## Decision

**Standardize the C-side signed/verified message construction on the
"integer-valued float" special case of Python's `str(float)`, not the
general shortest-round-trip algorithm — and restrict this port's supported
domain for `now` to whole-second, non-negative values under `1e16` in
magnitude.**

Checked directly (`str(float(v))` for representative values, see the
Task 5 verification transcript below): for any `float` that is exactly
integral and whose magnitude is `< 1e16`, CPython's `str()`/f-string
formatting is *always* exactly `"<decimal digits of the integer
part>.0"` (with a leading `-` for negative values) — it never switches to
scientific notation, never emits extra trailing digits, and never differs
from what a straightforward `sprintf("%lld.0", (long long)now)`-style
routine produces. (`1e16` and above switches to `"1e+16"`-style scientific
notation; PocketQube mission timescales — elapsed seconds over a
multi-year mission — are on the order of `1e8`, nine orders of magnitude
below that threshold, so this ceiling is not a practical constraint.)

This means the C implementation does **not** need to replicate the general
Python float-repr algorithm at all. `engine_auth.c`'s message-construction
helper:

1. Requires `now` to be an exact non-negative integer value under `1e15`
   (one order of magnitude of headroom below the `1e16` scientific-notation
   threshold, chosen deliberately as a documented, checked precondition —
   not an assumption): `now == floor(now) && now >= 0.0 && now < 1e15`.
2. Formats the message as `"<event_id>:<now as %lld>.0"` — i.e. the decimal
   digits of `(long long)now`, followed by the literal `".0"` — which is,
   for every value satisfying (1), byte-for-byte identical to what
   `f"{event_id}:{now}"` produces in Python.
3. If `now` fails precondition (1) — genuinely fractional, negative, or
   implausibly large — `engine_auth_verify_command()` fails closed
   (returns `false`, no crash, no attempt at a best-effort format) rather
   than emitting a message that might silently diverge from what Python
   would have signed. This is a documented, deliberate scope boundary, not
   a silent bug: it means this C port intentionally does not support
   ground-command auth over a fractional or out-of-range `now`, because no
   real or test call site in this repository ever produces one (see
   Investigation above) — a future extension of this repository's `now`
   semantics (e.g. sub-second mission timing) would need to revisit this
   decision, not silently rely on it.

## What was deliberately NOT done, and why

1. **Not attempting a general CPython-float-repr port in C.** Disproportionate
   engineering effort (correct-rounding shortest-decimal algorithms like
   Ryu/Grisu3 are their own nontrivial subsystem) for a domain that never
   actually needs it — see Investigation above. If a future change ever
   makes `now` genuinely fractional at a real call site, this decision
   record is the place to revisit, and the golden-vector test (Task 5 Step
   3, generated from the *real* `sign_command()`) would immediately catch
   any resulting mismatch rather than silently drifting, since it is
   re-run against fresh Python-generated vectors, not hand-transcribed
   constants.
2. **Not changing `engine/auth.py`'s message format itself** (e.g. to
   `f"{event_id}:{int(now)}"`, dropping the float suffix entirely). This
   file is explicitly out of scope for modification (Global Constraints:
   "`engine/*.py` ... never modified") and remains the sole correctness
   oracle — this decision is entirely about how the **C side** constructs
   an equivalent message for the domain of `now` values that actually
   occur, not about changing what Python signs.
3. **Not adding a timestamp-freshness window.** Explicitly out of scope per
   `engine/auth.py`'s own module docstring ("There is no separate
   timestamp-freshness window in this model") — unchanged by this decision.

## Verification this decision itself relies on (re-run as part of Task 5's own verification, not asserted blind)

```
$ /home/nik/Desktop/cepdt/.venv/bin/python3 -c "
for v in [0, 1, 100, 900, 3600, 999999999999999, 1e16, -100.0]:
    print(v, '->', repr(float(v)))
"
0 -> 0.0
1 -> 1.0
100 -> 100.0
900 -> 900.0
3600 -> 3600.0
999999999999999 -> 999999999999999.0
1e+16 -> 1e+16          # scientific notation begins exactly at 1e16
-100.0 -> -100.0
```

```
$ grep -rn "sign_command\|verify_command" sim/ engine/ tests/ tools/
sim/driver.py: ... sign_command(event_id, now, ground_auth_secret) ...   # the only call site
```

```
$ grep -n "dt_s\s*=" tests/*.py tools/*.py policy/*.py
# every hit is 10.0, 60.0, or 3600.0 -- never a non-integral dt_s anywhere in this repo
```

The Task 5 golden-vector table (`mcu/firmware/app/tests/host_c_unit/
run_auth_equivalence.py`, generated by calling the real
`engine.auth.sign_command()`, never hand-transcribed) is the binding
verification of this decision: if the C-side message-construction routine
described above ever produced a message differing from Python's real
output for any vector in the fixed `(event_id, now, secret)` matrix, that
test would fail. It does not (0 mismatches — see that test's own output).
