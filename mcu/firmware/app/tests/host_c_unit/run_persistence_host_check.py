from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

THIS_DIR = Path(__file__).resolve().parent
SRC_DIR = THIS_DIR.parent.parent / "src"
ZEPHYR_BASE_DEFAULT = Path.home() / "zephyrproject" / "zephyr"

COMPILERS = ("gcc", "clang")

SOURCES = [
    THIS_DIR / "harness_persistence_main.c",
    THIS_DIR / "persist_io_fake.c",
    SRC_DIR / "engine_persistence.c",
    SRC_DIR / "engine_config_table.c",
]

def run(*, zephyr_base: Path) -> int:
    crc32_sw_c = zephyr_base / "lib" / "crc" / "crc32_sw.c"
    if not crc32_sw_c.is_file():
        print(f"FAIL: {crc32_sw_c} not found (bad ZEPHYR_BASE?)", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="cepdt_persist_host_check_") as tmpdir:
        build_dir = Path(tmpdir)
        for cc in COMPILERS:
            if shutil.which(cc) is None:
                print(f"FAIL: compiler not found on PATH: {cc}", file=sys.stderr)
                return 1
            out_bin = build_dir / f"persist_check_{cc}"
            cmd = [
                cc, "-std=c11", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
                "-I", str(SRC_DIR),
                "-I", str(THIS_DIR / "zephyr_crc_shim"),
                "-o", str(out_bin),
                *[str(s) for s in SOURCES],
                str(crc32_sw_c),
            ]
            build = subprocess.run(cmd, capture_output=True, text=True)
            if build.returncode != 0:
                print(f"FAIL: {cc} build failed:\n{build.stdout}\n{build.stderr}", file=sys.stderr)
                return 1
            print(f"[build ok] {cc}", file=sys.stderr)

            result = subprocess.run([str(out_bin)], capture_output=True, text=True)
            print(result.stderr, file=sys.stderr)
            if result.returncode != 0:
                print(f"FAIL: {cc}-built harness reported failures", file=sys.stderr)
                return 1

    print("Persistence host-compile check: gcc + clang both clean, all checks passed.", file=sys.stderr)
    return 0

def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zephyr-base", default=None)
    args = parser.parse_args(argv)
    zephyr_base = Path(args.zephyr_base) if args.zephyr_base else ZEPHYR_BASE_DEFAULT
    return run(zephyr_base=zephyr_base)

if __name__ == "__main__":
    raise SystemExit(main())
