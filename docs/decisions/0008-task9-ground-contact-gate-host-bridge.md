# Decision Record 0008 — Task 9's Interpretation: Host-Bridge Contact Gate, Not a Second Renode Node

**Date:** 2026-08-08 (Phase 8, Task 9 — optional stretch, Phase 8.8)

## What was done

Pre-work "Step 0" investigation task-9-brief.md requires before building anything:
determine whether a literal two-Renode-machine "Wireless plugin" setup fits this
project's actual board model (Nucleo-F401RE / `platforms/cpus/stm32f4.repl`), and
record the resulting interpretation decision before implementation, per the
brief's own instruction ("before building anything substantial").

## The problem

The plan's Task 9 text names Renode's "Wireless plugin" as the mechanism for a
second simulated node. Checking Renode's own bundled examples
(`/opt/renode/scripts/multi-node/efr32xg24-twonode_demo.resc`,
`nrf52840-ble-zephyr.resc`) confirms the brief's premise: every multi-node example
built on an RF medium (`emulation CreateIEEE802_15_4Medium`/`CreateBLEMedium`)
requires each participating machine's platform description to expose a
`sysbus.radio` peripheral. `platforms/cpus/stm32f4.repl` (grepped directly,
confirmed empty match for `radio`/`Medium`/`sysbus.radio`) has no such peripheral
— it is a GPIO/UART/NVIC/RCC-only SoC description, matching this project's own
Global Constraints (RF hardware selection stays out of scope throughout;
`docs/parameters.md` P-023). A literal RF-medium two-node setup
is confirmed infeasible without inventing a radio subsystem this satellite was
never designed to carry.

## Investigation: is there a non-RF multi-node primitive? (brief's option 1)

Checked further before concluding "dead end" — Renode's own scripts directory has
multi-node examples that do **not** use an RF medium at all:
`/opt/renode/scripts/multi-node/nrf52840-ble-hci-uart-zephyr.resc` and
`/opt/renode/scripts/multi-node/imxrt500_nrf52840_pigweed_bt_advertiser.resc` both
use `emulation CreateUARTHub "<name>"` + `connector Connect <uart-peripheral>
<hub-name>` to wire two machines' UARTs together directly through a real Renode
interconnect primitive, no radio medium, no `sysbus.radio` peripheral required.
Combined with `emulation SetGlobalSerialExecution true` (used in the RF examples
for a shared time base, and equally applicable here), this means **a real
two-`mach create`d-machine setup with a shared emulation clock and a genuine
UART-only interconnect between two STM32F4-family Renode nodes is technically
buildable** — the brief's option 1 is not a literal dead end the way the
RF-medium reading is.

This changes the shape of the decision: it is not "Renode can't do this without a
radio," it's "what would the second node's own firmware actually *do*, and is
that content honest or contrived?"

## Why option 1 (two real Renode machines) was still not chosen

A second `mach create`d node needs its own firmware image to be a real machine,
not a decoration. Two candidates were considered and rejected:

1. **Node 2 recomputes contact windows itself.** Rejected outright — this would
   require porting `sim.orbit.find_passes()`/SGP4 propagation into C running on
   the second node, which is exactly the "no independently-authored contact-
   window math" the plan's Global Constraints and this brief both forbid. The
   real contact-window computation is host-side Python and stays there.
