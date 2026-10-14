from __future__ import annotations

import argparse
import dataclasses
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Union

THIS_DIR = Path(__file__).resolve().parent
SRC_DIR = THIS_DIR.parent.parent / "src"
HARNESS_MAIN = THIS_DIR / "harness_scheduler_main.c"
REPO_ROOT = THIS_DIR.parents[4]

sys.path.insert(0, str(REPO_ROOT))

from engine.scheduler import Item, Scheduler, SchedulerError  # noqa: E402

PRIORITY = ["TTC", "SSTV", "CODEC2_M17"]

class HarnessError(Exception):
    pass

@dataclasses.dataclass(frozen=True)
class InsertOp:
    item: Item

@dataclasses.dataclass(frozen=True)
class SelectOp:
    edf: bool = False

@dataclasses.dataclass(frozen=True)
class PeekClassOp:
    pass

@dataclasses.dataclass(frozen=True)
class CandidatesOp:
    pass

@dataclasses.dataclass(frozen=True)
class IsEmptyOp:
    pass

@dataclasses.dataclass(frozen=True)
class AllItemsOp:
    pass

@dataclasses.dataclass(frozen=True)
class InsertExpectFullOp(InsertOp):
    pass

Op = Union[InsertOp, SelectOp, PeekClassOp, CandidatesOp, IsEmptyOp, AllItemsOp, InsertExpectFullOp]

@dataclasses.dataclass(frozen=True)
class Scenario:
    name: str
    priority: list
    ops: list

def _edf_key(item: Item):
    return item.deadline if item.deadline is not None else math.inf

def build_scenarios() -> list[Scenario]:
    return [
        Scenario(
            name="test_empty_scheduler_selects_none_and_reports_empty",
            priority=PRIORITY,
            ops=[IsEmptyOp(), SelectOp()],
        ),
        Scenario(
            name="test_selects_highest_priority_class_regardless_of_insertion_order",
            priority=PRIORITY,
            ops=[
                InsertOp(Item(id="v1", data_class="CODEC2_M17")),
                InsertOp(Item(id="i1", data_class="SSTV")),
                InsertOp(Item(id="t1", data_class="TTC")),
                SelectOp(), SelectOp(), SelectOp(), SelectOp(),
            ],
        ),
        Scenario(
            name="test_same_class_items_are_fifo",
            priority=PRIORITY,
            ops=[
                InsertOp(Item(id="sstv-1", data_class="SSTV")),
                InsertOp(Item(id="sstv-2", data_class="SSTV")),
                SelectOp(), SelectOp(),
            ],
        ),
        Scenario(
            name="test_newly_arrived_higher_priority_item_preempts_queued_lower_priority_items",
            priority=PRIORITY,
            ops=[
                InsertOp(Item(id="v1", data_class="CODEC2_M17")),
                InsertOp(Item(id="i1", data_class="SSTV")),
                InsertOp(Item(id="t1", data_class="TTC")),
                SelectOp(), SelectOp(), SelectOp(),
            ],
        ),
        Scenario(
            name="test_unknown_data_class_raises_scheduler_error",
            priority=PRIORITY,
            ops=[InsertOp(Item(id="x", data_class="BOGUS"))],
        ),
        Scenario(
            name="test_peek_next_class_does_not_remove_item",
            priority=PRIORITY,
            ops=[
                InsertOp(Item(id="i1", data_class="SSTV")),
                PeekClassOp(), IsEmptyOp(), SelectOp(),
            ],
        ),
        Scenario(
            name="test_candidate_classes_reports_service_order_without_removing_items",
            priority=PRIORITY,
            ops=[
                InsertOp(Item(id="v1", data_class="CODEC2_M17")),
                InsertOp(Item(id="i1", data_class="SSTV")),
                InsertOp(Item(id="t1", data_class="TTC")),
                CandidatesOp(), IsEmptyOp(), SelectOp(),
            ],
        ),
        Scenario(
            name="test_candidate_classes_empty_scheduler",
            priority=PRIORITY,
            ops=[CandidatesOp()],
        ),
        Scenario(
            name="test_select_next_key_none_is_unchanged",
            priority=PRIORITY,
            ops=[
                InsertOp(Item(id="v1", data_class="CODEC2_M17")),
                InsertOp(Item(id="i1", data_class="SSTV")),
                InsertOp(Item(id="t1", data_class="TTC")),
                SelectOp(edf=False), SelectOp(edf=False), SelectOp(edf=False),
            ],
        ),
        Scenario(
            name="test_select_next_key_picks_earliest_deadline_within_top_class",
            priority=PRIORITY,
            ops=[
                InsertOp(Item(id="sstv-late", data_class="SSTV", deadline=500.0)),
                InsertOp(Item(id="sstv-early", data_class="SSTV", deadline=100.0)),
                InsertOp(Item(id="ttc-1", data_class="TTC", deadline=200.0)),
                SelectOp(edf=True), SelectOp(edf=True), SelectOp(edf=True),
            ],
        ),
        Scenario(
            name="test_select_next_key_ties_broken_by_arrival_order",
            priority=PRIORITY,
            ops=[
                InsertOp(Item(id="first", data_class="SSTV", deadline=100.0)),
                InsertOp(Item(id="second", data_class="SSTV", deadline=100.0)),
                SelectOp(edf=True), SelectOp(edf=True),
            ],
        ),
        Scenario(
            name="test_select_next_key_ignores_items_of_a_lower_class",
            priority=PRIORITY,
            ops=[
                InsertOp(Item(id="ttc-1", data_class="TTC", deadline=9999.0)),
                InsertOp(Item(id="sstv-urgent", data_class="SSTV", deadline=1.0)),
                SelectOp(edf=True),
            ],
        ),
        Scenario(
            name="test_all_items_returns_every_queued_item_without_removing",
            priority=PRIORITY,
            ops=[
                InsertOp(Item(id="t1", data_class="TTC")),
                InsertOp(Item(id="i1", data_class="SSTV")),
                AllItemsOp(), IsEmptyOp(), AllItemsOp(),
            ],
        ),
        Scenario(
            name="edge_insert_with_size_bytes_and_deadline_round_trips",
            priority=PRIORITY,
            ops=[
                InsertOp(Item(id="tlm-1", data_class="TTC", size_bytes=4096, deadline=42.5)),
                SelectOp(),
            ],
        ),
        Scenario(
            name="edge_queue_full_at_capacity_boundary",
            priority=PRIORITY,
            ops=(
                [InsertOp(Item(id=f"t{i}", data_class="TTC")) for i in range(16)]
                + [InsertExpectFullOp(Item(id="overflow", data_class="TTC"))]
                + [SelectOp() for _ in range(16)]
            ),
        ),
    ]

