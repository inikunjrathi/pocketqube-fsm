from __future__ import annotations

import argparse
import dataclasses
import gzip
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from engine.config_loader import Config, load_config  # noqa: E402
from tools.generate_baseline_results import (  # noqa: E402
    DEFAULT_DT_S,
    DEFAULT_DURATION_S,
    DEFAULT_SEED,
)

import sim.driver as driver_module  # noqa: E402
from engine.fsm import step as _real_step  # noqa: E402

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

EVIDENCE_ROOT = Path(__file__).resolve().parent / "evidence" / "task8_baseline_seed42"

_EXCLUDED_CALLERS = frozenset({"_find_bootstrap_path"})

@dataclasses.dataclass(frozen=True)
class TraceEntry:

    index: int
    caller: str
    from_state: str
    event_id: str
    now: float
    context: dict
    telemetry: dict
    oracle_new_state: str
    oracle_transition_id: Optional[str]
    oracle_actions: tuple
    oracle_legal: bool

    def oracle_tuple(self) -> tuple[str, Optional[str], tuple, bool]:
        return (self.oracle_new_state, self.oracle_transition_id, tuple(self.oracle_actions), self.oracle_legal)

def capture_baseline_trace(
    cfg: Config, *, seed: int, duration_s: float, dt_s: float
):
    trace: list[TraceEntry] = []

    def _recording_step(
        config: Config,
        state: str,
        event: str,
        context: Mapping[str, Any],
        *,
        telemetry: Optional[Mapping[str, Any]] = None,
        now: float = 0,
        persisted: Optional[Mapping[str, Any]] = None,
        ground_auth_secret: Optional[bytes] = None,
        command_signature: Optional[str] = None,
    ):
        caller_name = sys._getframe(1).f_code.co_name
        result = _real_step(
            config,
            state,
            event,
            context,
            telemetry=telemetry,
            now=now,
            persisted=persisted,
            ground_auth_secret=ground_auth_secret,
            command_signature=command_signature,
        )
        if caller_name not in _EXCLUDED_CALLERS:
            trace.append(
                TraceEntry(
                    index=len(trace),
                    caller=caller_name,
                    from_state=state,
                    event_id=event,
                    now=now,
                    context=dict(context),
                    telemetry=dict(telemetry or {}),
                    oracle_new_state=result.new_state,
                    oracle_transition_id=result.transition_id,
                    oracle_actions=tuple(result.actions),
                    oracle_legal=result.legal,
                )
            )
        return result

    original_step = driver_module.step
    driver_module.step = _recording_step
    try:
        sim_result = driver_module.run_simulation(
            cfg, duration_s=duration_s, dt_s=dt_s, seed=seed
        )
    finally:
        driver_module.step = original_step

    return trace, sim_result

def verify_trace_cross_check(trace: list[TraceEntry], sim_result) -> None:
    n_legal_in_trace = sum(1 for e in trace if e.oracle_legal)
    n_scheduler_calls = sum(1 for e in trace if e.caller == "run_simulation")
    n_transition_log_entries = sum(1 for e in sim_result.decision_log if e.kind == "transition")
    n_scheduler_log_entries = sum(1 for e in sim_result.decision_log if e.kind == "scheduler")

    if n_legal_in_trace != n_transition_log_entries:
        raise AssertionError(
            f"trace's legal-call count ({n_legal_in_trace}) != "
            f"decision_log's transition-entry count ({n_transition_log_entries})"
        )
    if n_scheduler_calls != n_scheduler_log_entries:
        raise AssertionError(
            f"trace's run_simulation-caller count ({n_scheduler_calls}) != "
            f"decision_log's scheduler-entry count ({n_scheduler_log_entries})"
        )

