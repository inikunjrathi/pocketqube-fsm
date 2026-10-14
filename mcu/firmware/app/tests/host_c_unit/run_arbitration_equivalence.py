from __future__ import annotations

import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SRC_DIR = THIS_DIR.parent.parent / "src"
REPO_ROOT = THIS_DIR.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from engine.arbitration import PendingEvent, arbitrate  # noqa: E402
from engine.config_loader import Config, load_config  # noqa: E402
from mcu.host_bridge.codegen_arbitration_table import render_arbitration_source  # noqa: E402
from tools.codegen_c_table import generate_tables, render_header, render_source  # noqa: E402

CONFIG_IDS = ("config-a", "config-b", "config-c")
N_RANDOM = 2000
TIMESTAMPS = (0.0, 10.0, 10.0, 25.5, 172800.0)

def build_cases(cfg: Config, seed: int = 19) -> list[list[tuple[int, float]]]:
    n = len(cfg.events)
    cases = [[(i, 0.0)] for i in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                cases.append([(i, 5.0), (j, 5.0)])
                cases.append([(i, 6.0), (j, 5.0)])
    rng = random.Random(seed)
    for _ in range(N_RANDOM):
        k = rng.randint(1, 8)
        cases.append([(rng.randrange(n), rng.choice(TIMESTAMPS)) for _ in range(k)])
    return cases

def python_order(cfg: Config, case: list[tuple[int, float]]) -> list[int]:
    ids = list(cfg.events)
    plain = [PendingEvent(ids[e], t) for e, t in case]
    pos = {id(p): k for k, p in enumerate(plain)}
    return [pos[id(p)] for p in arbitrate(cfg, plain)]

def build_harness(cfg: Config, build_dir: Path, cc: str) -> Path:
    tables = generate_tables(cfg)
    (build_dir / "engine_config_table.h").write_text(render_header(cfg, tables))
    (build_dir / "engine_config_table.c").write_text(render_source(cfg, tables))
    (build_dir / "engine_arbitration_table.c").write_text(render_arbitration_source(cfg))
    for name in ("engine_arbitration.h", "engine_arbitration.c"):
        (build_dir / name).write_text((SRC_DIR / name).read_text())
    (build_dir / "harness_arbitration_main.c").write_text((THIS_DIR / "harness_arbitration_main.c").read_text())
    exe = build_dir / "arbitration_harness"
    srcs = [str(build_dir / f) for f in ("engine_config_table.c", "engine_arbitration_table.c",
                                         "engine_arbitration.c", "harness_arbitration_main.c")]
    r = subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-I", str(build_dir),
                        *srcs, "-o", str(exe)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"C build failed:\n{r.stderr}")
    return exe

def run_config(config_id: str, cc: str) -> tuple[int, list[str]]:
    cfg = load_config(REPO_ROOT / "config" / f"{config_id}.yaml")
    cases = build_cases(cfg)
    with tempfile.TemporaryDirectory(prefix="arbitration_") as tmp:
        exe = build_harness(cfg, Path(tmp), cc)
        stdin = "\n".join(" ".join(f"{e} {t!r}" for e, t in c) for c in cases) + "\n"
        out = subprocess.run([str(exe)], input=stdin, capture_output=True, text=True, check=True).stdout.splitlines()
    mismatches = []
    for case, line in zip(cases, out, strict=True):
        c_order = [int(x) for x in line.split()[1:]] if line.startswith("ORDER") else None
        py = python_order(cfg, case)
        if c_order != py:
            mismatches.append(f"{config_id} {case}: python={py} c={line}")
    return len(cases), mismatches

def main() -> int:
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    total, bad = 0, []
    for cid in CONFIG_IDS:
        n, m = run_config(cid, cc)
        total += n
        bad += m
        print(f"{cid}: {n} cases, {len(m)} mismatches")
    for m in bad[:20]:
        print(m)
    return 1 if bad else 0

if __name__ == "__main__":
    raise SystemExit(main())
