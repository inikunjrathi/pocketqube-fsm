# Decision Record 0013 — Nucleo-L476RG as a Second Firmware Target

**Date:** 2026-10-31

## Problem

The firmware only targeted the Nucleo-F401RE. The L476RG was requested as a
second target. It is simulation-only like the F401RE: no physical board has
been programmed or measured, so no timing or power claim follows from it.

## Decision

Add `nucleo_l476rg` beside `nucleo_f401re`, selected with `CEPDT_BOARD`. The
F401RE stays the default and the paper's target.

- **Banks.** Zephyr's board file has no `slot0`/`slot1` partitions, so
  `mcu/firmware/app/boards/nucleo_l476rg.overlay` defines them. Each is one
  2 KiB page, at flash offsets `0x7F800` and `0xF7800`, one in each physical
  flash bank.
- **Writes.** L4 flash programs 8-byte double-words and the record is 556
  bytes, so `engine_persist_io_write()` pads to `write-block-size` with `0xFF`
  (560 bytes on flash). The CRC still covers the same span. On the F401
  `write-block-size` is 1 and the branch compiles away: `zephyr.bin` is
  byte-identical before and after this change, so the F401 evidence stands.
- **Simulation.** Renode ships no STM32L4 platform, RCC or flash controller.
  `mcu/renode/stm32l476.repl` reuses Renode's register-compatible USART and
  GPIO models, and adds small inline models for RCC and the flash controller.

## Verification

Run on the simulated L476 (Renode 1.17.0, Zephyr v4.2.2, seed 42):

| Check | Result |
|---|---|
| `verify_persistence_ab_bank.py` | 12 of 12 steps, including both torn-flash faults |
| `verify_arbitration_over_uart.py` | 400 cases, 0 failed |
| `verify_auth_short_circuit.py` | 4 of 4 cases |
| `verify_scheduler_over_uart.py` | 15 scenarios, 90 steps, 0 mismatches |
| `verify_ground_contact_gate.py` | 4 of 4 cases |
| `replay_baseline.py` config-a | 35,763 calls, 0 mismatches |
| `replay_baseline.py` config-b | 35,761 calls, 0 mismatches |
| `replay_baseline.py` config-c | 35,761 calls, 0 mismatches |

The config-a decision log is byte-identical to the committed F401 log in
`mcu/host_bridge/evidence/task8_baseline_seed42/config-a/`. The L476 logs are
not committed; pass `--out-dir` to regenerate them without overwriting that
evidence.

Image size: 36,640 B flash (3.49 % of 1 MB), 12,224 B RAM (12.43 % of 96 KB).

## Flash ECC on a torn write

The F401 has no flash ECC. The L4 does: per RM0351, an uncorrectable ECC error
on read raises an NMI. A power cut during programming can leave a double-word
with bad ECC, so reading a torn bank faults before the CRC check runs. Zephyr's
L4 flash driver has no ECC handling and its default NMI handler hangs, so one
torn write could stop the firmware on every boot with a good bank still in
flash.

`engine_flash_ecc_stm32l4.c`, built for the L4 only, handles this. Its NMI
handler reads the failing address from `FLASH_ECCR`, erases that page, and
returns. The retried read sees erased flash, which `load()` already treats as
a bank with no record, so it falls back to the other bank and the next save
repairs this one. Erasing costs nothing, because a record with an uncorrectable
error is unusable anyway.

- Only a page inside a persistence bank is erased. An NMI without `ECCD`, a
  system-flash fault, or any other address keeps Zephyr's default hang:
  erasing code flash would make things worse.
- The handler returns only if the erase reported no error, because otherwise
  the retried read would fault forever.
- A fault on both banks still loses the record, as any two-fault case does.

`verify_flash_ecc_nmi.py` passes 41 checks on the simulated L476: faults in both
banks, including the last double-word of a page, and five refused cases.
Removing the range check, or ignoring the `BK_ECC` bit, makes it fail.

**Still open.** Renode computes no ECC, so that verifier injects a fault by
setting `FLASH_ECCR` and pending the NMI while the CPU is idle. It proves the
handler's decisions and erase, not a real fault taken on a read: the retried
read, the address the hardware reports, and whether real torn flash faults at
all are unverified. Those need a real board and timed power cuts, and until then
the firmware does not claim to survive a power cut on an L476.

## Limits of the models

The RCC model only echoes ready bits, and the flash model does not enforce PG.
Neither models timing or wear. Wear figures in decision 0012 were derived for
the F401's 128 KB sectors and have not been re-derived for 2 KiB L4 pages.