def replay_trace_over_uart(
    config_id: str,
    trace: list[TraceEntry],
    *,
    west: Optional[Path] = None,
    zephyr_sdk_dir: Optional[Path] = None,
    zephyr_base: Optional[Path] = None,
    renode_log_path: Optional[Path] = None,
    progress_every: int = 2000,
) -> list[tuple[TraceEntry, ResponseLine]]:
    elf = build_firmware_for_config(
        config_id, west=west, zephyr_sdk_dir=zephyr_sdk_dir, zephyr_base=zephyr_base
    )
    pty = f"/tmp/cepdt_nucleo_f401re_uart_baseline_{config_id}"
    results: list[tuple[TraceEntry, ResponseLine]] = []
    with RenodeSession(elf, uart_pty=pty, log_path=renode_log_path) as _session:
        with UartBridge(pty) as bridge:
            bridge.wait_for_ready()
            t0 = time.monotonic()
            for entry in trace:
                bridge.send_inject(entry.event_id, entry.from_state, entry.now, entry.context, entry.telemetry)
                response = bridge.read_response()
                results.append((entry, response))
                if progress_every and entry.index % progress_every == 0 and entry.index > 0:
                    elapsed = time.monotonic() - t0
                    rate = entry.index / elapsed if elapsed > 0 else 0.0
                    print(
                        f"  ... {entry.index}/{len(trace)} replayed "
                        f"({elapsed:.1f}s elapsed, {rate:.0f} calls/s)",
                        file=sys.stderr,
                    )
    return results

@dataclasses.dataclass(frozen=True)
class CaseOutcome:
    entry: TraceEntry
    response: ResponseLine
    match: bool
    detail: str

def diff_trace_results(results: list[tuple[TraceEntry, ResponseLine]]) -> list[CaseOutcome]:
    outcomes = []
    for entry, response in results:
        expected = entry.oracle_tuple()
        if not isinstance(response, Decision):
            outcomes.append(
                CaseOutcome(
                    entry, response, False,
                    f"python={expected} but firmware did not return a DECISION line: {response!r}",
                )
            )
            continue
        actual = response.as_comparison_tuple()
        if actual == expected:
            outcomes.append(CaseOutcome(entry, response, True, "match"))
        else:
            outcomes.append(
                CaseOutcome(entry, response, False, f"python={expected} firmware={actual}")
            )
    return outcomes

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

