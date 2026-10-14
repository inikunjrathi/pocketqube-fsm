# Phase 8: `engine/` on a simulated STM32 (Renode + Zephyr) — scope and status

**Scope note, restated up front because it must never drift:** this is a
**simulation-only** side-track. It closes the paper's stated limitation
"on-device deployment and power measurement were not attempted: no hardware
access was available" by demonstrating that the `engine/*.py` decision logic,
ported to C, reproduces the existing, verified Python implementation exactly
when run inside a Renode-simulated Nucleo-F401RE (Cortex-M4) under Zephyr.

**What this is NOT, and never claims to be:**
- Not a physical-hardware deployment. No real STM32F401RE board was
  programmed or measured.
- Not a power measurement. Renode has no meaningful power model at this
  fidelity; no current/energy numbers from this work should ever be cited
  as representative of real hardware.
- Not a real-time timing claim. Renode's simulated CPU does not model real
  Cortex-M4 cycle timing, cache effects, or bus contention; nothing here
  supports a physical-hardware latency claim.
- Not an RF architecture exercise. Frequency band, antenna, and
  ground-station network selection remain explicitly out of scope, in Task 9's contact-window stretch goal as everywhere
  else.
- Not a reopening of Phase 0–7D. `engine/*.py` and `sim/*.py` are never
  modified by this work; the C port is a new, parallel sibling (`mcu/`).

The only thing this work supports citing is: **"engine decision logic
verified equivalent, in simulation, to the existing verified Python
implementation, on a Renode-simulated Cortex-M4 running Zephyr."**

## Task 1 (Phase 8.0): environment status

Task 1 bootstraps the toolchain and proves a minimal Zephyr UART-echo
firmware round-trips over a Renode-simulated UART, with zero manual
Renode-monitor steps. It does **not** touch `engine/*.py` — that starts in
Task 2.

### Pinned versions

| Component | Version | Where |
|---|---|---|
| Renode | 1.16.1 | system package `renode-bin` (Arch/pacman), already installed |
| West | 1.5.0 | `mcu/.venv` (pip) |
| Zephyr | v4.2.2 (tag) | `~/zephyrproject/zephyr`, West-managed workspace |
| Zephyr SDK | **0.17.4** (arm-zephyr-eabi, gcc 12.2.0) | `mcu/.toolchains/zephyr-sdk-0.17.4/` (project-local, NOT the system `zephyr-sdk` pacman package) |
| dtc | 1.8.1 | system package |
| cmake | 4.4.2 | system package |
| ninja | 1.13.2 | system package |
| Board | `nucleo_f401re` | Zephyr board target (STM32F401RE, Cortex-M4) |

**Why a project-local SDK instead of the system one:** the host this was
built on already had a system-wide `zephyr-sdk` pacman package installed
(version `1.0.0`, gcc 14.3.0). Zephyr v4.2.2's own CMake modules
(`cmake/modules/FindHostTools.cmake`) request `find_package(Zephyr-sdk
0.16)`, and Zephyr SDK 1.0's `Zephyr-sdkConfigVersion.cmake` *deliberately*
declares itself incompatible with any request for a pre-1.0 version (a
real, intentional compatibility gate in the SDK's own CMake package, not a
bug) — so the system SDK cannot build this checkout of Zephyr at all.
Zephyr v4.2.2's own `zephyr/SDK_VERSION` file names `0.17.4` as the
version it was validated against, so that is what is installed, into
`mcu/.toolchains/` (project-local, does not touch or replace the system
package, does not require root). `mcu/scripts/build_firmware.sh` sets
`ZEPHYR_SDK_INSTALL_DIR` explicitly to this project-local path so the
build never silently picks up the incompatible system SDK.

Re-provisioning steps (idempotent, e.g. after a clean checkout on a new
host) are recorded as a comment at the top of `mcu/scripts/build_firmware.sh`.

### What was built

