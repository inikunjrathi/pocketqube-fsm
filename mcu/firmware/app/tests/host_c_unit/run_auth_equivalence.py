from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

THIS_DIR = Path(__file__).resolve().parent
SRC_DIR = THIS_DIR.parent.parent / "src"
HARNESS_MAIN = THIS_DIR / "harness_auth_main.c"
REPO_ROOT = THIS_DIR.parents[4]

sys.path.insert(0, str(REPO_ROOT))

from engine.auth import sign_command, verify_command  # noqa: E402

EVENT_IDS = (
    "E-01",
    "E-13",
    "E-18",
    "UPLINK_CMD_GENERIC",
    "GROUND_SAFE_MODE_CMD",
    "",
    "T-99-not-a-real-event-id-but-a-syntactically-valid-string",
)

NOW_VALUES = (
    0.0,
    1.0,
    100.0,
    900.0,
    3600.0,
    172800.0,
    999999999999.0,
    999999999999999.0,
)

SECRETS = (
    b"secret",
    b"",
    bytes([0x00, 0x01, 0x02, 0xFF, 0xFE]),
    bytes(range(32)),
    b"a" * 100,
    b"phase8-task5-test-harness-secret-do-not-use-in-flight",
)

@dataclass(frozen=True)
class GoldenCase:
    event_id: str
    now: float
    secret: bytes

def build_matrix() -> list[GoldenCase]:
    return [
        GoldenCase(event_id=e, now=n, secret=s)
        for e in EVENT_IDS
        for n in NOW_VALUES
        for s in SECRETS
    ]

class HarnessError(Exception):
    pass

def find_cc() -> str:
    for candidate in ("cc", "gcc", "clang"):
        path = shutil.which(candidate)
        if path:
            return path
    raise HarnessError("no C compiler (cc/gcc/clang) found on PATH")