2. **Node 2 is a "dumb" relay: it forwards bytes to node 1's UART only while an
   OPEN/CLOSE flag (set by the host, which does the real computation) is open.**
   Technically buildable with `CreateUARTHub` — but its firmware would contain no
   actual decision logic of its own; the real gating decision is still 100%
   host-side Python, communicated to node 2 only so node 2 can mechanically echo
   it. This project has never modeled ground-station hardware anywhere in its
   architecture (Global Constraints: ground-station network
   selection is explicitly out of scope; the "ground station" in every other task
   is the host bridge script talking to real Phase 7B host-side math). Inventing
   a relay-MCU stand-in for a ground station now, solely so two Renode machines
   can be said to exist, is the same category of problem the brief already flags
   for the RF medium: a fictional device invented to check a box, not to model
   anything this program's actual architecture claims exists. It would not add
   verification value over doing the identical gating check directly in the host
   bridge (which already IS this project's ground-segment stand-in, per every
   prior task's UART-bridge framing) — it would only add a second Zephyr build
   target, a second `.resc` machine, and a second failure surface for a
   decision that is still made in the exact same place either way.

## Decision

**Take the brief's option 2: keep the single satellite Renode node
(`mcu/renode/nucleo_f401re.resc`, unmodified). Extend the host bridge itself —
already this project's real, established stand-in for "the ground segment" in
every prior task — with a contact-window gate.**

The gate (`mcu/host_bridge/ground_contact_gate.py`) computes real contact windows
via `sim.orbit.find_passes()` against `sim.scenario.GROUND_STATIONS_DUAL` (Config
C's own reference scenario, per `docs/decisions/0006-config-c-generality-axis.md`
— "Config C also adopts the Phase 7B dual-ground-station set as its own reference
scenario"), maps simulated seconds to the same UTC epoch `sim/driver.py`'s tick
loop uses (`sim.driver._epoch_datetime()`, imported/reused, not reimplemented),
and refuses to write a ground-sourced `INJECT` to the real Renode-simulated
UART unless the current simulated time falls inside a real, freshly-computed
contact window — logging why when it refuses. Config C (Task 5's ground-auth-
enabled build, `ENGINE_GROUND_AUTH_ENABLED`) is the demonstration target, per the
brief's own suggestion, since it is both the config whose reference scenario is
already `GROUND_STATIONS_DUAL` and the config for which HMAC ground-command auth
is a first-class, already-built feature.

This keeps "two-node Renode simulation" aspirational rather than literal, exactly
as the brief anticipated for this fallback path — but it is a real fix for the
actual problem Task 9 describes ("the host bridge can send `INJECT` at any
simulated time regardless of pass geometry"), it reuses Phase 7B's real trusted
contact-window math with zero new orbital/RF logic, and it runs the "allowed"
half of its demonstration over the genuine Renode-simulated UART round trip (the
"blocked" half is provably blocked before a single byte reaches that wire — see
`docs/phase8-c-port.md`'s Task 9 section for the verification transcript proving
this both ways: the gate blocks it, and the same command sent by bypassing the
gate directly proves the firmware itself has no timing model at all, which is
correctly a ground-segment responsibility, not a satellite-firmware one).

## What was deliberately NOT done, and why

1. **No `mcu/renode/` second node or new `.resc` script.** Per the reasoning
   above — would only add a fictional relay device, not new verification value.
2. **No new firmware target, CMake target, or Zephyr app for a "ground station."**
   Same reasoning; this project has no real ground-station embedded hardware to
   port, and inventing one contradicts the same scope discipline that ruled out
   the RF medium.
3. **No change to `mcu/renode/nucleo_f401re.resc`, `engine/*.py`, or `sim/*.py`.**
   Unmodified, per Global Constraints (verified via `git status`/`git diff`
   after this task, see the progress-ledger entry).
4. **No independently-authored contact-window math.** `ground_contact_gate.py`
   calls `sim.orbit.find_passes()` directly for the actual window computation
   and only adds a membership test (`aos <= now <= los`) on the real, already-
   computed `Pass` objects it returns — not a re-derivation of the elevation/
   pass-detection logic itself.

## Evidence this decision relies on

```
$ grep -n "radio\|Medium\|sysbus.radio" /opt/renode/platforms/cpus/stm32f4.repl
# (no output -- confirmed no radio peripheral in this project's platform description)

$ grep -rn "CreateUARTHub" /opt/renode/scripts/
scripts/multi-node/imxrt500_nrf52840_pigweed_bt_advertiser.resc:6:emulation CreateUARTHub "hci_beacon"
scripts/multi-node/imxrt500_nrf52840_pigweed_bt_advertiser.resc:7:emulation CreateUARTHub "hci_observer"
scripts/multi-node/nrf52840-ble-hci-uart-zephyr.resc:4:emulation CreateUARTHub "central_hci"
scripts/multi-node/nrf52840-ble-hci-uart-zephyr.resc:5:emulation CreateUARTHub "peripheral_hci"
# confirms a real, non-RF Renode multi-node primitive exists -- option 1 was
# rejected on engineering-honesty grounds (what node 2's firmware would
# actually DO), not because Renode lacks the mechanism.
```

Full verification of the built gate itself is in `docs/phase8-c-port.md`'s new
"Task 9" section (real contact-window pass data computed via
`sim.orbit.find_passes()` against `GROUND_STATIONS_DUAL`, and the end-to-end
gated/ungated demonstration transcript over the real single-node Renode UART).