- `mcu/firmware/app/` — a minimal Zephyr application (`CMakeLists.txt`,
  `prj.conf`, `src/main.c`) that echoes every byte received on the board's
  console UART (`usart2`, PA2/PA3 — the same UART wired to the physical
  Nucleo's ST-LINK virtual COM port) straight back out, unbuffered, from
  interrupt context. `CONFIG_CONSOLE`/`CONFIG_UART_CONSOLE` are explicitly
  disabled (board defconfig enables them by default) so nothing but the
  echo loop ever writes to that UART. This is intentionally the simplest
  possible skeleton — it exists to prove the toolchain, not to implement
  any protocol. `west build -b nucleo_f401re` compiles it warning-free
  (15988 B flash / 4544 B RAM used, well under the F401RE's 512 KB/96 KB).
  **These figures are for this Task 1 echo-loop skeleton only, not for the
  engine firmware.** The default engine firmware (config A table, auth
  and test hooks off) was rebuilt from commit `bddb420` on 2026-10-11
  with this script, Zephyr v4.2.2 and Zephyr SDK 0.17.4
  (arm-zephyr-eabi-gcc 12.2.0). The linker reported **FLASH 35,140 B
  (6.70 % of 512 KB) and RAM 11,648 B (11.85 % of 96 KB)**. `size`
  reports text 34,992 / data 140 / bss 11,504. The ELF's sha256 is
  `31746ba7…49b7f8`. RAM is dominated by `CONFIG_ISR_STACK_SIZE=8192`.
  The app's own objects (`libapp.a`) account for 12,914 B of text and
  1,033 B of bss, of which `engine_config_table.c` is 6,334 B text and
  `engine_auth.c` is 407 B text / 68 B bss. The HMAC/SHA-256 code is
  linked from Zephyr's mbedTLS module and counted outside `libapp.a`.
  From Task 4 onward, `src/main.c`'s echo loop is replaced by the real
  `INJECT`/`DECISION` UART bridge dispatch loop described in the plan's
  Global Constraints section; the `CMakeLists.txt`/`prj.conf` scaffolding
  is expected to be extended, not rewritten.

- `mcu/renode/nucleo_f401re.resc` — a Renode monitor script that loads
  Renode's **existing bundled** SoC-level platform description,
  `platforms/cpus/stm32f4.repl` (Renode 1.16.1 ships no board-specific
  `nucleo_f401re.repl`; this is the same underlying description the
  bundled `stm32f4_discovery` board is built from — the Nucleo-F401RE
  (STM32F401RE) and Discovery board (STM32F407VG) are both STM32F4-family
  parts with an identical peripheral register map for the peripherals
  this project uses (GPIO, USART2, NVIC, RCC); only flash/SRAM capacity
  and pinout/silkscreen differ, neither of which matters for a firmware
  image using well under 5% of either part's real capacity). No new
  `.repl` file was authored, per the plan's constraint. The script exposes
  `sysbus.usart2` on a host-visible pty via Renode's
  `emulation CreateUartPtyTerminal` monitor command and boots with `start`.

- `mcu/scripts/run_renode.sh` — boots the built firmware headless. Runs
  Renode in `-P <port>` (Monitor-over-telnet) daemon mode rather than
  `--console`: `--console` reads further Monitor commands from stdin, and
  when this script is launched as a background subprocess (stdin
  closed/EOF, as any scripted harness does) that causes Renode to execute
  an implicit `quit` and exit right after boot. `-P` removes that stdin
  dependency entirely so the simulation runs indefinitely until killed.
  Nothing in this project talks to that Monitor port; it exists purely so
  the process doesn't exit — all real interaction happens over the UART
  pty.

- `mcu/scripts/uart_roundtrip_check.py` — the scripted, non-interactive
  round-trip test. It owns the full lifecycle: launches
  `run_renode.sh` as a managed subprocess (in its own process group, via
  `start_new_session=True` — necessary because `/usr/bin/renode` itself
  spawns `dotnet` as an un-`exec`'d child, so a plain `SIGTERM` to the
  top-level pid would leak the actual Renode/dotnet process; cleanup
  signals the whole group), polls for the UART pty to appear, connects
  with `pyserial`, sends four payloads (a single byte, a short ASCII
  string, a string containing an embedded `\n`, and all bytes 0x01–0x7F),
  asserts each echoes back byte-for-byte, then tears the simulation down
  and removes the pty. Exit code 0 = pass. Confirmed re-runnable
  back-to-back with no leftover Renode/dotnet processes or stale ptys.

### Verification performed

```
mcu/scripts/build_firmware.sh          # clean west build, warning-free
mcu/.venv/bin/python3 mcu/scripts/uart_roundtrip_check.py
```

Both commands are re-runnable from a clean checkout given the pinned
versions above (`mcu/.toolchains/zephyr-sdk-0.17.4/` and
`~/zephyrproject/` must be provisioned first — see
`mcu/scripts/build_firmware.sh`'s header comment for exact re-provisioning
steps). Sample passing output of the round-trip test:

```
PASS case 0: 1 bytes echoed correctly
PASS case 1: 14 bytes echoed correctly
PASS case 2: 38 bytes echoed correctly
PASS case 3: 127 bytes echoed correctly
PASS: all 4 round-trip case(s) echoed correctly, zero manual Renode-monitor steps.
```

### Known environment caveats (not blockers, recorded for later tasks)

- `platforms/cpus/stm32f4.repl`'s `sysbus: init:` block does an
  `ApplySVD @https://dl.antmicro.com/...` on first machine creation (used
  for register-name introspection in the Monitor/GUI, not required for
  functional simulation). This is a one-time network fetch per Renode
  process invocation, cached by Renode itself
  (`~/.config/renode/renode-cache` equivalent) after the first run on a
  given host. A fully offline host would need this SVD pre-cached.
- The project-local Zephyr SDK install (`mcu/.toolchains/`) is
  intentionally excluded from version control (binary toolchain, ~370 MB
  unpacked); `.gitignore` covers it. Re-provisioning is scripted (see
  above), not manual.

## UART bridge protocol reference (Tasks 4–7, finalized)

Task 7 Step 3 ("finalize the UART protocol") audited every UART
command/reply this firmware's own modules emit or accept — `INJECT`/
`DECISION`/`ERROR`/`READY` (Task 4), `TESTHOOK CORRUPT`/`TESTHOOK LOAD`
(Task 6), and the new `TESTHOOK SCHED <op> ...` family (Task 7, this
task) — and confirms they all conform to ONE consistent grammar, with no
per-module ad hoc deviation. This section is the single authoritative
reference for that finalized grammar (the canonical source is still
`mcu/firmware/app/src/main.c`'s own top-of-file comment, which this
section summarizes and cross-checks).

**Reminder, restated from the plan's Global Constraints (this protocol is
internal test-harness plumbing, not a flight interface):** every command
and reply below exists only so a host-side Python script can drive this
firmware deterministically and diff its output against the real Python
`engine.*` implementation. None of it is a candidate flight command
interface.

### Framing

Line-oriented ASCII, `\n`-terminated, both directions. Tokens within a
line are space-separated (`next_token()` in main.c: skips leading spaces,
splits on the next space). No quoting/escaping mechanism exists anywhere
in this grammar — no field in any command or reply, across any module,
ever needs an embedded space (verified: item ids/data-class names/state
ids/event ids are all short bare identifiers in every fixture and
TESTHOOK-driven scenario this project uses; the one field that legitimately
contains embedded content, an action's raw string in a `DECISION` line's
`actions=` list, is always the LAST field on the line for exactly this
reason — see `uart_bridge.py`'s `_parse_decision_line()`, which parses
positionally rather than blindly splitting on every space).

### Firmware → host

| Line | When | Notes |
|---|---|---|
| `READY` | Once, at boot, after the UART IRQ is armed | Avoids a host-side startup race (`UartBridge.wait_for_ready()`). |
| `DECISION <now> <from_state> <event_id> -> <to_state> transition=<id\|NONE> legal=<0\|1> actions=<a1,a2,...\|NONE>` | Every successfully-parsed `INJECT` | Mirrors `engine.decision_log.DecisionLogger.record_transition`'s fields in a fixed order. `NONE` is this grammar's shared "no value" sentinel — used for an absent `transition_id` and an empty `actions` list alike. |
| `OK` | A successful `TESTHOOK CORRUPT`, or a successful `TESTHOOK SCHED RESET`/`INSERT` | Bare `OK` — no further data to report. |
| `OK <field>=<value>...` | `TESTHOOK LOAD` and every other successful `TESTHOOK SCHED` sub-command | These commands have data to report, so their success reply carries one or more `field=value` tokens instead of a bare `OK`. `OK NONE` is the shared "no data" case (e.g. an empty scheduler's `SELECT`/`PEEK_CLASS`/`CANDIDATES`) — this is a *successful*, expected result (Python returning `None`), never an `ERROR`. |
| `ERROR <reason> [<detail>]` | Any malformed `INJECT`/`TESTHOOK`, an unknown command, a disabled/not-yet-implemented `TESTHOOK`, or the `GuardError`-equivalent hard-fault case (`guard_telemetry_missing`) | `<reason>` is always `lower_snake_case`; `<detail>` (optional, space-separated) is the offending token/value where one exists (e.g. `unknown_event E-99`). |

### Host → firmware

**`INJECT <event_id> <state_id> <now> <k=v>* ; <k=v>* [SIG <hex64>]`**
— one stateless `engine_fsm_step()` RPC. `<k=v>*` before the literal `;`
token is the context map, `<k=v>*` after it is the telemetry map. Value
grammar: `true`/`false` → bool; else numeric if it matches
`-?\d+(\.\d+)?` (mirrors `engine/guards.py`'s `_NUMBER_RE`); else a bare
string. Every telemetry value must be numeric (every telemetry-referenced
guard across configs A/B/C is numeric) — a non-numeric telemetry value is
`ERROR telemetry_value_not_numeric`, never silently coerced. `SIG
<hex64>`, if present, must be the last token on the line.

**`TESTHOOK <name> <args>`** — fault-injection/introspection commands,
kept in a distinct top-level family from `INJECT` so a captured log is
never ambiguous about production-shaped vs. test-only traffic (Global
Constraints). Every `TESTHOOK` sub-family is off by default and gated
behind its own CMake cache option (see the table below) — a
default/production build accepts NO `TESTHOOK` command at all (every one
replies `ERROR testhook_not_implemented`).

| Command | Task | Gate flag | Reply |
|---|---|---|---|
| `TESTHOOK CORRUPT <A\|B>` | 6 | `ENGINE_PERSIST_TESTHOOKS_ENABLED` | `OK` / `ERROR bad_testhook_bank` / `ERROR testhook_corrupt_failed` |
| `TESTHOOK LOAD` | 6 | `ENGINE_PERSIST_TESTHOOKS_ENABLED` | `OK state=<id> deployment_confirmed=<0\|1>` / `ERROR testhook_load_no_record` |
| `TESTHOOK SCHED RESET <classes>` | 7 | `ENGINE_SCHED_TESTHOOKS_ENABLED` | `OK` / `ERROR bad_sched_reset_classes` |
| `TESTHOOK SCHED INSERT <id> <data_class> <size_bytes> <deadline\|NONE>` | 7 | `ENGINE_SCHED_TESTHOOKS_ENABLED` | `OK` / `ERROR sched_unknown_class <data_class>` / `ERROR sched_queue_full` / `ERROR bad_sched_insert_args` / `ERROR bad_sched_size_bytes` / `ERROR bad_sched_deadline` |
| `TESTHOOK SCHED SELECT` | 7 | `ENGINE_SCHED_TESTHOOKS_ENABLED` | `OK id=<id> data_class=<class> size_bytes=<n> deadline=<val\|NONE>` / `OK NONE` |
| `TESTHOOK SCHED SELECT_EDF` | 7 | `ENGINE_SCHED_TESTHOOKS_ENABLED` | same shape as `SELECT`, using `sim/driver.py`'s `_edf_key` |
| `TESTHOOK SCHED PEEK_CLASS` | 7 | `ENGINE_SCHED_TESTHOOKS_ENABLED` | `OK data_class=<class>` / `OK NONE` |
| `TESTHOOK SCHED CANDIDATES` | 7 | `ENGINE_SCHED_TESTHOOKS_ENABLED` | `OK classes=<c1,c2,...>` / `OK classes=NONE` |
| `TESTHOOK SCHED IS_EMPTY` | 7 | `ENGINE_SCHED_TESTHOOKS_ENABLED` | `OK empty=<0\|1>` |
| any other `TESTHOOK <name>` | — | — | `ERROR testhook_not_implemented` |

`ENGINE_PERSIST_TESTHOOKS_ENABLED` and `ENGINE_SCHED_TESTHOOKS_ENABLED`
are deliberately SEPARATE build flags (`CEPDT_ENGINE_PERSIST_TESTHOOKS_ENABLED`
/ `CEPDT_ENGINE_SCHED_TESTHOOKS_ENABLED` CMake cache options, both OFF by
default), not one shared flag — scheduler test hooks never touch flash or
persisted state and are semantically independent of the persistence
hooks, matching this project's established "each new testable capability
gets its own opt-in flag" precedent (see also
`CEPDT_ENGINE_GROUND_AUTH_ENABLED`, Task 5). Any combination of these
three flags builds and links cleanly (verified for all four combinations
of the two `TESTHOOK` flags during Task 7).

### Consistency audit (Task 7 Step 3's actual deliverable)

Confirmed by re-reading every reply site in `main.c` line-by-line:

- Every reply line, across every module, is one of exactly three shapes:
  a bare status word (`READY`, `OK`), a fixed-field-order data line
  (`DECISION ...`, `OK <field>=<value>...`), or `ERROR <reason>
  [<detail>]`. No module invents a fourth shape.
  `NONE` is the one shared sentinel for "no value" everywhere it appears
  (`transition=NONE`, `actions=NONE`, `deadline=NONE`, `OK NONE`,
  `classes=NONE`) — no module uses a different spelling (`null`, `-`,
  empty string) for the same concept.
- Every `ERROR` reason string is `lower_snake_case`, optionally followed
  by one space-separated detail token — no module uses a different
  casing or a multi-word untagged reason.
- Every `TESTHOOK` sub-family follows the identical "off by default,
  one dedicated CMake cache option, always compiles the underlying
  `engine_*` capability but gates only the UART dispatch reachability"
  pattern — Task 7's `TESTHOOK SCHED` family is not a special case.

No ad hoc per-module extension to this grammar was found or introduced.

## Task 8 (Phase 8.7): full seed=42 baseline equivalence run

This is the headline Phase 8 evidence artifact: the same seed=42, 48 h,
`dt_s=10s` reference scenario `tools/generate_baseline_results.py` uses to
produce `docs/baseline-results.md` (config A), replayed end-to-end through
the real Renode-simulated firmware and diffed line-for-line against the
real Python `engine.fsm.step()`.

### The trace-extraction problem and its resolution

`engine.decision_log.DecisionLogEntry` only records *legal* transitions and
never stores the `context`/`telemetry` a firmware replay needs to
reproduce a call — it cannot drive a replay by itself. `mcu/host_bridge/
replay_baseline.py` solves this by monkey-patching the `step` name
`sim/driver.py` imports (`from engine.fsm import step`) for the duration
of one `run_simulation()` call, with a thin recorder that calls through to
the real, unmodified `engine.fsm.step()` and additionally records every
call's exact input/output, then restores the original name afterward.
This observes the run without changing a byte of `engine/*.py` or
`sim/*.py` (Global Constraint, inviolable) — module-level names are looked
up through the module's own `__dict__` at call time, so every real call
site inside `sim/driver.py` (`_try_fire`, `_run_bootstrap`,
`_reenter_comms_mode`, and the tick loop's own scheduler-select call) is
transparently observed. One caller is deliberately excluded:
`_find_bootstrap_path`'s breadth-first search also calls `step()`, but
purely to explore the config's transition graph for the shortest bootstrap
path — none of those exploratory calls are ever applied to the real
running `(state, context)`, only the winning path's events get genuinely
re-fired (by `_run_bootstrap`/`_reenter_comms_mode`). Excluding them is
verified correct, not just plausible: the captured trace's legal-call
count and scheduler-call count are cross-checked against Python's own
`decision_log` bookkeeping (`verify_trace_cross_check()`) before Renode is
ever touched. Full rationale, including why the real call count (~35.8k)
is far larger than initially estimated and why that's genuine rather than
an over-eager capture, is in `replay_baseline.py`'s own module docstring.

### What was run

- `mcu/host_bridge/replay_baseline.py --config config-a` — captures the
  real trace, replays it as `INJECT` lines over **one continuous** Renode
  session (rebooting per event would defeat the point of testing
  persistence continuity across a single mission timeline), diffs every
  `DECISION`/`ERROR` response against the oracle tuple captured at the
  exact same call, and archives both logs.
- **35,763 real `engine.fsm.step()` calls** captured for config A (18,306
  legal, 17,457 illegal) — dominated by `_try_fire(POWER_LOW)`/
  `_try_fire(PASS_END)`, attempted on effectively every one of the 17,281
  ticks once the satellite settles into a comms-mode state early in the
  run (bootstrap completes within the first few simulated hours; no
  fault/watchdog event is ever modeled by this driver — see
  `sim/driver.py`'s own module docstring). This is a real, verified count,
  not a bug: it was cross-checked against `sim_result.decision_log`'s own
  bookkeeping before trusting it (see above).
- **Result: 0 mismatches**, out of 35,763 cases, against the real
  `engine.fsm.step()` oracle.
- **Run twice for reproducibility** (this project's established Renode
  verification discipline — see Tasks 1/4/5/6/7 above): both runs
  produced byte-for-byte identical archived logs (`diff` against the
  first run's committed archive shows zero differences in either file).

### Archive location

Both logs are committed, gzip-compressed (this JSON is highly repetitive
— gzip -9 shrinks it ~24-25x, so the full run is a few hundred KB
compressed rather than ~15-16 MB raw):

- `mcu/host_bridge/evidence/task8_baseline_seed42/config-a/python_trace.jsonl.gz`
  — the real captured Python call trace: one JSON object per real
  `step()` call, in order, with the exact `(caller, from_state, event_id,
  now, context, telemetry)` input and the real `engine.fsm.step()`
  output that call produced (the oracle).
- `mcu/host_bridge/evidence/task8_baseline_seed42/config-a/firmware_decisions.jsonl.gz`
  — the firmware's own `DECISION`/`ERROR` response sequence, one JSON
  object per response, in the same order (index-aligned with the Python
  trace file) so the two can be compared line-for-line
  (`zcat file.jsonl.gz | jq -c .` to inspect either directly).

**To regenerate:**

```
export CEPDT_WEST="$(pwd)/mcu/.venv/bin/west"
export ZEPHYR_SDK_INSTALL_DIR="$(pwd)/mcu/.toolchains/zephyr-sdk-0.17.4"
.venv/bin/python3 mcu/host_bridge/replay_baseline.py --config config-a
```

(Needs both `sim`/`engine`'s runtime deps and `pyserial` in the same
interpreter — the top-level repo `.venv` with `pyserial` added via
`requirements-dev.txt`, not `mcu/.venv` — see `replay_baseline.py`'s own
usage docstring for why this is the one host-bridge script that needs
both.) `--limit N` replays only the first N real calls, for a fast
smoke test before committing to the full run's several-minutes
wall-clock cost.

Configs B and C were left as the documented stretch goal (Step 4) — not
attempted, since config A alone already meets the "Done when" bar.

## Task 9 (Phase 8.8, optional stretch): contact-window-gated ground command injection

**Status: complete, via a scoped-down interpretation — recorded in
`docs/decisions/0008-task9-ground-contact-gate-host-bridge.md` before any of
this was built.** This closes out the whole Phase 8 plan; Task 9 was the
last remaining item and was explicitly optional throughout.

### Step 0: why this is not a second Renode machine

The plan's Task 9 text names Renode's "Wireless plugin" for a second
simulated node. Checked directly against this project's actual board model
before building anything: every Renode multi-node example built on an RF
medium (`/opt/renode/scripts/multi-node/efr32xg24-twonode_demo.resc`,
`nrf52840-ble-zephyr.resc`) requires each machine's platform description to
expose a `sysbus.radio` peripheral. `platforms/cpus/stm32f4.repl` — the
platform this project's single Renode node already loads — has none
(confirmed by grep: zero matches for `radio`/`Medium`/`sysbus.radio`), and
this project's Global Constraints keep RF hardware selection out of scope
throughout. A literal RF-medium two-node setup would
require inventing a radio subsystem this satellite was never designed to
carry — infeasible without contradicting this project's own scope.

Went further before concluding that's a dead end: Renode also ships
non-RF multi-node examples (`nrf52840-ble-hci-uart-zephyr.resc`,
`imxrt500_nrf52840_pigweed_bt_advertiser.resc`) that wire two machines'
UARTs together via `emulation CreateUARTHub` + `connector Connect`, no
radio medium at all — so a real two-`mach create`d-machine setup is
technically buildable in Renode. It was still not chosen: the plan's own
Global Constraints forbid an independently-authored contact-window
computation running on-device, which means a second node's firmware could
never be more than a "dumb relay" mechanically echoing a decision made
100% host-side — and this project has never modeled ground-station
hardware anywhere in its architecture (the "ground station" in every prior
task is the host bridge script talking to real Phase 7B host-side math).
Inventing a relay-MCU stand-in for a ground station, solely so two Renode
machines exist, is the same category of problem as the RF medium: a
fictional device invented to check a box. Full reasoning, including the
Renode commands checked, is in `docs/decisions/0008-*.md`.

**Decision taken:** keep the single satellite Renode node
(`mcu/renode/nucleo_f401re.resc`, unmodified). Extend the host bridge
itself — already this project's real stand-in for the ground segment in
every prior task's UART-bridge framing — with a contact-window gate.

### What was built

- `mcu/host_bridge/ground_contact_gate.py` — `compute_contact_windows()`
  calls the real, trusted `sim.orbit.find_passes()` directly against
  `sim.scenario.GROUND_STATIONS_DUAL` (config C's own reference scenario,
  per `docs/decisions/0006-config-c-generality-axis.md`) for the actual
  AOS/LOS contact-window computation — no independently-authored orbital
  math. `simulated_time_to_utc()` reuses `sim.driver._epoch_datetime()`
  (the same private helper `run_simulation()`'s own tick loop uses) so
  simulated seconds map to the same UTC epoch the rest of this codebase
  already uses. `GroundContactGate.send_gated_inject()` refuses to write a
  ground-sourced `INJECT` to the real UART unless `now` falls inside a real
  precomputed window (a plain `aos <= now <= los` membership test on
  `find_passes()`'s own output — not a new predicate), optionally signing
  with the real `engine.auth.sign_command()` when a ground-auth secret is
  configured (config C / `ENGINE_GROUND_AUTH_ENABLED`, Task 5).
- `mcu/host_bridge/verify_ground_contact_gate.py` — end-to-end
  demonstration/verification script, config-C build with
  `ENGINE_GROUND_AUTH_ENABLED=ON` (Task 5's build convention and
  test-harness secret), one continuous Renode session, four cases against
  `T-14` (config C: `from: "*"`, event `E-13` UPLINK_CMD_GENERIC,
  `source: ground`, guard: null, `to: null` — a self-transition, config
  C's generic ground command):
  1. **Gated, outside a real window → refused.** The gate computes real
     windows via `find_passes()`, finds `now` outside all of them, and
     writes nothing to the UART.
  2. **Proof of (1): zero bytes reached the wire.** A follow-up read with a
     short timeout finds no pending response line.
  3. **Same command, same out-of-window `now`, gate bypassed directly** (a
     raw `UartBridge.send_inject()` call) **→ succeeds** (`legal=1`) —
     proving the block in (1) is a ground-segment timing policy the gate
     adds, not something the firmware itself enforces. The firmware has no
     orbit/clock model at all, and nothing here claims otherwise — that is
     correctly a ground-segment responsibility, exactly like a real
     satellite does not reject a validly authenticated uplinked command
     because it independently suspects it isn't currently over a ground
     station.
  4. **Gated, inside a real window → transmitted and succeeds**, over the
     real Renode-simulated UART round trip, with a real HMAC-SHA256
     signature.

### What was run and the result

```
$ .venv/bin/python3 mcu/host_bridge/verify_ground_contact_gate.py
config-c link_quality_min_elevation_deg = 10.0 deg (real config parameter, not hardcoded here)
real contact windows (first 21600s, epoch=2025-01-21T21:45:38.676096):
  window[0]: aos=160s los=530s max_el=26.91 deg
  window[1]: aos=5940s los=6170s max_el=13.72 deg
chosen inside_s=345 (mid window[0]), outside_s=3235 (mid gap between window[0]/window[1])
[OK] case A: gate refused -- no real Phase 7B contact window covers now=3235s (2025-01-21T22:39:33.676096) -- refusing to transmit 'E-13', nothing written to the UART
[OK] case B: no response line arrived after the gate's refusal -- confirms zero bytes reached the firmware
[OK] case C: same command, same out-of-window time, gate BYPASSED directly -- firmware accepts it (no on-device timing model): Decision(now=3235.0, from_state='S-04', event_id='E-13', to_state='S-04', transition_id='T-14', legal=True, actions=('log_command_received', 'start_ground_contact_timer'))
[OK] case D: gate transmitted -- now=345s (2025-01-21T21:51:23.676096) falls inside real contact window [2025-01-21T21:48:18.676096, 2025-01-21T21:54:28.676096] (max elevation 26.91 deg) -- transmitted
[OK] case D: gated INJECT inside a real contact window, over the real Renode UART round trip: Decision(now=345.0, from_state='S-04', event_id='E-13', to_state='S-04', transition_id='T-14', legal=True, actions=('log_command_received', 'start_ground_contact_timer'))

All 4 contact-gate cases passed over a real Renode-simulated UART round trip: ...
```

**Run twice for reproducibility** (this project's established Renode
verification discipline — Tasks 1/4/5/6/7/8): both runs produced identical
pass/fail results and identical real contact-window data (deterministic
SGP4 propagation over a fixed TLE — no randomness anywhere in this path).

The real contact windows above are genuinely computed, not hand-picked:
`window[0]`/`window[1]` are `sim.orbit.find_passes()`'s actual output for
POQUITO's real reference TLE against `GROUND_STATIONS_DUAL` (Mumbai +
Svalbard) at config C's real 10° minimum-elevation mask, over the first 6
simulated hours from the TLE epoch.

### Regenerate

```
.venv/bin/python3 mcu/host_bridge/verify_ground_contact_gate.py
```

(Same top-level-`.venv` dependency note as `replay_baseline.py` — needs
`sim`/`engine`'s runtime deps and `pyserial` in the same interpreter.)

### What this does not claim

Same non-goals as the rest of Phase 8: no RF architecture (frequency,
antenna, ground-network selection are still out of scope), no physical
hardware, no power measurement. The "two-node" framing in the plan's Task 9
text is intentionally not literal here — see `docs/decisions/0008-*.md` for
why a second Renode machine was rejected in favor of this host-bridge gate,
and why that is a genuine, not a contrived, fix for the actual problem
(“the host bridge can send `INJECT` at any simulated time regardless of
pass geometry”).

## Later tasks

Tasks 2–9 (config codegen through the scheduler.py port, the finalized
UART protocol, the full seed=42 baseline equivalence run, and the
contact-window-gated ground command stretch goal) are all complete — see
this file's protocol reference / Task 8 / Task 9 sections
above. **Phase 8 (all 9 tasks, including the optional Task 9 stretch) is
now fully closed out.**
