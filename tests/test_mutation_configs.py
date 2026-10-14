from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_IDS = ("config-a", "config-b", "config-c")
OPERATORS = ("==", "!=", ">=", "<=", "<", ">")
_OP_RE = re.compile(r"==|!=|>=|<=|<|>")
JAR = REPO_ROOT / "tools" / "vendor" / "tla2tools.jar"
HARNESS = "tests/test_mutation_configs.py"
NEW_TEST_FILES = ("tests/test_requirements_independent.py", "tests/test_guard_negative.py")

def raw_config(config_id: str) -> dict:
    return yaml.safe_load((REPO_ROOT / "config" / f"{config_id}.yaml").read_text())

def mutants(config_id: str):
    base = raw_config(config_id)
    state_ids = [s["id"] for s in base["states"]]
    for i, t in enumerate(base["transitions"]):
        m = copy.deepcopy(base)
        del m["transitions"][i]
        for latch in m.get("latches", []):
            latch["set_by"] = [x for x in latch["set_by"] if x != t["id"]]
        yield f"{config_id}:drop:{t['id']}", "drop", m

        if t.get("to") in state_ids:
            new_to = state_ids[(state_ids.index(t["to"]) + 1) % len(state_ids)]
            m = copy.deepcopy(base)
            m["transitions"][i]["to"] = new_to
            yield f"{config_id}:retarget:{t['id']}->{new_to}", "retarget", m

        m = copy.deepcopy(base)
        set_by = m["latches"][0]["set_by"]
        if t["id"] in set_by:
            set_by.remove(t["id"])
        else:
            set_by.append(t["id"])
        yield f"{config_id}:latch:{t['id']}", "latch", m

        if t.get("guard"):
            op = _OP_RE.search(t["guard"]).group(0)
            for new_op in OPERATORS:
                if new_op != op:
                    m = copy.deepcopy(base)
                    m["transitions"][i]["guard"] = _OP_RE.sub(new_op, t["guard"], count=1)
                    yield f"{config_id}:guard:{t['id']}:{op}->{new_op}", "guard", m

    ranks = base["conflict_resolution"]
    for i in range(len(ranks) - 1):
        m = copy.deepcopy(base)
        cr = m["conflict_resolution"]
        cr[i]["member_events"], cr[i + 1]["member_events"] = cr[i + 1]["member_events"], cr[i]["member_events"]
        yield f"{config_id}:rank:{ranks[i]['rank']}<->{ranks[i + 1]['rank']}", "rank", m

def _load(raw: dict, tmp: Path):
    from engine.config_loader import load_config

    path = tmp / f"{raw['meta']['config_id']}.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return load_config(path)

def _explorer_violations(cfg) -> set[str]:
    from tests.test_requirements_independent import REQUIREMENTS, check, explore

    nodes, edges = explore(cfg)
    return {k for k, v in check(cfg, nodes, edges, REQUIREMENTS[cfg.config_id]).items() if v}

def _tlc_violations(cfg, independent: bool, exclude: frozenset[str] = frozenset()) -> str | None:
    from tools.generate_tla_spec import generate_tla_config, generate_tla_module, load_independent_requirements

    reqs = load_independent_requirements() if independent else None
    with tempfile.TemporaryDirectory() as d:
        name = cfg.config_id.replace("-", "_")
        try:
            (Path(d) / f"{name}.tla").write_text(generate_tla_module(cfg, reqs))
            tla_cfg = generate_tla_config(cfg, reqs)
        except Exception as exc:
            return f"generator: {exc}"
        tla_cfg = "\n".join(l for l in tla_cfg.splitlines() if l.split()[-1] not in exclude)
        (Path(d) / f"{name}.cfg").write_text(tla_cfg + "\n")
        for _ in range(3):
            out = subprocess.run(
                ["java", f"-Djava.io.tmpdir={d}", "-cp", str(JAR), "tlc2.TLC", "-metadir", f"{d}/meta",
                 "-config", f"{name}.cfg", f"{name}.tla"],
                cwd=d, capture_output=True, text=True, timeout=600,
            ).stdout
            if "Parsing or semantic analysis failed" not in out:
                break
    if "No error has been found" in out:
        return None
    m = re.search(r"(Invariant|Temporal property|Property) (\w+) is violated|Deadlock|Error: (.*)", out)
    return m.group(0) if m else "TLC error"

def _baseline():
    from engine.config_loader import load_config

    out = {}
    for cid in CONFIG_IDS:
        cfg = load_config(REPO_ROOT / "config" / f"{cid}.yaml")
        out[cid] = _explorer_violations(cfg)
    return out

def evaluate(mutant_id: str, raw: dict, baseline: dict, tlc: bool) -> dict:
    cid = raw["meta"]["config_id"]
    res = {"id": mutant_id}
    with tempfile.TemporaryDirectory() as d:
        try:
            cfg = _load(raw, Path(d))
        except Exception as exc:
            res["loader"] = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
            return res
    res["loader"] = None
    try:
        new = _explorer_violations(cfg) - baseline[cid]
        res["explorer"] = sorted(new) or None
    except Exception as exc:
        res["explorer"] = f"crash: {type(exc).__name__}: {exc}"
    if tlc:
        exclude = frozenset(baseline[cid])
        res["tlc_generic"] = _tlc_violations(cfg, independent=False)
        res["tlc_indep"] = _tlc_violations(cfg, independent=True, exclude=exclude)
    return res

