from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOST_C_UNIT_DIR = REPO_ROOT / "mcu" / "firmware" / "app" / "tests" / "host_c_unit"
sys.path.insert(0, str(HOST_C_UNIT_DIR))

import run_scheduler_equivalence as rse  # noqa: E402

CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")

pytestmark = pytest.mark.skipif(CC is None, reason="no C compiler (cc/gcc/clang) available on this host")

@pytest.fixture(scope="module")
def scheduler_harness(tmp_path_factory):
    build_dir = tmp_path_factory.mktemp("scheduler_equivalence_pytest")
    exe = rse.build_harness(build_dir, CC)
    harness = rse.SchedulerHarness(exe)
    try:
        yield harness
    finally:
        harness.close()

@pytest.mark.parametrize("scenario", rse.build_scenarios(), ids=lambda s: s.name)
def test_c_scheduler_matches_python_oracle(scenario, scheduler_harness):
    mismatches = rse.run_scenario(scheduler_harness, scenario, verbose=False)
    assert not mismatches, "\n" + "\n".join(
        f"step {m.step_index} {m.op!r}: python={m.python_result} c={m.c_result}" for m in mismatches
    )

def test_scenario_count_regression_guard():
    assert len(rse.build_scenarios()) == 15
