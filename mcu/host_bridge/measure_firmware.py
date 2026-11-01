#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.config_loader import load_config  # noqa: E402
from mcu.host_bridge.firmware_build import build_firmware_for_config, restore_committed_config_a_table  # noqa: E402
from mcu.host_bridge.replay_baseline import (  # noqa: E402
    CONFIG_PATHS,
    _replay_service_group,
    capture_baseline_trace,
    diff_trace_results,
)
from mcu.host_bridge.uart_bridge import RenodeSession, UartBridge  # noqa: E402

MONITOR_PORT = 9720
FUNCTIONS = {
    "step": "engine_fsm_step",
    "load": "engine_persistence_load",
    "save": "engine_persistence_save",
    "bank_write": "engine_persist_io_write",
}
LOG_LINE = re.compile(r"CEPDT ([io]) (\w+) (\d+)")


def _tool(name: str) -> str:
    sdk = os.environ["ZEPHYR_SDK_INSTALL_DIR"]
    return f"{sdk}/arm-zephyr-eabi/bin/arm-zephyr-eabi-{name}"


def _run(*command: str) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


def hook_addresses(elf: Path) -> dict[str, tuple[int, list[int]]]:
    symbols = {
        fields[2]: int(fields[0], 16) & ~1
        for fields in (line.split() for line in _run(_tool("nm"), str(elf)).splitlines())
        if len(fields) == 3
    }
    disassembly = _run(_tool("objdump"), "-d", str(elf))
    hooks = {}
    for label, symbol in FUNCTIONS.items():
        calls = re.findall(rf"^\s*([0-9a-f]+):.*\sbl\s+[0-9a-f]+ <{symbol}>", disassembly, re.M)
        tail_calls = re.findall(rf"\sb(?:\.w|\.n)?\s+[0-9a-f]+ <{symbol}>", disassembly)
        if tail_calls or not calls:
            raise SystemExit(f"{symbol}: {len(calls)} calls, {len(tail_calls)} tail calls; cannot hook returns")
        hooks[label] = (symbols[symbol], [int(address, 16) + 4 for address in calls])
    return hooks


class Monitor:
    def __init__(self, port: int) -> None:
        self._sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self._sock.settimeout(0.3)
        self._drain()

    def _drain(self) -> str:
        output = b""
        try:
            while chunk := self._sock.recv(65536):
                output += chunk
        except socket.timeout:
            pass
        return output.decode(errors="replace")

    def send(self, command: str) -> str:
        self._sock.sendall(command.encode() + b"\n")
        return self._drain()


def install_hooks(monitor: Monitor, hooks: dict[str, tuple[int, list[int]]]) -> None:
    def code(kind: str, label: str) -> str:
        return f"self.Log(LogLevel.Warning, 'CEPDT {kind} {label} %d' % self.ExecutedInstructions)"

    for label, (entry, returns) in hooks.items():
        monitor.send(f'cpu AddHook {entry:#x} "{code("i", label)}"')
        for address in returns:
            monitor.send(f'cpu AddHook {address:#x} "{code("o", label)}"')


def interrupt_stack(elf: Path) -> tuple[int, int]:
    for line in _run(_tool("nm"), "-S", str(elf)).splitlines():
        fields = line.split()
        if len(fields) == 4 and fields[3] == "z_interrupt_stacks":
            return int(fields[0], 16), int(fields[1], 16)
    raise SystemExit("z_interrupt_stacks not found")


def stack_peak(monitor: Monitor, base: int, size: int) -> int:
    for address in range(base, base + size, 8):
        quad = re.findall(r"0x[0-9A-Fa-f]{16}\b", monitor.send(f"sysbus ReadQuadWord {address:#x}"))
        if any(int(value, 16) for value in quad):
            return size - (address - base)
    return 0


def replay(bridge: UartBridge, trace, groups) -> list:
    results: list = []
    by_start = {group.start: group for group in groups}
    while len(results) < len(trace):
        entry = trace[len(results)]
        group = by_start.get(entry.index)
        if group is not None and entry.index + group.count <= len(trace):
            results += _replay_service_group(bridge, trace[entry.index:entry.index + group.count], group)
        else:
            bridge.send_inject(entry.event_id, entry.from_state, entry.now, entry.context, entry.telemetry)
            results.append((entry, bridge.read_response()))
    return results