_COPY_IGNORE = shutil.ignore_patterns(".git", ".venv", "report", "build",
                                      "__pycache__", ".pytest_cache")

def _suite_cmd():
    return [str(REPO_ROOT / ".venv" / "bin" / "python"), "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "-rfE", f"--ignore={HARNESS}"]

def run_suite(raw: dict | None, workdir: Path, deselect: list[str]) -> dict:
    shutil.copytree(REPO_ROOT, workdir, ignore=_COPY_IGNORE, symlinks=True)
    if raw is not None:
        path = workdir / "config" / f"{raw['meta']['config_id']}.yaml"
        path.write_text(yaml.safe_dump(raw, sort_keys=False))
    cmd = _suite_cmd() + [f"--deselect={t}" for t in deselect]
    try:
        p = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=900)
        failed = re.findall(r"^(?:FAILED|ERROR) (\S+)", p.stdout, re.M)
        result = {"rc": p.returncode, "failed": failed,
                  "tail": p.stdout.strip().splitlines()[-1] if p.stdout.strip() else p.stderr[-300:]}
    except subprocess.TimeoutExpired:
        result = {"rc": "timeout", "failed": [], "tail": "timeout"}
    shutil.rmtree(workdir, ignore_errors=True)
    return result

def main(argv: list[str]) -> None:
    suite = "--suite" in argv
    jobs = int(argv[argv.index("--jobs") + 1]) if "--jobs" in argv else 8
    tlc = JAR.exists() and shutil.which("java") is not None
    baseline = _baseline()
    all_mutants = [(mid, cls, raw) for cid in CONFIG_IDS for mid, cls, raw in mutants(cid)]
    print(f"{len(all_mutants)} mutants; tlc={tlc}; suite={suite}; baseline explorer violations={baseline}")

    with ThreadPoolExecutor(jobs) as pool:
        results = list(pool.map(lambda m: {**evaluate(m[0], m[2], baseline, tlc), "class": m[1]}, all_mutants))

    deselect: list[str] = []
    out_path = REPO_ROOT / "build" / "review" / "mutation-results.json"
    if "--reuse-suite" in argv and out_path.exists():
        old = json.loads(out_path.read_text())
        deselect = old["deselected_baseline_failures"]
        prev = {r["id"]: r for r in old["results"]}
        for r in results:
            r.update({k: v for k, v in prev.get(r["id"], {}).items() if k.startswith("suite")})
    if suite:
        scratch = Path(tempfile.mkdtemp(prefix="mutsuite-"))
        base = run_suite(None, scratch / "baseline", [])
        deselect = base["failed"]
        print("suite baseline:", base)
        todo = [(r, raw) for r, (_, _, raw) in zip(results, all_mutants) if r["loader"] is None]
        with ThreadPoolExecutor(jobs) as pool:
            outs = pool.map(lambda x: run_suite(x[1], scratch / x[0]["id"].replace(":", "_").replace(">", ""), deselect), todo)
            for (r, _), out in zip(todo, outs):
                new = [f for f in out["failed"] if f.split("::")[0] in NEW_TEST_FILES]
                old = [f for f in out["failed"] if f not in new]
                if out["rc"] not in (0, 1) and not out["failed"]:
                    old = [str(out["tail"])]
                r["suite_existing"] = old[:5] or None
                r["suite_new"] = new[:5] or None

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"deselected_baseline_failures": deselect, "results": results}, indent=1))
    print(f"wrote {out_path}")

def test_every_mutation_class_produces_mutants_for_every_config():
    for cid in CONFIG_IDS:
        classes = {cls for _, cls, _ in mutants(cid)}
        assert classes == {"drop", "retarget", "latch", "guard", "rank"}

def test_mutants_differ_from_the_shipped_config_and_have_unique_ids():
    for cid in CONFIG_IDS:
        base = raw_config(cid)
        ids = [mid for mid, _, raw in mutants(cid) if raw != base]
        assert len(ids) == len(set(ids)) == sum(1 for _ in mutants(cid))

def test_explorer_kills_dropping_the_ground_safe_mode_transition():
    baseline = _baseline()
    raw = raw_config("config-b")
    tid = next(t["id"] for t in raw["transitions"] if t["event"] == "E-10")
    mid, _, mutant = next(m for m in mutants("config-b") if m[0] == f"config-b:drop:{tid}")
    assert "GroundSafeAvailableExactly" in evaluate(mid, mutant, baseline, tlc=False)["explorer"]

def test_explorer_kills_setting_the_latch_on_separation():
    baseline = _baseline()
    m = next(m for m in mutants("config-b") if m[0] == "config-b:latch:T-01")
    assert "LatchRisesOnlyVia" in evaluate(m[0], m[2], baseline, tlc=False)["explorer"]

if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT))
    main(sys.argv[1:])
