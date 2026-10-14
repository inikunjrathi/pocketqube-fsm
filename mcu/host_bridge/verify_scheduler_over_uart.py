from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
HOST_C_UNIT_DIR = REPO_ROOT / "mcu" / "firmware" / "app" / "tests" / "host_c_unit"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(HOST_C_UNIT_DIR))

from engine.scheduler import Scheduler  # noqa: E402

from mcu.host_bridge.firmware_build import (  # noqa: E402
    build_firmware_for_config,
    restore_committed_config_a_table,
)
from mcu.host_bridge.uart_bridge import (  # noqa: E402
    Raw,
    RenodeSession,
    UartBridge,
    UartBridgeError,
)

import run_scheduler_equivalence as rse  # noqa: E402

class SchedulerUartVerificationError(Exception):
    pass

class UartSchedulerDriver:

    def __init__(self, bridge: UartBridge) -> None:
        self._bridge = bridge

    def _send(self, line: str) -> str:
        self._bridge._ser.write((line + "\n").encode("ascii"))  # noqa: SLF001
        self._bridge._ser.flush()  # noqa: SLF001
        response = self._bridge.read_response()
        if isinstance(response, Raw):
            return response.text
        from mcu.host_bridge.uart_bridge import Error

        if isinstance(response, Error):
            return f"ERROR {response.reason}" + (f" {response.detail}" if response.detail else "")
        raise SchedulerUartVerificationError(f"unexpected response to {line!r}: {response!r}")

    def reset(self, priority: list) -> None:
        reply = self._send("TESTHOOK SCHED RESET " + ",".join(priority))
        if reply != "OK":
            raise SchedulerUartVerificationError(f"TESTHOOK SCHED RESET failed: {reply!r}")

    def apply(self, op) -> "rse.OpResult":
        OpResult = rse.OpResult
        if isinstance(op, rse.InsertOp):
            item = op.item
            deadline_tok = "NONE" if item.deadline is None else repr(item.deadline)
            reply = self._send(
                f"TESTHOOK SCHED INSERT {item.id} {item.data_class} {item.size_bytes} {deadline_tok}"
            )
            if reply == "OK":
                return OpResult("ok", None)
            if reply.startswith("ERROR sched_unknown_class"):
                return OpResult("error", "sched_unknown_class")
            if reply == "ERROR sched_queue_full":
                return OpResult("error", "sched_queue_full")
            raise SchedulerUartVerificationError(f"unexpected INSERT reply: {reply!r}")
        if isinstance(op, rse.SelectOp):
            reply = self._send("TESTHOOK SCHED SELECT_EDF" if op.edf else "TESTHOOK SCHED SELECT")
            if reply == "OK NONE":
                return OpResult("item_or_none", None)
            return OpResult("item_or_none", rse._parse_field(reply, "id", label="SELECT"))
        if isinstance(op, rse.PeekClassOp):
            reply = self._send("TESTHOOK SCHED PEEK_CLASS")
            if reply == "OK NONE":
                return OpResult("class_or_none", None)
            return OpResult("class_or_none", rse._parse_field(reply, "data_class", label="PEEK_CLASS"))
        if isinstance(op, rse.CandidatesOp):
            reply = self._send("TESTHOOK SCHED CANDIDATES")
            classes_str = rse._parse_field(reply, "classes", label="CANDIDATES")
            return OpResult("class_list", () if classes_str == "NONE" else tuple(classes_str.split(",")))
        if isinstance(op, rse.IsEmptyOp):
            reply = self._send("TESTHOOK SCHED IS_EMPTY")
            empty_str = rse._parse_field(reply, "empty", label="IS_EMPTY")
            return OpResult("bool", empty_str == "1")
        if isinstance(op, rse.AllItemsOp):
            reply = self._send("TESTHOOK SCHED ALL_ITEMS")
            ids_str = rse._parse_field(reply, "ids", label="ALL_ITEMS")
            return OpResult("id_set", frozenset() if ids_str == "NONE" else frozenset(ids_str.split(",")))
        raise SchedulerUartVerificationError(f"unhandled op type: {op!r}")

def run_scenario_over_uart(driver: UartSchedulerDriver, scenario, *, verbose: bool) -> list:
    sched = Scheduler(list(scenario.priority))
    driver.reset(list(scenario.priority))

    mismatches = []
    for i, op in enumerate(scenario.ops):
        py_result = rse.apply_python(sched, op)
        uart_result = driver.apply(op)
        if isinstance(op, rse.InsertExpectFullOp):
            match = uart_result == rse.OpResult("error", "sched_queue_full")
        else:
            match = py_result == uart_result
        if verbose:
            status = "OK" if match else "MISMATCH"
            print(f"[{status}] {scenario.name}[{i}] {op!r}: python={py_result} uart={uart_result}", file=sys.stderr)
        if not match:
            mismatches.append(rse.StepMismatch(scenario.name, i, op, py_result, uart_result))
    return mismatches

def run(
    *,
    west: Optional[Path] = None,
    zephyr_sdk_dir: Optional[Path] = None,
    zephyr_base: Optional[Path] = None,
    verbose: bool = False,
) -> int:
    elf = build_firmware_for_config(
        "config-a",
        west=west,
        zephyr_sdk_dir=zephyr_sdk_dir,
        zephyr_base=zephyr_base,
        build_dir_name="config-a-schedtest",
        extra_west_args=["--", "-DCEPDT_ENGINE_SCHED_TESTHOOKS_ENABLED=ON"],
    )

    pty = "/tmp/cepdt_nucleo_f401re_uart_schedtest"
    monitor_port = 9701
    scenarios = rse.build_scenarios()

    with RenodeSession(elf, uart_pty=pty, monitor_port=monitor_port) as _session:
        with UartBridge(pty) as bridge:
            bridge.wait_for_ready()
            driver = UartSchedulerDriver(bridge)

            all_mismatches = []
            total_steps = 0
            for scenario in scenarios:
                mismatches = run_scenario_over_uart(driver, scenario, verbose=verbose)
                all_mismatches.extend(mismatches)
                total_steps += len(scenario.ops)
                print(f"{scenario.name}: {len(scenario.ops)} steps, {len(mismatches)} mismatches", file=sys.stderr)

    print(
        f"\nTOTAL (over real Renode-simulated UART): {len(scenarios)} scenarios, "
        f"{total_steps} steps, {len(all_mismatches)} mismatches",
        file=sys.stderr,
    )
    if all_mismatches:
        print("\nFailing steps:", file=sys.stderr)
        for m in all_mismatches:
            print(f"  {m.scenario}[{m.step_index}] {m.op!r}: python={m.python_result} uart={m.c_result}", file=sys.stderr)
        return 1

    print(
        "All TESTHOOK SCHED results, replayed over a real Renode-simulated "
        "UART round trip, match engine.scheduler.Scheduler exactly.",
        file=sys.stderr,
    )
    return 0

def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--west", default=None)
    parser.add_argument("--zephyr-sdk-dir", default=None)
    parser.add_argument("--zephyr-base", default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    try:
        return run(
            west=Path(args.west) if args.west else None,
            zephyr_sdk_dir=Path(args.zephyr_sdk_dir) if args.zephyr_sdk_dir else None,
            zephyr_base=Path(args.zephyr_base) if args.zephyr_base else None,
            verbose=args.verbose,
        )
    except (UartBridgeError, SchedulerUartVerificationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        restore_committed_config_a_table()

if __name__ == "__main__":
    raise SystemExit(main())
