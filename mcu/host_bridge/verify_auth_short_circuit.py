from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from engine.auth import sign_command  # noqa: E402

from mcu.host_bridge.firmware_build import (  # noqa: E402
    build_firmware_for_config,
    restore_committed_config_a_table,
)
from mcu.host_bridge.uart_bridge import (  # noqa: E402
    Decision,
    RenodeSession,
    UartBridge,
    UartBridgeError,
)

TEST_HARNESS_SECRET = b"phase8-task5-test-harness-secret-do-not-use-in-flight"

BAD_SIGNATURE = "0" * 64

class AuthVerificationError(Exception):
    pass

def _expect_decision(response, *, legal: bool, to_state: str, transition_id: Optional[str], label: str) -> None:
    if not isinstance(response, Decision):
        raise AuthVerificationError(f"{label}: expected a DECISION line, got {response!r}")
    if response.legal != legal:
        raise AuthVerificationError(f"{label}: expected legal={legal!r}, got {response.legal!r} ({response!r})")
    if response.to_state != to_state:
        raise AuthVerificationError(
            f"{label}: expected to_state={to_state!r}, got {response.to_state!r} ({response!r})"
        )
    if response.transition_id != transition_id:
        raise AuthVerificationError(
            f"{label}: expected transition={transition_id!r}, got {response.transition_id!r} ({response!r})"
        )
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
        build_dir_name="config-a-authtest",
        extra_west_args=["--", "-DCEPDT_ENGINE_GROUND_AUTH_ENABLED=ON"],
    )

    pty = "/tmp/cepdt_nucleo_f401re_uart_authtest"
    with RenodeSession(elf, uart_pty=pty) as _session:
        with UartBridge(pty) as bridge:
            bridge.wait_for_ready()

            bridge.send_inject("E-13", "S-03", 0, {}, {}, signature=BAD_SIGNATURE)
            _expect_decision(
                bridge.read_response(),
                legal=False, to_state="S-03", transition_id=None,
                label="case 1: T-17 with a wrong (but well-formed) signature",
            )

            bridge.send_inject("E-13", "S-03", 0, {}, {})
            _expect_decision(
                bridge.read_response(),
                legal=False, to_state="S-03", transition_id=None,
                label="case 2: T-17 with no signature at all",
            )

            correct_sig = sign_command("E-13", 0.0, TEST_HARNESS_SECRET)
            bridge.send_inject("E-13", "S-03", 0, {}, {}, signature=correct_sig)
            _expect_decision(
                bridge.read_response(),
                legal=True, to_state="S-10", transition_id="T-17",
                label="case 3: T-17 with the correct signature",
            )

            bridge.send_inject("E-01", "S-01", 0, {}, {})
            _expect_decision(
                bridge.read_response(),
                legal=True, to_state="S-02", transition_id="T-01",
                label="case 4 (control): T-01 (onboard-sourced), no signature, unaffected",
            )

    print(
        "\nAll 4 auth-short-circuit re-verification cases passed over a real "
        "Renode-simulated UART round trip.",
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
    except (UartBridgeError, AuthVerificationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        restore_committed_config_a_table()

if __name__ == "__main__":
    raise SystemExit(main())
