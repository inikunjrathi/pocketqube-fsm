from __future__ import annotations

import argparse
import os
import random
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path
from typing import Optional

THIS_DIR = Path(__file__).resolve().parent
HARNESS_MAIN = THIS_DIR / "harness_crc32_main.c"
CRC_SHIM_DIR = THIS_DIR / "zephyr_crc_shim"

DEFAULT_ZEPHYR_BASE = Path(os.environ.get("ZEPHYR_BASE", Path.home() / "zephyrproject" / "zephyr"))

COMPILERS = ("gcc", "clang")

def _random_payloads(count: int, max_len: int, seed: int) -> list[bytes]:
    rng = random.Random(seed)
    payloads: list[bytes] = [b"", b"A", b"hello world", bytes(range(256)), b"\x00" * 556]
    for _ in range(count):
        n = rng.randint(0, max_len)
        payloads.append(bytes(rng.randrange(256) for _ in range(n)))
    return payloads

def run(*, zephyr_base: Path, case_count: int = 200, verbose: bool = False) -> int:
    crc32_sw_c = zephyr_base / "lib" / "crc" / "crc32_sw.c"
    if not crc32_sw_c.is_file():
        print(f"FAIL: {crc32_sw_c} not found (bad --zephyr-base / ZEPHYR_BASE?)", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="cepdt_crc32_conformance_") as tmpdir:
        build_dir = Path(tmpdir)

        binaries: dict[str, Path] = {}
        for cc in COMPILERS:
            if shutil.which(cc) is None:
                print(f"FAIL: compiler not found on PATH: {cc}", file=sys.stderr)
                return 1
            out_bin = build_dir / f"crc32_check_{cc}"
            cmd = [
                cc, "-std=c11", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
                "-I", str(CRC_SHIM_DIR),
                "-o", str(out_bin),
                str(HARNESS_MAIN), str(crc32_sw_c),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"FAIL: {cc} build failed:\n{result.stdout}\n{result.stderr}", file=sys.stderr)
                return 1
            binaries[cc] = out_bin
            if verbose:
                print(f"[build ok] {cc} -> {out_bin}", file=sys.stderr)

        payloads = _random_payloads(case_count, max_len=600, seed=42)
        mismatches = 0
        comparisons = 0
        for i, payload in enumerate(payloads):
            payload_path = build_dir / f"payload_{i}.bin"
            payload_path.write_bytes(payload)
            expected = zlib.crc32(payload) & 0xFFFFFFFF
            for cc, binpath in binaries.items():
                out = subprocess.run([str(binpath), str(payload_path)], capture_output=True, text=True)
                if out.returncode != 0:
                    print(f"FAIL: harness ({cc}) exited {out.returncode} on case {i}: {out.stderr}", file=sys.stderr)
                    return 1
                got = int(out.stdout.strip(), 16)
                comparisons += 1
                if got != expected:
                    mismatches += 1
                    print(
                        f"MISMATCH case {i} ({cc}): len={len(payload)} "
                        f"c={got:08x} zlib={expected:08x}",
                        file=sys.stderr,
                    )

        print(
            f"crc32_ieee() vs zlib.crc32(): {comparisons} comparisons "
            f"({len(payloads)} payloads x {len(binaries)} compilers), "
            f"{mismatches} mismatches",
            file=sys.stderr,
        )
        return 1 if mismatches else 0

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zephyr-base", default=None)
    parser.add_argument("--cases", type=int, default=200)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    zephyr_base = Path(args.zephyr_base) if args.zephyr_base else DEFAULT_ZEPHYR_BASE
    return run(zephyr_base=zephyr_base, case_count=args.cases, verbose=args.verbose)

if __name__ == "__main__":
    raise SystemExit(main())
