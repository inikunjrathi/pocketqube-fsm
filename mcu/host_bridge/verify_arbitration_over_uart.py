from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.arbitration import PendingEvent, arbitrate, step_many  # noqa: E402
from engine.config_loader import load_config  # noqa: E402
from engine.guards import GuardError  # noqa: E402
from engine.persistence import PersistenceLayer  # noqa: E402
from mcu.host_bridge.firmware_build import (  # noqa: E402
    build_firmware_for_config,
    restore_committed_config_a_table,
)
from mcu.host_bridge.uart_bridge import Decision, RenodeSession, Serviced, UartBridge  # noqa: E402

DEFAULT_CASES = 400
SEED = 7


def _draw_case(cfg, rng: random.Random):
    state = rng.choice(sorted(cfg.states))
    now = float(rng.randrange(1, 100000))
    context = {latch.name: rng.random() < 0.5 for latch in cfg.latches}
    telemetry = {
        "elevation": float(rng.randrange(-20, 60)),
        "fault_count": float(rng.randrange(0, 5)),
        "battery_soc": float(rng.randrange(0, 100)),
    }
    ids = rng.sample(sorted(cfg.events), rng.randrange(2, 5))
    pending = [PendingEvent(e, float(rng.randrange(0, 3))) for e in ids]
    return state, now, context, telemetry, pending


def _check_case(bridge, cfg, layer, case) -> tuple[Optional[str], int, int]:
    state, now, context, telemetry, pending = case
    try:
        arb = step_many(cfg, state, pending, context, telemetry=telemetry, now=now, persisted=layer.load())
    except GuardError:
        return None, 0, 0
    ordered = arbitrate(cfg, pending)
    attempts = len(arb.dropped) + (1 if arb.result is not None else 0)
    bridge.send_service(state, now, context, telemetry, [(p.event_id, p.timestamp) for p in pending])
    for i in range(attempts):
        response = bridge.read_response()
        if not isinstance(response, Decision) or response.event_id != ordered[i].event_id:
            return f"attempt {i}: python {ordered[i].event_id}, firmware {response!r}", 0, 0
    if arb.result is not None:
        if response.as_comparison_tuple() != (
            arb.result.new_state, arb.result.transition_id, tuple(arb.result.actions), True
        ):
            return f"result: python {arb.result!r}, firmware {response!r}", 0, 0
        layer.save(arb.result.new_state, arb.result.context)
    end = bridge.read_response()
    expected = tuple(p.event_id for p in arb.remaining)
    if not isinstance(end, Serviced) or end.remaining != expected:
        return f"kept: python {expected}, firmware {end!r}", 0, 0
    return None, int(arb.result is not None), int(bool(expected))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config-a")
    parser.add_argument("--cases", type=int, default=DEFAULT_CASES)
    parser.add_argument("--west", type=Path)
    parser.add_argument("--zephyr-sdk-dir", type=Path)
    parser.add_argument("--zephyr-base", type=Path)
    args = parser.parse_args()

    cfg = load_config(REPO_ROOT / "config" / f"{args.config}.yaml")
    rng = random.Random(SEED)
    layer = PersistenceLayer()
    elf = build_firmware_for_config(
        args.config, west=args.west, zephyr_sdk_dir=args.zephyr_sdk_dir, zephyr_base=args.zephyr_base
    )
    failures = kept = fired = 0
    try:
        with RenodeSession(elf, uart_pty=f"/tmp/cepdt_arbitration_{args.config}"):
            with UartBridge(f"/tmp/cepdt_arbitration_{args.config}") as bridge:
                bridge.wait_for_ready()
                for n in range(args.cases):
                    problem, did_fire, did_keep = _check_case(bridge, cfg, layer, _draw_case(cfg, rng))
                    fired += did_fire
                    kept += did_keep
                    if problem is not None:
                        failures += 1
                        print(f"FAIL case {n}: {problem}", file=sys.stderr)
    finally:
        restore_committed_config_a_table()
    print(f"{args.config}: {args.cases} cases, {fired} fired, {kept} kept events queued, {failures} failed")
    return 0 if failures == 0 and kept > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