def build_auth_harness(build_dir: Path, cc: str) -> Path:
    (build_dir / "engine_auth.h").write_text((SRC_DIR / "engine_auth.h").read_text())
    (build_dir / "engine_auth.c").write_text((SRC_DIR / "engine_auth.c").read_text())
    (build_dir / "harness_auth_main.c").write_text(HARNESS_MAIN.read_text())

    exe = build_dir / "auth_harness"
    c_files = sorted(str(p) for p in build_dir.glob("*.c"))
    cmd = [
        cc, "-std=c11", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
        "-DMBEDTLS_DECLARE_PRIVATE_IDENTIFIERS",
        *c_files, "-lmbedcrypto", "-o", str(exe),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise HarnessError(f"C build failed:\n{result.stderr}")
    return exe

def _hex(b: bytes) -> str:
    return b.hex()

def encode_sign_line(case: GoldenCase) -> str:
    return f"SIGN|{case.event_id}|{case.now!r}|{_hex(case.secret)}"

def encode_verify_line(event_id: str, now: float, secret: bytes, signature) -> str:
    sig_field = "NULL" if signature is None else signature
    return f"VERIFY|{event_id}|{now!r}|{_hex(secret)}|{sig_field}"

class AuthHarness:

    def __init__(self, exe: Path) -> None:
        self._proc = subprocess.Popen(
            [str(exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, bufsize=1,
        )

    def close(self) -> None:
        if self._proc.stdin:
            self._proc.stdin.close()
        self._proc.wait(timeout=5)

    def _roundtrip(self, line: str) -> str:
        assert self._proc.stdin is not None and self._proc.stdout is not None
        self._proc.stdin.write(line + "\n")
        self._proc.stdin.flush()
        out = self._proc.stdout.readline()
        if not out:
            raise HarnessError(f"auth_harness produced no output for input: {line!r}")
        return out.rstrip("\n")

    def sign(self, case: GoldenCase) -> tuple[bool, Optional[str]]:
        out = self._roundtrip(encode_sign_line(case))
        parts = out.split(" ", 2)
        if len(parts) < 3 or parts[0] != "SIGN":
            raise HarnessError(f"malformed SIGN response: {out!r}")
        status = parts[2].split(" ", 1)
        if status[0] == "RESULT":
            return True, status[1]
        return False, None

    def verify(self, event_id: str, now: float, secret: bytes, signature) -> bool:
        out = self._roundtrip(encode_verify_line(event_id, now, secret, signature))
        parts = out.split(" ", 2)
        if len(parts) < 3 or parts[0] != "VERIFY":
            raise HarnessError(f"malformed VERIFY response: {out!r}")
        status = parts[2].split(" ", 1)
        if status[0] != "RESULT":
            raise HarnessError(f"VERIFY errored unexpectedly: {out!r}")
        return status[1] == "true"

@dataclass
class Mismatch:
    label: str
    detail: str

def run_golden_vector_matrix(harness: AuthHarness, verbose: bool) -> tuple[list[Mismatch], int]:
    mismatches: list[Mismatch] = []
    matrix = build_matrix()
    for case in matrix:
        python_hex = sign_command(case.event_id, case.now, case.secret)
        c_ok, c_hex = harness.sign(case)
        label = f"event_id={case.event_id!r} now={case.now!r} secret={case.secret!r}"
        if not c_ok:
            mismatches.append(Mismatch(label, f"C sign FAILED (expected RESULT); python={python_hex}"))
        elif c_hex != python_hex:
            mismatches.append(Mismatch(label, f"python={python_hex} c={c_hex}"))
        elif verbose:
            print(f"[OK] {label}: {python_hex}")
    return mismatches, len(matrix)

def run_domain_boundary_checks(harness: AuthHarness, verbose: bool) -> list[Mismatch]:
    mismatches: list[Mismatch] = []
    secret = b"secret"

    ok, _ = harness.sign(GoldenCase("E-01", 100.5, secret))
    if ok:
        mismatches.append(Mismatch("fractional now=100.5", "C sign should have failed closed but returned RESULT"))
    elif verbose:
        print("[OK] fractional now=100.5: C correctly failed closed")

    ok, _ = harness.sign(GoldenCase("E-01", -1.0, secret))
    if ok:
        mismatches.append(Mismatch("negative now=-1.0", "C sign should have failed closed but returned RESULT"))
    elif verbose:
        print("[OK] negative now=-1.0: C correctly failed closed")

    ok, _ = harness.sign(GoldenCase("E-01", 1e15, secret))
    if ok:
        mismatches.append(Mismatch("now=1e15 (at ceiling)", "C sign should have failed closed but returned RESULT"))
    elif verbose:
        print("[OK] now=1e15 (at ceiling): C correctly failed closed")

    py_result = verify_command("E-01", 100.0, None, secret)
    c_result = harness.verify("E-01", 100.0, secret, None)
    if py_result != c_result or py_result is not False:
        mismatches.append(Mismatch("verify with signature=None", f"python={py_result} c={c_result}"))
    elif verbose:
        print(f"[OK] verify with signature=None: python={py_result} c={c_result}")

    correct_sig = sign_command("E-01", 100.0, secret)
    py_result = verify_command("E-01", 100.0, correct_sig, secret)
    c_result = harness.verify("E-01", 100.0, secret, correct_sig)
    if py_result != c_result or py_result is not True:
        mismatches.append(Mismatch("verify with the correct signature", f"python={py_result} c={c_result}"))
    elif verbose:
        print(f"[OK] verify with the correct signature: python={py_result} c={c_result}")

    wrong_sig = "0" * 64
    py_result = verify_command("E-01", 100.0, wrong_sig, secret)
    c_result = harness.verify("E-01", 100.0, secret, wrong_sig)
    if py_result != c_result or py_result is not False:
        mismatches.append(Mismatch("verify with a wrong signature", f"python={py_result} c={c_result}"))
    elif verbose:
        print(f"[OK] verify with a wrong signature: python={py_result} c={c_result}")

    py_result = verify_command("E-01", 100.0, "abcd", secret)
    c_result = harness.verify("E-01", 100.0, secret, "abcd")
    if py_result != c_result or py_result is not False:
        mismatches.append(Mismatch("verify with a wrong-length signature", f"python={py_result} c={c_result}"))
    elif verbose:
        print(f"[OK] verify with a wrong-length signature: python={py_result} c={c_result}")

    empty_key_sig = sign_command("E-01", 100.0, b"")
    if harness.verify("E-01", 100.0, b"", empty_key_sig):
        mismatches.append(Mismatch("verify with no secret provisioned", "C accepted; must fail closed"))
    elif verbose:
        print("[OK] verify with no secret provisioned: C correctly failed closed")

    return mismatches

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="print every case, not just failures")
    parser.add_argument(
        "--keep-build-dir", action="store_true",
        help="do not delete the temporary build directory on exit (for debugging)",
    )
    args = parser.parse_args(argv)

    cc = find_cc()
    print(f"using C compiler: {cc}")

    tmp_ctx = tempfile.TemporaryDirectory(prefix="auth_equivalence_")
    build_dir = Path(tmp_ctx.name)

    try:
        exe = build_auth_harness(build_dir, cc)
        harness = AuthHarness(exe)
        try:
            golden_mismatches, n_matrix = run_golden_vector_matrix(harness, args.verbose)
            print(f"golden-vector matrix: {n_matrix} cases, {len(golden_mismatches)} mismatches")

            boundary_mismatches = run_domain_boundary_checks(harness, args.verbose)
            print(f"domain-boundary/defensive checks: {len(boundary_mismatches)} mismatches")
        finally:
            harness.close()
    finally:
        if args.keep_build_dir:
            print(f"build directory kept at: {build_dir}")
            tmp_ctx._finalizer.detach()  # type: ignore[attr-defined]
        else:
            tmp_ctx.cleanup()

    all_mismatches = golden_mismatches + boundary_mismatches
    print(f"\nTOTAL: {len(all_mismatches)} mismatches")
    if all_mismatches:
        print("\nFailing cases:")
        for m in all_mismatches:
            print(f"  {m.label}: {m.detail}")
        return 1

    print(
        "All C engine_auth_sign_command() results match the real "
        "engine.auth.sign_command() byte-for-byte over the full golden-vector "
        "matrix, and all domain-boundary/defensive checks passed."
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
