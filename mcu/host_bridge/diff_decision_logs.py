from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from engine.config_loader import load_config  # noqa: E402
from engine.fsm import step  # noqa: E402
from engine.guards import GuardError  # noqa: E402

from mcu.host_bridge.replay_driver import (  # noqa: E402
    CONFIG_PATHS,
    ReplayCase,
    run_full_replay,
)
from mcu.host_bridge.firmware_build import restore_committed_config_a_table  # noqa: E402
from mcu.host_bridge.uart_bridge import Decision, Error, ResponseLine, UartBridgeError  # noqa: E402

class CaseOutcome:
    def __init__(self, case: ReplayCase, response: ResponseLine, match: bool, detail: str) -> None:
        self.case = case
        self.response = response
        self.match = match
        self.detail = detail

def python_oracle_tuple(config_id: str, case: ReplayCase):
    cfg = load_config(CONFIG_PATHS[config_id])
    try:
        result = step(
            cfg,
            case.from_state,
            case.event_id,
            case.context,
            telemetry=case.telemetry,
            now=case.now,
        )
    except GuardError as exc:
        return "guard_error", str(exc)
    return "ok", (result.new_state, result.transition_id, result.actions, result.legal)

def diff_case(config_id: str, case: ReplayCase, response: ResponseLine) -> CaseOutcome:
    kind, python_value = python_oracle_tuple(config_id, case)

    if kind == "guard_error":
        if isinstance(response, Error):
            return CaseOutcome(case, response, True, f"both sides errored ({python_value})")
        return CaseOutcome(
            case, response, False,
            f"python raised GuardError ({python_value}) but firmware returned {response!r}",
        )

    if not isinstance(response, Decision):
        return CaseOutcome(
            case, response, False,
            f"python returned {python_value} but firmware did not return a DECISION line: {response!r}",
        )
    c_value = response.as_comparison_tuple()
    if c_value == python_value:
        return CaseOutcome(case, response, True, "match")
    return CaseOutcome(
        case, response, False,
        f"python={python_value} firmware={c_value}",
    )

def diff_config(
    config_id: str,
    *,
    west: Optional[Path] = None,
    zephyr_sdk_dir: Optional[Path] = None,
    zephyr_base: Optional[Path] = None,
    verbose: bool = False,
) -> list[CaseOutcome]:
    results = run_full_replay(config_id, west=west, zephyr_sdk_dir=zephyr_sdk_dir, zephyr_base=zephyr_base)
    outcomes = []
    for case, response in results:
        outcome = diff_case(config_id, case, response)
        outcomes.append(outcome)
        if verbose or not outcome.match:
            status = "OK" if outcome.match else "MISMATCH"
            print(f"[{status}] {config_id}:{case.label}: {outcome.detail}")
    return outcomes

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", choices=sorted(CONFIG_PATHS), default=None)
    parser.add_argument("--west", default=None)
    parser.add_argument("--zephyr-sdk-dir", default=None)
    parser.add_argument("--zephyr-base", default=None)
    parser.add_argument("-v", "--verbose", action="store_true", help="print every case, not just mismatches")
    args = parser.parse_args(argv)

    config_ids = [args.config] if args.config else list(CONFIG_PATHS)

    all_outcomes: list[CaseOutcome] = []
    try:
        for config_id in config_ids:
            print(f"=== {config_id} ===", file=sys.stderr)
            try:
                outcomes = diff_config(
                    config_id,
                    west=Path(args.west) if args.west else None,
                    zephyr_sdk_dir=Path(args.zephyr_sdk_dir) if args.zephyr_sdk_dir else None,
                    zephyr_base=Path(args.zephyr_base) if args.zephyr_base else None,
                    verbose=args.verbose,
                )
            except UartBridgeError as exc:
                print(f"FAIL: {config_id}: transport error: {exc}", file=sys.stderr)
                return 1
            n_mismatch = sum(1 for o in outcomes if not o.match)
            print(f"{config_id}: {len(outcomes)} cases, {n_mismatch} mismatches", file=sys.stderr)
            all_outcomes.extend(outcomes)
    finally:
        restore_committed_config_a_table()

    total = len(all_outcomes)
    mismatches = [o for o in all_outcomes if not o.match]
    print(f"\nTOTAL: {total} cases, {len(mismatches)} mismatches", file=sys.stderr)
    if mismatches:
        print("\nFailing cases:", file=sys.stderr)
        for o in mismatches:
            print(f"  {o.case.config_id}:{o.case.label}: {o.detail}", file=sys.stderr)
        return 1

    print(
        "All firmware DECISION results match engine.fsm.step() exactly "
        "(replayed over a real Renode-simulated UART round trip).",
        file=sys.stderr,
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
