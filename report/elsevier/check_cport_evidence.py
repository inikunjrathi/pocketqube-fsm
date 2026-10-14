import gzip, json, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
EV = REPO / "mcu/host_bridge/evidence/task8_baseline_seed42/config-a"

def load(p):
    with gzip.open(p, "rt") as f:
        return [json.loads(l) for l in f]

py = load(EV / "python_trace.jsonl.gz")
fw = load(EV / "firmware_decisions.jsonl.gz")
assert len(py) == len(fw), (len(py), len(fw))
mism = 0
for a, b in zip(py, fw):
    o, r = a["oracle"], b["response"]
    ok = (a["index"] == b["index"] and r["kind"] == "DECISION" and r["legal"] == o["legal"]
          and r["from_state"] == a["from_state"] and r["event_id"] == a["event_id"] and r["now"] == a["now"])
    if o["legal"]:
        ok = ok and r["to_state"] == o["new_state"] and r["transition_id"] == o["transition_id"] and r["actions"] == o["actions"]
    mism += not ok
legal = sum(e["oracle"]["legal"] for e in py)
print(f"archived: calls={len(py)} legal={legal} illegal={len(py)-legal} firmware_vs_oracle_mismatches={mism}")

from engine.config_loader import load_config
from mcu.host_bridge.replay_baseline import capture_baseline_trace, write_python_trace_jsonl
from mcu.host_bridge.replay_driver import CONFIG_PATHS
from tools.generate_baseline_results import DEFAULT_DT_S, DEFAULT_DURATION_S, DEFAULT_SEED

trace, res = capture_baseline_trace(load_config(CONFIG_PATHS["config-a"]),
                                    seed=DEFAULT_SEED, duration_s=DEFAULT_DURATION_S, dt_s=DEFAULT_DT_S)
tmp = Path(tempfile.mkdtemp()) / "fresh.jsonl.gz"
write_python_trace_jsonl(tmp, trace)
fresh = load(tmp)
diff = sum(x != y for x, y in zip(fresh, py)) + abs(len(fresh) - len(py))
print(f"fresh capture: calls={len(fresh)} entries_differing_from_archive={diff}")
