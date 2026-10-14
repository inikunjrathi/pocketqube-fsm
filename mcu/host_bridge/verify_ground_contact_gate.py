from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from engine.auth import sign_command  # noqa: E402
from engine.config_loader import load_config  # noqa: E402

from mcu.host_bridge.firmware_build import (  # noqa: E402
    build_firmware_for_config,
    restore_committed_config_a_table,
)
from mcu.host_bridge.ground_contact_gate import (  # noqa: E402
    GroundContactGate,
    compute_contact_windows,
)
from mcu.host_bridge.uart_bridge import (  # noqa: E402
    Decision,
    RenodeSession,
    UartBridge,
    UartBridgeError,
)

TEST_HARNESS_SECRET = b"phase8-task5-test-harness-secret-do-not-use-in-flight"

GROUND_EVENT_ID = "E-13"
REPRESENTATIVE_STATE_ID = "S-04"

DEMO_DURATION_S = 6.0 * 3600.0

class ContactGateVerificationError(Exception):
    pass

def _expect_decision(response, *, legal: bool, to_state: str, transition_id: Optional[str], label: str) -> None:
    if not isinstance(response, Decision):
        raise ContactGateVerificationError(f"{label}: expected a DECISION line, got {response!r}")
    if response.legal != legal:
        raise ContactGateVerificationError(f"{label}: expected legal={legal!r}, got {response.legal!r} ({response!r})")
    if response.to_state != to_state:
        raise ContactGateVerificationError(
            f"{label}: expected to_state={to_state!r}, got {response.to_state!r} ({response!r})"
        )
    if response.transition_id != transition_id:
        raise ContactGateVerificationError(
            f"{label}: expected transition={transition_id!r}, got {response.transition_id!r} ({response!r})"
        )
    print(f"[OK] {label}: {response!r}", file=sys.stderr)

def run(
    *,
    west: Optional[Path] = None,
    zephyr_sdk_dir: Optional[Path] = None,
    zephyr_base: Optional[Path] = None,
) -> int:
    cfg = load_config(REPO_ROOT / "config" / "config-c.yaml")
    params_by_name = {p.name: p.value for p in cfg.parameters.values()}
    min_elevation_deg = float(params_by_name["link_quality_min_elevation_deg"])
    print(
        f"config-c link_quality_min_elevation_deg = {min_elevation_deg} deg "
        "(real config parameter, not hardcoded here)",
        file=sys.stderr,
    )

    windows, epoch = compute_contact_windows(
        duration_s=DEMO_DURATION_S, min_elevation_deg=min_elevation_deg
    )
    if len(windows) < 2:
        raise ContactGateVerificationError(
            f"expected >=2 real contact windows in the first {DEMO_DURATION_S:.0f}s "
            f"for this demonstration to have a genuine 'between two passes' "
            f"out-of-window point; sim.orbit.find_passes() returned {len(windows)}. "
            "This is a property of the real reference orbit/ground stations, not "
            "a bug in this script -- widen DEMO_DURATION_S if this ever changes."
        )
    print(f"real contact windows (first {DEMO_DURATION_S:.0f}s, epoch={epoch.isoformat()}):", file=sys.stderr)
    for i, p in enumerate(windows):
        aos_s = (p.aos - epoch).total_seconds()
        los_s = (p.los - epoch).total_seconds()
        print(f"  window[{i}]: aos={aos_s:.0f}s los={los_s:.0f}s max_el={p.max_elevation_deg:.2f} deg", file=sys.stderr)

    first, second = windows[0], windows[1]
    inside_s = (first.aos - epoch).total_seconds() + (
        (first.los - first.aos).total_seconds() / 2.0
    )
    outside_s = (first.los - epoch).total_seconds() + (
        (second.aos - first.los).total_seconds() / 2.0
    )
    print(f"chosen inside_s={inside_s:.0f} (mid window[0]), outside_s={outside_s:.0f} (mid gap between window[0]/window[1])", file=sys.stderr)

    elf = build_firmware_for_config(
        "config-c",
        west=west,
        zephyr_sdk_dir=zephyr_sdk_dir,
        zephyr_base=zephyr_base,
        build_dir_name="config-c-task9-gate",
        extra_west_args=["--", "-DCEPDT_ENGINE_GROUND_AUTH_ENABLED=ON"],
    )

    pty = "/tmp/cepdt_nucleo_f401re_uart_task9_gate"
    with RenodeSession(elf, uart_pty=pty) as _session:
        with UartBridge(pty) as bridge:
            bridge.wait_for_ready()

            gate = GroundContactGate(
                bridge,
                windows=windows,
                epoch=epoch,
                ground_auth_secret=TEST_HARNESS_SECRET,
            )

            decision_a = gate.send_gated_inject(
                GROUND_EVENT_ID, REPRESENTATIVE_STATE_ID, outside_s, {}, {}
            )
            if decision_a.sent:
                raise ContactGateVerificationError(
                    f"case A: expected the gate to refuse at out-of-window now={outside_s}, "
                    f"but it sent (decision={decision_a!r})"
                )
            print(f"[OK] case A: gate refused -- {decision_a.reason}", file=sys.stderr)

            try:
                stray = bridge.read_response(timeout_s=1.5)
            except UartBridgeError:
                print("[OK] case B: no response line arrived after the gate's refusal -- confirms zero bytes reached the firmware", file=sys.stderr)
            else:
                raise ContactGateVerificationError(
                    f"case B: expected no response after the gate refused case A, "
                    f"but got {stray!r} -- the gate must not have actually blocked the write"
                )

            bypass_sig = sign_command(GROUND_EVENT_ID, float(outside_s), TEST_HARNESS_SECRET)
            bridge.send_inject(
                GROUND_EVENT_ID, REPRESENTATIVE_STATE_ID, outside_s, {}, {}, signature=bypass_sig
            )
            _expect_decision(
                bridge.read_response(),
                legal=True, to_state=REPRESENTATIVE_STATE_ID, transition_id="T-14",
                label="case C: same command, same out-of-window time, gate BYPASSED directly -- firmware accepts it (no on-device timing model)",
            )

            decision_d = gate.send_gated_inject(
                GROUND_EVENT_ID, REPRESENTATIVE_STATE_ID, inside_s, {}, {}
            )
            if not decision_d.sent:
                raise ContactGateVerificationError(
                    f"case D: expected the gate to transmit at in-window now={inside_s}, "
                    f"but it refused (decision={decision_d!r})"
                )
            print(f"[OK] case D: gate transmitted -- {decision_d.reason}", file=sys.stderr)
            _expect_decision(
                decision_d.response,
                legal=True, to_state=REPRESENTATIVE_STATE_ID, transition_id="T-14",
                label="case D: gated INJECT inside a real contact window, over the real Renode UART round trip",
            )

    print(
        "\nAll 4 contact-gate cases passed over a real Renode-simulated UART "
        "round trip: blocked outside a real window (A), provably zero bytes "
        "sent (B), the same command succeeds if the gate is bypassed (C) -- "
        "confirming the firmware itself has no timing model, exactly as this "
        "project's scope requires -- and succeeds through the gate inside a "
        "real window (D).",
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
    except (UartBridgeError, ContactGateVerificationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        restore_committed_config_a_table()

if __name__ == "__main__":
    raise SystemExit(main())