@dataclasses.dataclass(frozen=True)
class OpResult:

    kind: str
    value: object

def apply_python(sched: Scheduler, op: Op) -> OpResult:
    if isinstance(op, InsertOp):
        try:
            sched.insert(op.item)
            return OpResult("ok", None)
        except SchedulerError:
            return OpResult("error", "sched_unknown_class")
    if isinstance(op, SelectOp):
        item = sched.select_next(key=_edf_key if op.edf else None)
        return OpResult("item_or_none", None if item is None else item.id)
    if isinstance(op, PeekClassOp):
        return OpResult("class_or_none", sched.peek_next_class())
    if isinstance(op, CandidatesOp):
        return OpResult("class_list", tuple(sched.candidate_classes()))
    if isinstance(op, IsEmptyOp):
        return OpResult("bool", sched.is_empty())
    if isinstance(op, AllItemsOp):
        return OpResult("id_set", frozenset(item.id for item in sched.all_items()))
    raise HarnessError(f"unhandled op type: {op!r}")

def find_cc() -> str:
    for candidate in ("cc", "gcc", "clang"):
        path = shutil.which(candidate)
        if path:
            return path
    raise HarnessError("no C compiler (cc/gcc/clang) found on PATH")

def build_harness(build_dir: Path, cc: str) -> Path:
    exe = build_dir / "scheduler_harness"
    cmd = [
        cc, "-std=c11", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
        "-I", str(SRC_DIR),
        str(HARNESS_MAIN), str(SRC_DIR / "engine_scheduler.c"),
        "-o", str(exe),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise HarnessError(f"C build failed:\n{result.stderr}")
    return exe

class SchedulerHarness:

    def __init__(self, exe: Path) -> None:
        self._proc = subprocess.Popen(
            [str(exe)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )

    def close(self) -> None:
        if self._proc.stdin is not None:
            self._proc.stdin.close()
        self._proc.wait(timeout=5)

    def _send(self, line: str) -> str:
        assert self._proc.stdin is not None and self._proc.stdout is not None
        self._proc.stdin.write(line + "\n")
        self._proc.stdin.flush()
        reply = self._proc.stdout.readline()
        if reply == "":
            stderr = self._proc.stderr.read() if self._proc.stderr else ""
            raise HarnessError(f"harness subprocess closed stdout unexpectedly; stderr:\n{stderr}")
        return reply.rstrip("\n")

    def reset(self, priority: list) -> None:
        reply = self._send("SCHED RESET " + ",".join(priority))
        if reply != "OK":
            raise HarnessError(f"SCHED RESET failed: {reply!r}")

    def apply(self, op: Op) -> OpResult:
        if isinstance(op, InsertOp):
            item = op.item
            deadline_tok = "NONE" if item.deadline is None else repr(item.deadline)
            reply = self._send(f"SCHED INSERT {item.id} {item.data_class} {item.size_bytes} {deadline_tok}")
            if reply == "OK":
                return OpResult("ok", None)
            if reply.startswith("ERROR sched_unknown_class"):
                return OpResult("error", "sched_unknown_class")
            if reply == "ERROR sched_queue_full":
                return OpResult("error", "sched_queue_full")
            raise HarnessError(f"unexpected INSERT reply: {reply!r}")
        if isinstance(op, SelectOp):
            reply = self._send("SCHED SELECT_EDF" if op.edf else "SCHED SELECT")
            if reply == "OK NONE":
                return OpResult("item_or_none", None)
            item_id = _parse_field(reply, "id", label="SELECT")
            return OpResult("item_or_none", item_id)
        if isinstance(op, PeekClassOp):
            reply = self._send("SCHED PEEK_CLASS")
            if reply == "OK NONE":
                return OpResult("class_or_none", None)
            return OpResult("class_or_none", _parse_field(reply, "data_class", label="PEEK_CLASS"))
        if isinstance(op, CandidatesOp):
            reply = self._send("SCHED CANDIDATES")
            classes_str = _parse_field(reply, "classes", label="CANDIDATES")
            return OpResult("class_list", () if classes_str == "NONE" else tuple(classes_str.split(",")))
        if isinstance(op, IsEmptyOp):
            reply = self._send("SCHED IS_EMPTY")
            empty_str = _parse_field(reply, "empty", label="IS_EMPTY")
            return OpResult("bool", empty_str == "1")
        if isinstance(op, AllItemsOp):
            reply = self._send("SCHED ALL_ITEMS")
            ids_str = _parse_field(reply, "ids", label="ALL_ITEMS")
            return OpResult("id_set", frozenset() if ids_str == "NONE" else frozenset(ids_str.split(",")))
        raise HarnessError(f"unhandled op type: {op!r}")

def _parse_field(reply: str, field: str, *, label: str) -> str:
    marker = f"{field}="
    idx = reply.find(marker)
    if not reply.startswith("OK") or idx == -1:
        raise HarnessError(f"unexpected {label} reply: {reply!r}")
    rest = reply[idx + len(marker):]
    return rest.split(" ", 1)[0]

@dataclasses.dataclass
class StepMismatch:
    scenario: str
    step_index: int
    op: Op
    python_result: OpResult
    c_result: OpResult

def run_scenario(harness: SchedulerHarness, scenario: Scenario, verbose: bool) -> list[StepMismatch]:
    sched = Scheduler(list(scenario.priority))
    harness.reset(list(scenario.priority))

    mismatches: list[StepMismatch] = []
    for i, op in enumerate(scenario.ops):
        py_result = apply_python(sched, op)
        c_result = harness.apply(op)
        if isinstance(op, InsertExpectFullOp):
            match = c_result == OpResult("error", "sched_queue_full")
        else:
            match = py_result == c_result
        if verbose:
            status = "OK" if match else "MISMATCH"
            print(f"[{status}] {scenario.name}[{i}] {op!r}: python={py_result} c={c_result}")
        if not match:
            mismatches.append(StepMismatch(scenario.name, i, op, py_result, c_result))
    return mismatches

def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="print every step, not just mismatches")
    args = parser.parse_args(argv)

    cc = find_cc()
    print(f"using C compiler: {cc}")

    scenarios = build_scenarios()

    with tempfile.TemporaryDirectory(prefix="scheduler_equivalence_") as tmp:
        exe = build_harness(Path(tmp), cc)
        harness = SchedulerHarness(exe)
        try:
            all_mismatches: list[StepMismatch] = []
            total_steps = 0
            for scenario in scenarios:
                mismatches = run_scenario(harness, scenario, args.verbose)
                all_mismatches.extend(mismatches)
                total_steps += len(scenario.ops)
                print(f"{scenario.name}: {len(scenario.ops)} steps, {len(mismatches)} mismatches")
        finally:
            harness.close()

    print(f"\nTOTAL: {len(scenarios)} scenarios, {total_steps} steps, {len(all_mismatches)} mismatches")
    if all_mismatches:
        print("\nFailing steps:")
        for m in all_mismatches:
            print(f"  {m.scenario}[{m.step_index}] {m.op!r}: python={m.python_result} c={m.c_result}")
        return 1

    print("All C engine_scheduler.c results match engine.scheduler.Scheduler exactly.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