def write_python_trace_jsonl(path: Path, trace: list[TraceEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as f:
        for e in trace:
            record = {
                "index": e.index,
                "caller": e.caller,
                "from_state": e.from_state,
                "event_id": e.event_id,
                "now": e.now,
                "context": e.context,
                "telemetry": e.telemetry,
                "oracle": {
                    "new_state": e.oracle_new_state,
                    "transition_id": e.oracle_transition_id,
                    "actions": list(e.oracle_actions),
                    "legal": e.oracle_legal,
                },
            }
            f.write(json.dumps(record) + "\n")

def write_firmware_log_jsonl(path: Path, results: list[tuple[TraceEntry, ResponseLine]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as f:
        for entry, response in results:
            record = {"index": entry.index, "response": _response_to_dict(response)}
            f.write(json.dumps(record) + "\n")

def run_baseline_equivalence(
    config_id: str,
    *,
    west: Optional[Path] = None,
    zephyr_sdk_dir: Optional[Path] = None,
    zephyr_base: Optional[Path] = None,
    seed: int = DEFAULT_SEED,
    duration_s: float = DEFAULT_DURATION_S,
    dt_s: float = DEFAULT_DT_S,
    limit: Optional[int] = None,
    out_dir: Optional[Path] = None,
    renode_log_path: Optional[Path] = None,
    verbose: bool = False,
) -> list[CaseOutcome]:
    cfg = load_config(CONFIG_PATHS[config_id])
    print(f"capturing real step() trace for {config_id} (seed={seed}, duration_s={duration_s}, dt_s={dt_s}) ...", file=sys.stderr)
    trace, sim_result = capture_baseline_trace(cfg, seed=seed, duration_s=duration_s, dt_s=dt_s)
    verify_trace_cross_check(trace, sim_result)
    print(
        f"captured {len(trace)} real step() calls "
        f"({sum(1 for e in trace if e.oracle_legal)} legal, "
        f"{sum(1 for e in trace if not e.oracle_legal)} illegal); "
        f"cross-check against decision_log passed.",
        file=sys.stderr,
    )

    if limit is not None:
        trace = trace[:limit]
        print(f"--limit given: replaying only the first {len(trace)} calls", file=sys.stderr)

    print(f"booting one continuous Renode session and replaying {len(trace)} INJECT calls ...", file=sys.stderr)
    results = replay_trace_over_uart(
        config_id, trace, west=west, zephyr_sdk_dir=zephyr_sdk_dir,
        zephyr_base=zephyr_base, renode_log_path=renode_log_path,
    )

    outcomes = diff_trace_results(results)
    n_mismatch = sum(1 for o in outcomes if not o.match)
    if verbose or n_mismatch:
        for o in outcomes:
            if verbose or not o.match:
                status = "OK" if o.match else "MISMATCH"
                print(f"[{status}] {config_id}:#{o.entry.index} ({o.entry.caller} {o.entry.from_state}--{o.entry.event_id}): {o.detail}")

    suffix = f"_first{limit}" if limit is not None else ""
    out_dir = out_dir or (EVIDENCE_ROOT / config_id)
    python_log_path = out_dir / f"python_trace{suffix}.jsonl.gz"
    firmware_log_path = out_dir / f"firmware_decisions{suffix}.jsonl.gz"
    write_python_trace_jsonl(python_log_path, trace)
    write_firmware_log_jsonl(firmware_log_path, results)
    print(f"archived: {python_log_path}", file=sys.stderr)
    print(f"archived: {firmware_log_path}", file=sys.stderr)

    print(f"{config_id}: {len(outcomes)} cases, {n_mismatch} mismatches", file=sys.stderr)
    return outcomes

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", choices=sorted(CONFIG_PATHS), default="config-a")
    parser.add_argument("--west", default=None)
    parser.add_argument("--zephyr-sdk-dir", default=None)
    parser.add_argument("--zephyr-base", default=None)
    parser.add_argument(
        "--limit", type=int, default=None,
        help="replay only the first N real step() calls (smoke test / short-slice verification)",
    )
    parser.add_argument("--out-dir", default=None, help="override the evidence archive directory")
    parser.add_argument("--renode-log", default=None, help="capture Renode's own stdout/stderr to this path")
    parser.add_argument("-v", "--verbose", action="store_true", help="print every case, not just mismatches")
    args = parser.parse_args(argv)

    try:
        outcomes = run_baseline_equivalence(
            args.config,
            west=Path(args.west) if args.west else None,
            zephyr_sdk_dir=Path(args.zephyr_sdk_dir) if args.zephyr_sdk_dir else None,
            zephyr_base=Path(args.zephyr_base) if args.zephyr_base else None,
            limit=args.limit,
            out_dir=Path(args.out_dir) if args.out_dir else None,
            renode_log_path=Path(args.renode_log) if args.renode_log else None,
            verbose=args.verbose,
        )
    except UartBridgeError as exc:
        print(f"FAIL: {args.config}: transport error: {exc}", file=sys.stderr)
        return 1
    finally:
        restore_committed_config_a_table()

    n_mismatch = sum(1 for o in outcomes if not o.match)
    if n_mismatch:
        print("\nFailing cases:", file=sys.stderr)
        for o in outcomes:
            if not o.match:
                print(f"  #{o.entry.index}: {o.detail}", file=sys.stderr)
        return 1

    print(
        "All firmware DECISION results match engine.fsm.step() exactly, "
        "replayed over a single continuous real Renode-simulated UART session "
        "for the full seed=42 baseline run.",
        file=sys.stderr,
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
