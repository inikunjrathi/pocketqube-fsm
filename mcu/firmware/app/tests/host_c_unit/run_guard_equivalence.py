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
HARNESS_MAIN = THIS_DIR / "harness_main.c"
REPO_ROOT = THIS_DIR.parents[4]

sys.path.insert(0, str(REPO_ROOT))

from engine.config_loader import Config, load_config  # noqa: E402
from engine.guards import GuardError, evaluate_guard  # noqa: E402
from tests.fixtures.transition_cases import fixture_for  # noqa: E402
from tools.codegen_c_table import generate_tables, render_header, render_source  # noqa: E402

CONFIG_PATHS = {
    "config-a": REPO_ROOT / "config" / "config-a.yaml",
    "config-b": REPO_ROOT / "config" / "config-b.yaml",
    "config-c": REPO_ROOT / "config" / "config-c.yaml",
}

class HarnessError(Exception):
    pass

@dataclass(frozen=True)
class Case:
    config_id: str
    transition_id: str
    kind: str
    now: float
    context: dict
    telemetry: dict
    expect_guard_error: bool = False

@dataclass
class CaseResult:
    case: Case
    python_ok: bool
    python_value: Optional[bool]
    python_error: Optional[str]
    c_ok: bool
    c_value: Optional[bool]
    c_error: Optional[str]

    @property
    def matches(self) -> bool:
        if self.case.expect_guard_error:
            return (not self.python_ok) and (not self.c_ok)
        return self.python_ok and self.c_ok and (self.python_value == self.c_value)

def _fmt_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    raise TypeError(f"unsupported value type for the guard-harness wire format: {value!r}")

def _fmt_kv(mapping: dict) -> str:
    return ",".join(f"{k}={_fmt_scalar(v)}" for k, v in mapping.items())

def encode_case(case: Case) -> str:
    return f"{case.transition_id}|{_fmt_scalar(case.now)}|{_fmt_kv(case.context)}|{_fmt_kv(case.telemetry)}"

def _build_cases_for_config(cfg: Config) -> list[Case]:
    tables = generate_tables(cfg)
    row_by_id = {row.id: row for row in tables.transitions}
    params = {pid: p.value for pid, p in cfg.parameters.items()}

    cases: list[Case] = []
    for t in cfg.transitions:
        if t.guard is None:
            continue
        fixture = fixture_for(cfg, t)
        row = row_by_id[t.id]
        guard = row.guard
        lhs, rhs = guard.lhs, guard.rhs

        cases.append(
            Case(
                config_id=cfg.config_id,
                transition_id=t.id,
                kind="fixture (guard-satisfying)",
                now=fixture.now,
                context=dict(fixture.context),
                telemetry=dict(fixture.telemetry),
            )
        )

        recognized_shape = False

        if lhs.kind == "CONTEXT" and rhs.kind == "LIT_BOOL":
            recognized_shape = True
            name = lhs.name
            current = fixture.context.get(name, False)

            flipped_context = dict(fixture.context)
            flipped_context[name] = not current
            cases.append(
                Case(
                    config_id=cfg.config_id,
                    transition_id=t.id,
                    kind=f"context.{name} flipped",
                    now=fixture.now,
                    context=flipped_context,
                    telemetry=dict(fixture.telemetry),
                )
            )

            cases.append(
                Case(
                    config_id=cfg.config_id,
                    transition_id=t.id,
                    kind=f"context.{name} missing (unset flag -> false, not an error)",
                    now=fixture.now,
                    context={},
                    telemetry=dict(fixture.telemetry),
                )
            )

        if lhs.kind == "ELAPSED" and rhs.kind == "PARAM":
            recognized_shape = True
            timer_name = lhs.name
            threshold = params[rhs.param_id]
            for delta in (-1, 0, 1):
                boundary_now = threshold + delta
                cases.append(
                    Case(
                        config_id=cfg.config_id,
                        transition_id=t.id,
                        kind=f"elapsed({timer_name}) boundary now={boundary_now}",
                        now=boundary_now,
                        context={timer_name: 0},
                        telemetry=dict(fixture.telemetry),
                    )
                )
            cases.append(
                Case(
                    config_id=cfg.config_id,
                    transition_id=t.id,
                    kind=f"elapsed({timer_name}) never armed (-> VAL_NONE -> false, not an error)",
                    now=fixture.now,
                    context={},
                    telemetry=dict(fixture.telemetry),
                )
            )

        if lhs.kind == "TELEMETRY" and rhs.kind == "PARAM":
            recognized_shape = True
            field_name = lhs.name
            threshold = params[rhs.param_id]
            for delta in (-1, 0, 1):
                boundary_value = threshold + delta
                telemetry = dict(fixture.telemetry)
                telemetry[field_name] = boundary_value
                cases.append(
                    Case(
                        config_id=cfg.config_id,
                        transition_id=t.id,
                        kind=f"{field_name} boundary value={boundary_value}",
                        now=fixture.now,
                        context=dict(fixture.context),
                        telemetry=telemetry,
                    )
                )
            cases.append(
                Case(
                    config_id=cfg.config_id,
                    transition_id=t.id,
                    kind=f"{field_name} missing (-> hard error on both sides)",
                    now=fixture.now,
                    context=dict(fixture.context),
                    telemetry={},
                    expect_guard_error=True,
                )
            )

        if not recognized_shape:
            raise HarnessError(
                f"{cfg.config_id}:{t.id}: guard {t.guard!r} has an operand-kind "
                f"combination ({lhs.kind} {guard.op} {rhs.kind}) this harness does "
                "not yet generate boundary cases for -- config drift, or a "
                "genuinely new guard shape landed; extend "
                "_build_cases_for_config() before trusting this run's coverage."
            )

    return cases

