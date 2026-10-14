from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import tempfile
from pathlib import Path
from typing import Iterator, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from engine.config_loader import Config, load_config  # noqa: E402
from tests.fixtures.transition_cases import illegal_pairs, legal_cases  # noqa: E402

from mcu.host_bridge.firmware_build import (  # noqa: E402
    build_firmware_for_config,
    restore_committed_config_a_table,
)
from mcu.host_bridge.uart_bridge import (  # noqa: E402
    Decision,
    Error,
    RenodeSession,
    ResponseLine,
    UartBridge,
    UartBridgeError,
)

CONFIG_PATHS = {
    "config-a": REPO_ROOT / "config" / "config-a.yaml",
    "config-b": REPO_ROOT / "config" / "config-b.yaml",
    "config-c": REPO_ROOT / "config" / "config-c.yaml",
}

@dataclasses.dataclass(frozen=True)
class ReplayCase:

    config_id: str
    label: str
    from_state: str
    event_id: str
    now: float
    context: dict
    telemetry: dict
    expected_transition_id: Optional[str]

def iter_replay_cases(cfg: Config) -> Iterator[ReplayCase]:
    for case in legal_cases(cfg):
        yield ReplayCase(
            config_id=cfg.config_id,
            label=f"{case.transition.id}@{case.origin_state}",
            from_state=case.origin_state,
            event_id=case.transition.event,
            now=case.fixture.now,
            context=dict(case.fixture.context),
            telemetry=dict(case.fixture.telemetry),
            expected_transition_id=case.transition.id,
        )
    for _cfg, state_id, event_id in illegal_pairs(cfg):
        yield ReplayCase(
            config_id=cfg.config_id,
            label=f"illegal {state_id},{event_id}",
            from_state=state_id,
            event_id=event_id,
            now=0.0,
            context={},
            telemetry={},
            expected_transition_id=None,
        )

def replay_config(
    config_id: str, bridge: UartBridge, cases: Optional[list[ReplayCase]] = None
) -> Iterator[tuple[ReplayCase, ResponseLine]]:
    if cases is None:
        cfg = load_config(CONFIG_PATHS[config_id])
        cases = list(iter_replay_cases(cfg))

    for case in cases:
        bridge.send_inject(case.event_id, case.from_state, case.now, case.context, case.telemetry)
        response = bridge.read_response()
        yield case, response

def run_full_replay(
    config_id: str,
    *,
    west: Optional[Path] = None,
    zephyr_sdk_dir: Optional[Path] = None,
    zephyr_base: Optional[Path] = None,
    uart_pty: Optional[str] = None,
    renode_log_path: Optional[Path] = None,
) -> list[tuple[ReplayCase, ResponseLine]]:
    elf = build_firmware_for_config(
        config_id, west=west, zephyr_sdk_dir=zephyr_sdk_dir, zephyr_base=zephyr_base
    )
    pty = uart_pty or f"/tmp/cepdt_nucleo_f401re_uart_replay_{config_id}"
    with RenodeSession(elf, uart_pty=pty, log_path=renode_log_path) as _session:
        with UartBridge(pty) as bridge:
            bridge.wait_for_ready()
            return list(replay_config(config_id, bridge))

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", choices=sorted(CONFIG_PATHS), default=None,
        help="replay only this config (default: all three, in order)",
    )
    parser.add_argument("--west", default=None, help="override CEPDT_WEST (path to the west binary)")
    parser.add_argument("--zephyr-sdk-dir", default=None, help="override ZEPHYR_SDK_INSTALL_DIR")
    parser.add_argument("--zephyr-base", default=None, help="override ZEPHYR_BASE")
    parser.add_argument(
        "--out-dir", default=None,
        help="directory to write one <config_id>.jsonl replay log per config "
        "(default: a fresh temporary directory, printed to stderr)",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir) if args.out_dir else Path(tempfile.mkdtemp(prefix="cepdt_replay_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"replay logs will be written under: {out_dir}", file=sys.stderr)

    config_ids = [args.config] if args.config else list(CONFIG_PATHS)

    exit_code = 0
    try:
        for config_id in config_ids:
            print(f"=== {config_id} ===", file=sys.stderr)
            try:
                results = run_full_replay(
                    config_id,
                    west=Path(args.west) if args.west else None,
                    zephyr_sdk_dir=Path(args.zephyr_sdk_dir) if args.zephyr_sdk_dir else None,
                    zephyr_base=Path(args.zephyr_base) if args.zephyr_base else None,
                )
            except UartBridgeError as exc:
                print(f"FAIL: {config_id}: {exc}", file=sys.stderr)
                exit_code = 1
                continue

            log_path = out_dir / f"{config_id}.jsonl"
            n_errors = 0
            with open(log_path, "w") as f:
                for case, response in results:
                    if isinstance(response, Error):
                        n_errors += 1
                    record = {
                        "case": dataclasses.asdict(case),
                        "response": _response_to_dict(response),
                    }
                    f.write(json.dumps(record) + "\n")
            print(
                f"{config_id}: {len(results)} cases replayed, {n_errors} ERROR "
                f"response(s) -- log: {log_path}",
                file=sys.stderr,
            )
    finally:
        restore_committed_config_a_table()

    return exit_code

def _response_to_dict(response: ResponseLine) -> dict:
    if isinstance(response, Decision):
        return {
            "kind": "DECISION",
            "now": response.now,
            "from_state": response.from_state,
            "event_id": response.event_id,
            "to_state": response.to_state,
            "transition_id": response.transition_id,
            "legal": response.legal,
            "actions": list(response.actions),
        }
    if isinstance(response, Error):
        return {"kind": "ERROR", "reason": response.reason, "detail": response.detail}
    return {"kind": "RAW", "text": getattr(response, "text", repr(response))}

if __name__ == "__main__":
    raise SystemExit(main())