def spans(log_text: str) -> dict[str, list[tuple[int, int]]]:
    open_at: dict[str, int] = {}
    pairs: dict[str, list[tuple[int, int]]] = {label: [] for label in FUNCTIONS}
    for kind, label, count in LOG_LINE.findall(log_text):
        if kind == "i":
            open_at[label] = int(count)
        elif label in open_at:
            pairs[label].append((open_at.pop(label), int(count)))
    return pairs


def summarise(pairs: dict[str, list[tuple[int, int]]]) -> dict:
    def durations(label: str) -> list[int]:
        return [end - start for start, end in pairs[label]]

    def writes_inside(start: int, end: int) -> int:
        return sum(start <= begin < end for begin, _ in pairs["bank_write"])

    saves_by_writes: dict[int, list[int]] = {}
    for start, end in pairs["save"]:
        saves_by_writes.setdefault(writes_inside(start, end), []).append(end - start)

    def describe(values: list[int]) -> dict:
        return {"count": len(values), "median": statistics.median(values), "max": max(values)}

    return {
        "step": describe(durations("step")),
        "load": describe(durations("load")),
        "save": describe(durations("save")),
        "saves_by_bank_writes": {str(k): describe(v) for k, v in sorted(saves_by_writes.items())},
        "bank_writes": len(pairs["bank_write"]),
    }


def footprint(elf: Path) -> dict:
    sizes = {}
    for line in _run(_tool("nm"), "-S", str(elf)).splitlines():
        fields = line.split()
        if len(fields) == 4:
            sizes[fields[3]] = int(fields[1], 16)
    text, data, bss = map(int, _run(_tool("size"), str(elf)).splitlines()[1].split()[:3])
    table_object = next(elf.parents[1].rglob("engine_config_table.c.obj"))
    table_text, table_data = map(int, _run(_tool("size"), str(table_object)).splitlines()[1].split()[:2])
    return {
        "flash_text_plus_data": text + data,
        "ram_data_plus_bss": data + bss,
        "config_table_object": table_text + table_data,
        "symbols": {
            name: size
            for name, size in sizes.items()
            if name.startswith(("g_transitions", "engine_fsm_step", "engine_guard", "engine_persist", "engine_arbit"))
            or name == "z_interrupt_stacks"
        },
    }


def measure(config_id: str, limit: int | None = None) -> dict:
    cfg = load_config(CONFIG_PATHS[config_id])
    trace, _result, groups = capture_baseline_trace(cfg, seed=42, duration_s=172800.0, dt_s=10.0)
    trace = trace[:limit]
    elf = build_firmware_for_config(config_id)
    hooks = hook_addresses(elf)
    stack_base, stack_size = interrupt_stack(elf)
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "renode.log"
        pty = f"{tmp}/uart"
        with RenodeSession(elf, uart_pty=pty, monitor_port=MONITOR_PORT, log_path=log_path):
            with UartBridge(pty) as bridge:
                bridge.wait_for_ready()
                monitor = Monitor(MONITOR_PORT)
                install_hooks(monitor, hooks)
                monitor.send("pause")
                monitor.send(f"sysbus ZeroRange {stack_base:#x} {stack_size:#x}")
                monitor.send("start")
                results = replay(bridge, trace, groups)
                monitor.send("pause")
                peak = stack_peak(monitor, stack_base, stack_size)
        time.sleep(1)
        log_text = log_path.read_text(errors="replace")
    outcomes = diff_trace_results(results)
    return {
        "config": config_id,
        "board": os.environ.get("CEPDT_BOARD", "nucleo_f401re"),
        "calls": len(results),
        "mismatches": sum(not outcome.match for outcome in outcomes),
        "instructions": summarise(spans(log_text)),
        "interrupt_stack_peak_bytes": peak,
        "interrupt_stack_bytes": stack_size,
        "footprint": footprint(elf),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", choices=sorted(CONFIG_PATHS), default="config-a")
    parser.add_argument("--limit", type=int, default=None, help="replay only the first N calls (smoke test)")
    args = parser.parse_args()
    try:
        print(json.dumps(measure(args.config, args.limit), indent=2))
    finally:
        restore_committed_config_a_table()
    return 0


if __name__ == "__main__":
    sys.exit(main())
