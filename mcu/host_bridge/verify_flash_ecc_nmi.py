#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcu.host_bridge.firmware_build import build_firmware_for_config, restore_committed_config_a_table  # noqa: E402
from mcu.host_bridge.measure_firmware import Monitor  # noqa: E402
from mcu.host_bridge.uart_bridge import Decision, Raw, RenodeSession, UartBridge, UartBridgeError  # noqa: E402
from mcu.host_bridge.verify_persistence_ab_bank import (  # noqa: E402
    BANK_A_FLASH_ADDRESS,
    BANK_B_FLASH_ADDRESS,
    _testhook,
)

MONITOR_PORT = 9701
FLASH_BASE = 0x08000000
INJECT_ECC_REGISTER = 0x40022000 + 0x3FC
FLASH_ECCR = 0x40022018
ECCD = 1 << 31
BK_ECC = 1 << 19
SYSF_ECC = 1 << 20
CODE_OFFSET = 0x1000


def eccr_for(address: int, extra: int = 0) -> int:
    offset = address - FLASH_BASE
    return ECCD | extra | (offset & 0x7FFFF) | (BK_ECC if offset >= 0x80000 else 0)


def check(condition: bool, label: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {label}")
    print(f"[OK] {label}", file=sys.stderr)


def word(monitor: Monitor, address: int) -> int:
    reply = monitor.send(f"sysbus ReadDoubleWord {address:#x}")
    return int(reply.split("0x")[-1].split()[0], 16)


def inject(monitor: Monitor, value: int) -> None:
    monitor.send(f"sysbus WriteDoubleWord {INJECT_ECC_REGISTER:#x} {value:#x}")
    time.sleep(0.5)


def write_both_banks(bridge: UartBridge) -> None:
    for event, state, now, context in (
        ("E-02", "S-02", 2000, {"rf_inhibit_timer": 0}),
        ("E-04", "S-03", 2000, {"path_a_confirmed": True}),
        ("E-19", "S-04", 2001, {"deployment_confirmed": True}),
    ):
        bridge.send_inject(event, state, now, context, {})
        check(isinstance(bridge.read_response(), Decision), f"{event} accepted")


def expect_load(bridge: UartBridge, label: str) -> None:
    response = _testhook(bridge, "TESTHOOK LOAD")
    check(isinstance(response, Raw) and response.text == "OK state=S-05 deployment_confirmed=1", f"{label}: {response!r}")


def repair(bridge: UartBridge) -> None:
    bridge.send_inject("E-19", "S-04", 2001, {"deployment_confirmed": True}, {})
    check(isinstance(bridge.read_response(), Decision), "unchanged save repairs the erased bank")


def expect_hung(bridge: UartBridge, label: str) -> None:
    bridge._ser.write(b"TESTHOOK LOAD\n")  # noqa: SLF001
    bridge._ser.flush()  # noqa: SLF001
    try:
        response = bridge.read_response(timeout_s=3.0)
    except (UartBridgeError, TimeoutError):
        response = None
    check(response is None, f"{label}: firmware stopped ({response!r})")


def main() -> int:
    if os.environ.get("CEPDT_BOARD") != "nucleo_l476rg":
        raise SystemExit("set CEPDT_BOARD=nucleo_l476rg")
    elf = build_firmware_for_config(
        "config-a",
        build_dir_name="config-a-eccnmi",
        extra_west_args=["--", "-DCEPDT_ENGINE_PERSIST_TESTHOOKS_ENABLED=ON"],
    )
    pty = "/tmp/cepdt_nucleo_l476rg_uart_eccnmi"
    with RenodeSession(elf, uart_pty=pty, monitor_port=MONITOR_PORT):
        with UartBridge(pty) as bridge:
            bridge.wait_for_ready()
            monitor = Monitor(MONITOR_PORT)
            write_both_banks(bridge)

            inject(monitor, eccr_for(BANK_B_FLASH_ADDRESS + 0x40))
            check(word(monitor, BANK_B_FLASH_ADDRESS) == 0xFFFFFFFF, "bank B fault: page erased")
            check(word(monitor, FLASH_ECCR) & ECCD == 0, "bank B fault: ECCD cleared")
            check(word(monitor, BANK_A_FLASH_ADDRESS) != 0xFFFFFFFF, "bank B fault: bank A untouched")
            expect_load(bridge, "bank B fault: LOAD from bank A")
            repair(bridge)

            inject(monitor, eccr_for(BANK_A_FLASH_ADDRESS + 0x7F8))
            check(word(monitor, BANK_A_FLASH_ADDRESS) == 0xFFFFFFFF, "bank A fault, last double-word: page erased")
            check(word(monitor, BANK_B_FLASH_ADDRESS) != 0xFFFFFFFF, "bank A fault: bank B untouched")
            expect_load(bridge, "bank A fault: LOAD from bank B")

    code = FLASH_BASE + CODE_OFFSET
    for label, value in (
        ("code-flash fault", eccr_for(code)),
        ("NMI without ECCD", 0),
        ("system-flash fault", eccr_for(BANK_A_FLASH_ADDRESS, SYSF_ECC)),
        ("address just below bank A", eccr_for(BANK_A_FLASH_ADDRESS - 8)),
        ("address just above bank B", eccr_for(BANK_B_FLASH_ADDRESS + 0x800)),
    ):
        with RenodeSession(elf, uart_pty=pty, monitor_port=MONITOR_PORT):
            with UartBridge(pty) as bridge:
                bridge.wait_for_ready()
                monitor = Monitor(MONITOR_PORT)
                write_both_banks(bridge)
                code_word = word(monitor, code)
                banks = word(monitor, BANK_A_FLASH_ADDRESS), word(monitor, BANK_B_FLASH_ADDRESS)
                inject(monitor, value)
                expect_hung(bridge, label)
                check(word(monitor, code) == code_word, f"{label}: code flash not erased")
                check(
                    (word(monitor, BANK_A_FLASH_ADDRESS), word(monitor, BANK_B_FLASH_ADDRESS)) == banks,
                    f"{label}: banks untouched",
                )
    print("\nAll ECC NMI cases passed on the simulated L476.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        restore_committed_config_a_table()
