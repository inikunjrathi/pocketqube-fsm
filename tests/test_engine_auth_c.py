from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOST_C_UNIT_DIR = REPO_ROOT / "mcu" / "firmware" / "app" / "tests" / "host_c_unit"
sys.path.insert(0, str(HOST_C_UNIT_DIR))

import run_auth_equivalence as rae  # noqa: E402

CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")

def _mbedtls_available() -> bool:
    if CC is None:
        return False
    probe_src = (
        "#include <mbedtls/md.h>\n"
        "int main(void) { return mbedtls_md_info_from_type(MBEDTLS_MD_SHA256) == 0; }\n"
    )
    with tempfile.TemporaryDirectory(prefix="mbedtls_probe_") as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "probe.c"
        src.write_text(probe_src)
        exe = tmp_path / "probe"
        result = subprocess.run(
            [CC, "-std=c11", str(src), "-lmbedcrypto", "-o", str(exe)],
            capture_output=True, text=True,
        )
        return result.returncode == 0

MBEDTLS_AVAILABLE = _mbedtls_available()

pytestmark = pytest.mark.skipif(
    not MBEDTLS_AVAILABLE,
    reason="no C compiler + linkable system mbedTLS (-lmbedcrypto) available on this host",
)

@pytest.fixture(scope="module")
def auth_harness():
    with tempfile.TemporaryDirectory(prefix="auth_equivalence_pytest_") as tmp:
        exe = rae.build_auth_harness(Path(tmp), CC)
        harness = rae.AuthHarness(exe)
        try:
            yield harness
        finally:
            harness.close()

def test_c_sign_command_matches_python_oracle_over_golden_vector_matrix(auth_harness):
    mismatches, n_matrix = rae.run_golden_vector_matrix(auth_harness, verbose=False)
    assert n_matrix > 0, "golden-vector matrix is empty -- check run_auth_equivalence.build_matrix()"
    assert not mismatches, "\n" + "\n".join(f"{m.label}: {m.detail}" for m in mismatches)

def test_c_auth_domain_boundary_and_defensive_checks(auth_harness):
    mismatches = rae.run_domain_boundary_checks(auth_harness, verbose=False)
    assert not mismatches, "\n" + "\n".join(f"{m.label}: {m.detail}" for m in mismatches)

def test_golden_vector_matrix_size_regression_guard():
    assert len(rae.build_matrix()) == 336
