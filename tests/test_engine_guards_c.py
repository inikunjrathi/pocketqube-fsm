from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOST_C_UNIT_DIR = REPO_ROOT / "mcu" / "firmware" / "app" / "tests" / "host_c_unit"
sys.path.insert(0, str(HOST_C_UNIT_DIR))

import run_guard_equivalence as rge  # noqa: E402

from engine.config_loader import load_config  # noqa: E402

CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")

pytestmark = pytest.mark.skipif(CC is None, reason="no C compiler (cc/gcc/clang) available on this host")

@pytest.fixture(scope="module")
def build_root():
    with tempfile.TemporaryDirectory(prefix="guard_equivalence_pytest_") as tmp:
        yield Path(tmp)

@pytest.mark.parametrize("config_id", ["config-a", "config-b", "config-c"])
def test_c_guard_evaluator_matches_python_oracle(config_id, build_root):
    results = rge.run_config(config_id, CC, build_root, verbose=False)
    assert results, f"{config_id}: no guarded transitions were exercised -- check _build_cases_for_config()"
    failures = [r for r in results if not r.matches]
    assert not failures, "\n" + "\n".join(
        f"{r.case.config_id}:{r.case.transition_id} ({r.case.kind}): "
        f"python={'error:' + r.python_error if not r.python_ok else r.python_value} "
        f"c={'error:' + r.c_error if not r.c_ok else r.c_value}"
        for r in failures
    )

def test_every_guarded_transition_across_all_three_configs_is_exercised():
    total_guarded = 0
    for config_id, path in rge.CONFIG_PATHS.items():
        cfg = load_config(path)
        total_guarded += sum(1 for t in cfg.transitions if t.guard is not None)
    assert total_guarded == 24
