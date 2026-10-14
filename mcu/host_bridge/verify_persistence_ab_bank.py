from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from mcu.host_bridge.firmware_build import (  # noqa: E402
    build_firmware_for_config,
    restore_committed_config_a_table,
)
from mcu.host_bridge.uart_bridge import (  # noqa: E402
    Decision,
    Raw,
    RenodeSession,
    UartBridge,
    UartBridgeError,
)

MONITOR_COMMAND_TIMEOUT_S = 5.0
POST_RESET_READY_TIMEOUT_S = 20.0

class PersistenceVerificationError(Exception):
    pass

def _monitor_reset(monitor_port: int) -> None:
    with socket.create_connection(("127.0.0.1", monitor_port), timeout=MONITOR_COMMAND_TIMEOUT_S) as sock:
        sock.settimeout(MONITOR_COMMAND_TIMEOUT_S)

        def _drain() -> bytes:
            chunk_total = b""
            try:
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    chunk_total += chunk
            except socket.timeout:
                pass
            return chunk_total

        def _send(command: bytes) -> bytes:
            sock.sendall(command + b"\n")
            return _drain()

        _drain()
        _send(b"pause")
        _send(b"runMacro $reset")
        _send(b"cpu Reset")
        _send(b"start")

def _testhook(bridge: UartBridge, command: str):
    bridge._ser.write((command + "\n").encode("ascii"))  # noqa: SLF001 -- see note below
    bridge._ser.flush()  # noqa: SLF001
    return bridge.read_response()

def _expect_decision(response, *, legal: bool, to_state: str, transition_id: Optional[str], label: str) -> None:
    if not isinstance(response, Decision):
        raise PersistenceVerificationError(f"{label}: expected a DECISION line, got {response!r}")
    if response.legal != legal:
        raise PersistenceVerificationError(f"{label}: expected legal={legal!r}, got {response.legal!r} ({response!r})")
    if response.to_state != to_state:
        raise PersistenceVerificationError(
            f"{label}: expected to_state={to_state!r}, got {response.to_state!r} ({response!r})"
        )
    if response.transition_id != transition_id:
        raise PersistenceVerificationError(
            f"{label}: expected transition={transition_id!r}, got {response.transition_id!r} ({response!r})"
        )
    print(f"[OK] {label}: {response!r}", file=sys.stderr)

def _expect_load(response, *, state: str, deployment_confirmed: bool, label: str) -> None:
    expected_text = f"OK state={state} deployment_confirmed={1 if deployment_confirmed else 0}"
    if not isinstance(response, Raw) or response.text != expected_text:
        raise PersistenceVerificationError(f"{label}: expected {expected_text!r}, got {response!r}")
    print(f"[OK] {label}: {response!r}", file=sys.stderr)

def run(
    *,
    west: Optional[Path] = None,
    zephyr_sdk_dir: Optional[Path] = None,
    zephyr_base: Optional[Path] = None,
) -> int:
    elf = build_firmware_for_config(
        "config-a",
        west=west,
        zephyr_sdk_dir=zephyr_sdk_dir,
        zephyr_base=zephyr_base,
        build_dir_name="config-a-persisttest",
        extra_west_args=["--", "-DCEPDT_ENGINE_PERSIST_TESTHOOKS_ENABLED=ON"],
    )

    pty = "/tmp/cepdt_nucleo_f401re_uart_persisttest"
    monitor_port = 9700
    with RenodeSession(elf, uart_pty=pty, monitor_port=monitor_port) as _session:
        with UartBridge(pty) as bridge:
            bridge.wait_for_ready()

            bridge.send_inject("E-02", "S-02", 2000, {"rf_inhibit_timer": 0}, {})
            _expect_decision(
                bridge.read_response(),
                legal=True, to_state="S-03", transition_id="T-02",
                label="step 1: T-02 (save -> bank A)",
            )

            bridge.send_inject("E-04", "S-03", 2000, {"path_a_confirmed": True}, {})
            _expect_decision(
                bridge.read_response(),
                legal=True, to_state="S-04", transition_id="T-06",
                label="step 2: T-06 (save -> bank B, sets deployment_confirmed)",
            )

            bridge.send_inject("E-19", "S-04", 2001, {"deployment_confirmed": True}, {})
            _expect_decision(
                bridge.read_response(),
                legal=True, to_state="S-05", transition_id="T-07",
                label="step 3: T-07 (save -> bank A, now the more-recent bank)",
            )

            _expect_load(
                _testhook(bridge, "TESTHOOK LOAD"),
                state="S-05", deployment_confirmed=True,
                label="step 4: pre-corruption LOAD (bank A, highest sequence, wins)",
            )

            corrupt_response = _testhook(bridge, "TESTHOOK CORRUPT B")
            if not isinstance(corrupt_response, Raw) or corrupt_response.text != "OK":
                raise PersistenceVerificationError(f"step 5: TESTHOOK CORRUPT B failed: {corrupt_response!r}")
            print(f"[OK] step 5: TESTHOOK CORRUPT B: {corrupt_response!r}", file=sys.stderr)

            bridge.send_inject("E-04", "S-03", 2002, {"path_a_confirmed": True}, {})
            _expect_decision(
                bridge.read_response(),
                legal=True, to_state="S-04", transition_id="T-06",
                label="step 6: T-06 again (re-save -> bank B)",
            )

            _expect_load(
                _testhook(bridge, "TESTHOOK LOAD"),
                state="S-04", deployment_confirmed=True,
                label="step 7: post-corruption LOAD, pre-reboot (bank B wins, latch survives)",
            )

            _monitor_reset(monitor_port)
            ready_line = bridge._read_line(timeout_s=POST_RESET_READY_TIMEOUT_S)  # noqa: SLF001
            if ready_line != "READY":
                raise PersistenceVerificationError(
                    f"step 8: expected READY after the CPU-level reset, got {ready_line!r}"
                )
            print("[OK] step 8: CPU-level reset (Renode process/flash preserved) -> READY", file=sys.stderr)

            _expect_load(
                _testhook(bridge, "TESTHOOK LOAD"),
                state="S-04", deployment_confirmed=True,
                label="step 9: post-reboot LOAD (unchanged -- flash genuinely survived)",
            )

            bridge.send_inject("E-16", "S-01", 3000, {}, {})
            _expect_decision(
                bridge.read_response(),
                legal=True, to_state="S-04", transition_id="T-22",
                label="step 10: T-22 (E-16 RESET) post-reboot resolves to the surviving bank",
            )

    print(
        "\nAll 10 save/corrupt/reboot/load steps passed over a real "
        "Renode-simulated UART round trip, reproducing the R-29 outcome: "
        "the older-but-valid bank wins after the other bank is "
        "corrupted, and the deployment_confirmed latch survives a real "
        "CPU-level reboot.",
        file=sys.stderr,
    )
    return 0

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--west", default=None)
    parser.add_argument("--zephyr-sdk-dir", default=None)
    parser.add_argument("--zephyr-base", default=None)
    args = parser.parse_args(argv)

    try:
        return run(
            west=Path(args.west) if args.west else None,
            zephyr_sdk_dir=Path(args.zephyr_sdk_dir) if args.zephyr_sdk_dir else None,
            zephyr_base=Path(args.zephyr_base) if args.zephyr_base else None,
        )
    except (UartBridgeError, PersistenceVerificationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        restore_committed_config_a_table()

if __name__ == "__main__":
    raise SystemExit(main())
