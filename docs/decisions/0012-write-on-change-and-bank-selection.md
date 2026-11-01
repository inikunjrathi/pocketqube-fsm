# Decision Record 0012 — Write on Change, and Bank Selection

**Date:** 2026-10-31 (firmware rebuild and re-measurement)

## Problem

Rebuilding the firmware and counting flash writes exposed a wear problem.
`save()` ran after every legal step and each write erased a 128 KB sector.
A 48 h Config A run made 18,307 bank writes, of which 31 changed the stored
content. At that rate each bank reaches the 10,000 cycles assumed from the
STM32F401xB/C data sheet (not confirmed for the xE part) in about 52 h, and
10.2 h to 20.3 h of the run is spent erasing (2 s typical, 4 s maximum per
128 KB sector at byte parallelism, STM32F401xD/xE data sheet).

Reviewing the fix found three defects in how a bank was chosen, none of them
reachable by the tests or models of the time:

1. **Overwriting the only good copy.** The target was "the bank not written
   last". A torn record has a readable sequence and looks newest, so the next
   save overwrote the one valid bank. Two resets in a row lost everything.
2. **Sequence wraparound.** The next sequence read every bank, valid or not. A
   torn erase can leave a value near `0xFFFFFFFF`, and the C counter wraps.
3. **Sequence outside the CRC.** A tear of the sequence field alone left a
   CRC-valid record with a garbage sequence, so a stale record could win. The
   power-cut harness found this one in the first version of this fix.

## Decision

- A save that both banks already match writes nothing.
- A save that changes the content writes both banks: first the bank not
  holding the newest valid record, then the other. A bank that already holds
  the content is not rewritten, so a damaged or stale bank is repaired by the
  next save with one write.
- The sequence comes from the newest valid bank only, and the CRC covers it.
- In C, a failed first write stops the second, which would otherwise erase
  the good copy.

Mirroring every change replaces decision 0011's latch-only mirror, so
`PersistenceLayer` no longer takes latch names.

## Alternative rejected

Writing one bank per change and mirroring only latch changes gives half the
wear (about 3.4 years against 1.8 in the reference scenario). It leaves the
older bank one content change behind for as long as nothing changes, so
corrupting the newest bank rolls the state back one transition. The R-29
fault-injection sweep caught this, and the guarantee is not worth trading: a
rollback can repeat an action that only a latch guards.

## Case analysis (one fault at a time)

| Fault | Outcome |
|---|---|
| Reset during the first write of a change | Older record loads; the next save writes it again |
| Reset during the second write | First copy is valid and is the new record |
| Corruption of either bank after a save returns | The other bank restores the same record; the next save repairs the damaged bank |
| Torn erase or program, with a garbage sequence | Bank invalid; ignored by load, target choice and the sequence counter |
| Bit flip in a sequence field | Bank invalid (replaces 0011's stale-record case) |
| Reset again on the next write | The only valid bank is never the target, so it survives |
| Corruption of both banks, or corruption plus a reset during one save | Double fault, out of scope |

## Cost and remaining limits

- 48 h, seed 42: 62 writes on Config A and 26 on B and C, half per bank. On the
  assumed endurance Config A reaches 10,000 cycles after about 1.8 years at
  that rate. Stress scenarios that cycle through safe mode write more.
- Each change now blocks for two sector erases, 4 s to 8 s on the data-sheet
  figures. Whether that is tolerable has not been measured, and an erase may
  stall code running from flash.
- A log-structured record inside each sector would need far fewer erases. It
  is a larger change and was not attempted.

## Measured on the emulated F401RE

Seed 42, 48 h, `mcu/host_bridge/measure_firmware.py`, Zephyr v4.2.2, SDK 0.17.4.
Instruction counts exclude flash erase and program time.

| | Config A | Config B | Config C |
|---|---|---|---|
| Calls, mismatches | 35,763, 0 | 35,761, 0 | 35,761, 0 |
| Bank writes | 62 | 26 | 26 |
| Saves writing nothing | 18,275 | 18,291 | 18,291 |
| Step, median / max instructions | 3,422 / 4,986 | 3,375 / 4,296 | 3,375 / 4,296 |
| Load | 19,267 | 18,945 | 18,945 |
| Save, no write | 31,710 | 30,840 | 30,840 |
| Save, content change | 278,173 | 277,303 | 277,303 |
| Interrupt stack peak | 3,472 B | 3,376 B | 3,392 B |
| Flash image | 36,728 B | 34,372 B | 34,672 B |

RAM is 11,648 B on all three. Config A was measured twice, with identical
counts and stack peak.

## Evidence

- `tests/test_persistence.py`: write counts, repair, torn records, garbage
  sequence, a run-level wear budget.
- `mcu/firmware/app/tests/host_c_unit/harness_persistence_main.c`: 8,912 power
  cuts, one at every byte of every erase and program across a four-save
  history, each followed by a second cut on the next write, under gcc and
  clang. Eight hand-made C mutants are all detected.
- `docs/tla/persistence_ab.tla`: both banks, each erase and program step, and
  three protocol mutants that TLC must reject.
- `mcu/host_bridge/verify_persistence_ab_bank.py`: torn flash written directly
  into the emulated part, then a real CPU reset, through the Zephyr backend.
