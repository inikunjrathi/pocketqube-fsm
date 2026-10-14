# Decision Record 0011 — The Latch-Setting Save Writes Both Banks

**Date:** 2026-10-14 (manuscript-review response, persistence track)

## Problem

A review asked whether the deployment latch really survives "any
single-bank corruption", as the manuscript claimed. It did not in one
window. Each save went to the alternate bank only, so after the save that
set the latch, the latch lived in one bank until the next save:

```
save S-03, latch unset   -> bank A, seq 0
save S-04, latch set     -> bank B, seq 1
corrupt bank B
load()                   -> S-03, deployment_confirmed = false
```

Torn writes could not cause this: a torn write damages the bank being
written, and the write after the latched save targets the other bank. A
bit flip or retention failure in the newest bank before the next save
could. The R-29 tests did not catch it, because each saved the latched
state twice before corrupting a bank. The TLC model did not catch it,
because it abstracts the two banks as one "last completed save" and
models torn saves only.

## Decision

`save()` writes the alternate bank as before. If the record sets a latch
that the other bank does not hold (the other bank is blank, CRC-invalid,
or stores the latch as false), the same record is then written to the
other bank with the next sequence number. The latch is committed when
that save returns.

- `engine/persistence.py`: `PersistenceLayer(latch_names)`;
  `sim/driver.py` and `policy/oracle.py` pass `cfg.latches`.
- `mcu/firmware/app/src/engine_persistence.c`: the same rule, reading
  latch names from the generated `g_latches[]` table and the stored
  entries directly (not `decode_body()`, whose static buffers may back the
  caller's context). The CRC covers only the body, so the copy keeps the
  same CRC.

## Case analysis (one fault at a time)

| Fault | Outcome |
|---|---|
| Reset during an ordinary save | Older bank loads; last completed save restored |
| Reset during the first write of the latch-setting save | Latch not committed; older record loads with the latch unset; deployment is confirmed again |
| Reset during the mirror write | First copy is valid and holds the latch |
| Corruption of either bank after the latch-setting save returns | The other bank holds the latch |
| Corruption of both banks | Nothing valid; initial state, latch lost (double fault, out of scope) |
| Bit flip raising the older bank's sequence field (outside the CRC) | A stale record may load; once committed, both banks hold the latch, so the latch is kept but the state may be stale |

## Evidence

- `tests/test_persistence.py`: the review's sequence on both banks; the
  same sequence without latch names (pins why callers must pass them); a
  torn mirror write; one mirror only, then normal alternation; every save
  history of up to five saves with corruption of either bank.
- `tests/test_latch_fuzz.py`: the random walk now corrupts either bank at
  random, including straight after the latch-setting step. Its earlier
  comment called that "an unattainable guarantee".
- `mcu/firmware/app/tests/host_c_unit/harness_persistence_main.c`: the
  window on both banks, gcc and clang, `-Wall -Wextra -Wpedantic -Werror`.
  The old C code fails the bank-B case.
- `mcu/host_bridge/verify_persistence_ab_bank.py` now corrupts bank B, the
  more-recent bank under mirroring. It has not been re-run on Renode: the
  Zephyr toolchain was not installed when the change was made, so the
  firmware image was not rebuilt.

## Not changed

Decisions are unaffected: `load()` returns the same record content, so
every simulation result and the 35,763-call replay trace are unchanged.
The TLA+ model still abstracts the banks as one snapshot; bank
corruption is covered by the tests above, not by TLC.
