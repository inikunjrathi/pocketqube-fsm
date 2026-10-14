# R-19

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

HOST_C_UNIT_DIR = Path(__file__).resolve().parents[1] / "mcu" / "firmware" / "app" / "tests" / "host_c_unit"
sys.path.insert(0, str(HOST_C_UNIT_DIR))

import run_arbitration_equivalence as rae  # noqa: E402

CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")

pytestmark = [
    pytest.mark.skipif(CC is None, reason="no C compiler on this host"),
    pytest.mark.requirement("R-19"),
]

@pytest.mark.parametrize("config_id", rae.CONFIG_IDS)
def test_c_arbitration_matches_python(config_id):
    n, mismatches = rae.run_config(config_id, CC)
    assert n > 2000
    assert not mismatches, "\n".join(mismatches[:20])