def find_cc() -> str:
    for candidate in ("cc", "gcc", "clang"):
        path = shutil.which(candidate)
        if path:
            return path
    raise HarnessError("no C compiler (cc/gcc/clang) found on PATH")

def build_config_binary(cfg: Config, build_dir: Path, cc: str) -> Path:
    tables = generate_tables(cfg)
    (build_dir / "engine_config_table.h").write_text(render_header(cfg, tables))
    (build_dir / "engine_config_table.c").write_text(render_source(cfg, tables))
    (build_dir / "engine_guards.h").write_text((SRC_DIR / "engine_guards.h").read_text())
    (build_dir / "engine_guards.c").write_text((SRC_DIR / "engine_guards.c").read_text())
    (build_dir / "harness_main.c").write_text(HARNESS_MAIN.read_text())

    exe = build_dir / "guard_harness"
    c_files = sorted(str(p) for p in build_dir.glob("*.c"))
    cmd = [cc, "-std=c11", "-Wall", "-Wextra", "-Wpedantic", "-Werror", *c_files, "-o", str(exe)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise HarnessError(f"C build failed for {cfg.config_id}:\n{result.stderr}")
    return exe

def run_c_harness(exe: Path, cases: list[Case]) -> list[tuple[bool, Optional[bool], Optional[str]]]:
    stdin_text = "\n".join(encode_case(c) for c in cases) + "\n"
    result = subprocess.run([str(exe)], input=stdin_text, capture_output=True, text=True)
    if result.returncode != 0:
        raise HarnessError(f"{exe} exited {result.returncode}, stderr:\n{result.stderr}")
    lines = result.stdout.splitlines()
    if len(lines) != len(cases):
        raise HarnessError(
            f"{exe} produced {len(lines)} output lines for {len(cases)} input cases "
            f"(protocol desync) -- stdout was:\n{result.stdout}"
        )
    parsed = []
    for line in lines:
        parts = line.split(" ", 2)
        if len(parts) < 2:
            raise HarnessError(f"malformed harness output line: {line!r}")
        status = parts[1]
        if status == "RESULT":
            parsed.append((True, parts[2] == "true", None))
        elif status == "ERROR":
            parsed.append((False, None, parts[2] if len(parts) > 2 else "unknown"))
        else:
            raise HarnessError(f"unrecognized harness output line: {line!r}")
    return parsed

def python_oracle(guard: str, case: Case, params: dict) -> tuple[bool, Optional[bool], Optional[str]]:
    try:
        value = evaluate_guard(guard, context=case.context, telemetry=case.telemetry, params=params, now=case.now)
        return True, value, None
    except GuardError as exc:
        return False, None, str(exc)

def run_config(config_id: str, cc: str, build_root: Path, verbose: bool) -> list[CaseResult]:
    cfg = load_config(CONFIG_PATHS[config_id])
    cases = _build_cases_for_config(cfg)
    guard_by_transition = {t.id: t.guard for t in cfg.transitions if t.guard is not None}
    params = {pid: p.value for pid, p in cfg.parameters.items()}

    build_dir = build_root / config_id
    build_dir.mkdir(parents=True, exist_ok=True)
    exe = build_config_binary(cfg, build_dir, cc)

    c_results = run_c_harness(exe, cases)

    results: list[CaseResult] = []
    for case, (c_ok, c_value, c_error) in zip(cases, c_results):
        guard = guard_by_transition[case.transition_id]
        python_ok, python_value, python_error = python_oracle(guard, case, params)
        result = CaseResult(
            case=case,
            python_ok=python_ok,
            python_value=python_value,
            python_error=python_error,
            c_ok=c_ok,
            c_value=c_value,
            c_error=c_error,
        )
        results.append(result)
        if verbose:
            status = "OK" if result.matches else "MISMATCH"
            print(
                f"[{status}] {case.config_id}:{case.transition_id} ({case.kind}): "
                f"python={'error:' + python_error if not python_ok else python_value} "
                f"c={'error:' + c_error if not c_ok else c_value}"
            )
    return results

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="print every case, not just failures")
    parser.add_argument(
        "--keep-build-dir",
        action="store_true",
        help="do not delete the temporary per-config build directories on exit (for debugging)",
    )
    args = parser.parse_args(argv)

    cc = find_cc()
    print(f"using C compiler: {cc}")

    tmp_ctx = tempfile.TemporaryDirectory(prefix="guard_equivalence_")
    build_root = Path(tmp_ctx.name)

    all_results: list[CaseResult] = []
    try:
        for config_id in ("config-a", "config-b", "config-c"):
            results = run_config(config_id, cc, build_root, args.verbose)
            all_results.extend(results)
            n_fail = sum(1 for r in results if not r.matches)
            print(f"{config_id}: {len(results)} cases, {n_fail} mismatches")
    finally:
        if args.keep_build_dir:
            print(f"build directories kept at: {build_root}")
            tmp_ctx._finalizer.detach()  # type: ignore[attr-defined]
        else:
            tmp_ctx.cleanup()

    failures = [r for r in all_results if not r.matches]
    print(f"\nTOTAL: {len(all_results)} cases, {len(failures)} mismatches")
    if failures:
        print("\nFailing cases:")
        for r in failures:
            c = r.case
            print(
                f"  {c.config_id}:{c.transition_id} ({c.kind}): "
                f"python={'error:' + r.python_error if not r.python_ok else r.python_value} "
                f"c={'error:' + r.c_error if not r.c_ok else r.c_value}"
            )
        return 1

    print("All C guard-evaluator results match engine.guards.evaluate_guard() exactly.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
