from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from engine.config_loader import load_config
from tools.codegen_c_table import (
    CodegenError,
    c_ident,
    generate_tables,
    render_header,
    render_source,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_A = load_config(REPO_ROOT / "config" / "config-a.yaml")
CONFIG_B = load_config(REPO_ROOT / "config" / "config-b.yaml")
CONFIG_C = load_config(REPO_ROOT / "config" / "config-c.yaml")
ALL_CONFIGS = (CONFIG_A, CONFIG_B, CONFIG_C)

CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")

def make_config(tmp_path: Path, *, states, events, transitions, parameters=None) -> "Config":
    conflict_resolution = [
        {"rank": i + 1, "category": f"cat-{e['id']}", "member_events": [e["id"]]}
        for i, e in enumerate(events)
    ]
    raw = {
        "meta": {"config_id": "fixture", "name": "Fixture", "description": "", "version": "0.0.1"},
        "states": states,
        "events": events,
        "transitions": transitions,
        "parameters": parameters or [],
        "conflict_resolution": conflict_resolution,
    }
    path = tmp_path / "fixture.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return load_config(path)

@pytest.mark.parametrize("cfg", ALL_CONFIGS, ids=lambda c: c.config_id)
def test_transition_row_count_matches_source(cfg):
    tables = generate_tables(cfg)
    assert len(tables.transitions) == len(cfg.transitions)

@pytest.mark.parametrize("cfg", ALL_CONFIGS, ids=lambda c: c.config_id)
def test_transition_row_order_and_ids_match_source_exactly(cfg):
    tables = generate_tables(cfg)
    for row, source in zip(tables.transitions, cfg.transitions):
        assert row.id == source.id

@pytest.mark.parametrize("cfg", ALL_CONFIGS, ids=lambda c: c.config_id)
def test_every_row_matches_its_source_transitiondef_field_for_field(cfg):
    tables = generate_tables(cfg)
    all_state_ids = frozenset(cfg.states)
    for row, source in zip(tables.transitions, cfg.transitions):
        assert row.from_wildcard == (source.from_states == "*")
        if row.from_wildcard:
            assert row.from_mask == (1 << len(tables.state_ids)) - 1
        else:
            expected_mask = 0
            for sid in source.from_states:
                expected_mask |= 1 << tables.state_ids.index(sid)
            assert row.from_mask == expected_mask
        for i, sid in enumerate(tables.state_ids):
            bit_set = bool(row.from_mask & (1 << i))
            assert bit_set == source.applies_from(sid, all_state_ids)

        assert tables.event_ids[row.event_index] == source.event
        assert row.guard.has_guard == (source.guard is not None)

        if source.to is None:
            assert row.target_kind == "SELF"
        elif source.to == "reload_from_persistence":
            assert row.target_kind == "RELOAD"
        else:
            assert row.target_kind == "STATE"
            assert tables.state_ids[row.to_state_index] == source.to

        assert len(row.actions) == len(source.actions)
        for a, raw in zip(row.actions, source.actions):
            assert a.raw == raw

@pytest.mark.parametrize("cfg", ALL_CONFIGS, ids=lambda c: c.config_id)
def test_states_and_events_preserve_yaml_declaration_order(cfg):
    tables = generate_tables(cfg)
    assert tables.state_ids == tuple(cfg.states.keys())
    assert tables.event_ids == tuple(cfg.events.keys())
    assert tables.state_ids[tables.initial_state_index] == cfg.initial_state

def test_config_a_t02_guard_is_elapsed_rf_inhibit_timer_ge_p010():
    tables = generate_tables(CONFIG_A)
    row = next(r for r in tables.transitions if r.id == "T-02")
    assert row.guard.has_guard
    assert row.guard.op == ">="
    assert row.guard.lhs.kind == "ELAPSED"
    assert row.guard.lhs.name == "rf_inhibit_timer"
    assert row.guard.rhs.kind == "PARAM"
    assert tables.parameters[row.guard.rhs.param_index].id == "P-010"
    assert tables.parameters[row.guard.rhs.param_index].value == 900.0

def test_config_a_t22_wildcard_reset_targets_reload_persistence():
    tables = generate_tables(CONFIG_A)
    row = next(r for r in tables.transitions if r.id == "T-22")
    assert row.from_wildcard
    assert row.from_mask == (1 << len(tables.state_ids)) - 1
    assert row.target_kind == "RELOAD"

def test_config_a_t23_wildcard_noop_is_self_loop():
    tables = generate_tables(CONFIG_A)
    row = next(r for r in tables.transitions if r.id == "T-23")
    assert row.target_kind == "SELF"

@pytest.mark.parametrize("cfg", ALL_CONFIGS, ids=lambda c: c.config_id)
def test_latch_rows_match_source_latchdefs_one_to_one(cfg):
    tables = generate_tables(cfg)
    assert len(tables.latches) == len(cfg.latches)
    for row, source in zip(tables.latches, cfg.latches):
        assert row.name == source.name

@pytest.mark.parametrize("cfg", ALL_CONFIGS, ids=lambda c: c.config_id)
def test_latch_set_by_indices_resolve_to_the_correct_transition_ids(cfg):
    tables = generate_tables(cfg)
    transition_ids = [t.id for t in tables.transitions]
    for row, source in zip(tables.latches, cfg.latches):
        resolved_ids = tuple(transition_ids[i] for i in row.set_by_indices)
        assert resolved_ids == source.set_by

def test_config_a_deployment_confirmed_latch_set_by_t04_and_t06():
    tables = generate_tables(CONFIG_A)
    latch = next(l for l in tables.latches if l.name == "deployment_confirmed")
    transition_ids = [t.id for t in tables.transitions]
    resolved = tuple(transition_ids[i] for i in latch.set_by_indices)
    assert resolved == ("T-04", "T-06")

def test_render_header_declares_latch_def_t_and_g_latches(cfg=CONFIG_A):
    tables = generate_tables(cfg)
    header = render_header(cfg, tables)
    assert "latch_def_t" in header
    assert "extern const latch_def_t g_latches[];" in header
    assert "extern const uint32_t g_latches_count;" in header

def test_render_source_contains_one_latch_row_per_source_latchdef(cfg=CONFIG_A):
    tables = generate_tables(cfg)
    source = render_source(cfg, tables)
    for latch in cfg.latches:
        assert f'.name = "{latch.name}"' in source
    assert f"const uint32_t g_latches_count = {len(cfg.latches)};" in source

def test_config_a_parameters_are_exactly_the_guard_referenced_numeric_ids():
    tables = generate_tables(CONFIG_A)
    ids = {p.id for p in tables.parameters}
    assert ids == {"P-010", "P-013", "P-015", "P-019", "P-025"}

def test_config_b_parameters_are_exactly_the_guard_referenced_numeric_ids():
    tables = generate_tables(CONFIG_B)
    ids = {p.id for p in tables.parameters}
    assert ids == {"PB-002", "PB-003", "PB-005", "PB-006", "PB-011"}

def test_config_c_parameters_are_exactly_the_guard_referenced_numeric_ids():
    tables = generate_tables(CONFIG_C)
    ids = {p.id for p in tables.parameters}
    assert ids == {"PC-002", "PC-003", "PC-005", "PC-006", "PC-011", "PC-012"}

@pytest.mark.parametrize(
    "pid",
    ["P-001", "P-002", "P-011", "P-012", "P-014", "P-016", "P-017", "P-018", "P-020", "P-023", "P-024"],
)
def test_non_guard_referenced_config_a_parameters_are_dropped(pid):
    assert pid in CONFIG_A.parameters
    tables = generate_tables(CONFIG_A)
    assert pid not in {p.id for p in tables.parameters}

def test_parameters_table_is_sorted_for_deterministic_output():
    tables = generate_tables(CONFIG_A)
    ids = [p.id for p in tables.parameters]
    assert ids == sorted(ids)

def test_guard_referencing_unknown_parameter_id_hard_errors(tmp_path):
    cfg = make_config(
        tmp_path,
        states=[{"id": "S-01", "name": "A", "is_initial": True}, {"id": "S-02", "name": "B", "is_initial": False}],
        events=[{"id": "E-01", "name": "GO", "source": "onboard"}],
        transitions=[
            {"id": "T-01", "from": ["S-01"], "event": "E-01", "guard": "fault_count >= P-999", "to": "S-02"},
        ],
    )
    with pytest.raises(CodegenError, match="unknown parameter id"):
        generate_tables(cfg)

def test_guard_referencing_non_numeric_parameter_hard_errors(tmp_path):
    cfg = make_config(
        tmp_path,
        states=[{"id": "S-01", "name": "A", "is_initial": True}, {"id": "S-02", "name": "B", "is_initial": False}],
        events=[{"id": "E-01", "name": "GO", "source": "onboard"}],
        transitions=[
            {"id": "T-01", "from": ["S-01"], "event": "E-01", "guard": "fault_count >= P-001", "to": "S-02"},
        ],
        parameters=[{"id": "P-001", "name": "not_numeric", "value": "high"}],
    )
    with pytest.raises(CodegenError, match="not numeric"):
        generate_tables(cfg)

@pytest.mark.parametrize("cfg", ALL_CONFIGS, ids=lambda c: c.config_id)
def test_every_elapsed_operand_resolves_to_a_valid_timer_index(cfg):
    tables = generate_tables(cfg)
    for row in tables.transitions:
        if not row.guard.has_guard:
            continue
        for operand in (row.guard.lhs, row.guard.rhs):
            if operand.kind == "ELAPSED":
                assert 0 <= operand.timer_index < len(tables.timers)
                assert tables.timers[operand.timer_index] == operand.name

@pytest.mark.parametrize("cfg", ALL_CONFIGS, ids=lambda c: c.config_id)
def test_every_start_timer_action_referenced_by_a_guard_gets_a_matching_index(cfg):
    tables = generate_tables(cfg)
    elapsed_index_by_name = {
        op.name: op.timer_index
        for row in tables.transitions
        if row.guard.has_guard
        for op in (row.guard.lhs, row.guard.rhs)
        if op.kind == "ELAPSED"
    }
    for row in tables.transitions:
        for action in row.actions:
            if action.kind != "START_TIMER":
                continue
            if action.timer_name in elapsed_index_by_name:
                assert action.timer_index == elapsed_index_by_name[action.timer_name]
            else:
                assert action.timer_index == -1

def test_config_a_rf_inhibit_timer_start_and_elapsed_share_one_index():
    tables = generate_tables(CONFIG_A)
    start_action = next(
        a for row in tables.transitions for a in row.actions if a.timer_name == "rf_inhibit_timer"
    )
    elapsed_operand = next(
        op
        for row in tables.transitions
        if row.guard.has_guard
        for op in (row.guard.lhs, row.guard.rhs)
        if op.kind == "ELAPSED" and op.name == "rf_inhibit_timer"
    )
    assert start_action.timer_index == elapsed_operand.timer_index
    assert tables.timers[start_action.timer_index] == "rf_inhibit_timer"

def test_elapsed_without_matching_start_timer_hard_errors(tmp_path):
    cfg = make_config(
        tmp_path,
        states=[{"id": "S-01", "name": "A", "is_initial": True}, {"id": "S-02", "name": "B", "is_initial": False}],
        events=[{"id": "E-01", "name": "GO", "source": "onboard"}, {"id": "E-02", "name": "CHECK", "source": "onboard"}],
        transitions=[
            {"id": "T-01", "from": ["S-01"], "event": "E-01", "to": "S-02", "actions": ["start_switch_debounce_timer"]},
            {"id": "T-02", "from": ["S-02"], "event": "E-02", "guard": "elapsed(switch_debounce) >= P-001", "to": "S-01"},
        ],
        parameters=[{"id": "P-001", "name": "thresh", "value": 5}],
    )
    with pytest.raises(CodegenError, match=r"elapsed\(\)/start_ mismatch"):
        generate_tables(cfg)

def test_elapsed_with_matching_start_timer_on_a_different_transition_is_fine(tmp_path):
    cfg = make_config(
        tmp_path,
        states=[{"id": "S-01", "name": "A", "is_initial": True}, {"id": "S-02", "name": "B", "is_initial": False}],
        events=[{"id": "E-01", "name": "GO", "source": "onboard"}, {"id": "E-02", "name": "CHECK", "source": "onboard"}],
        transitions=[
            {"id": "T-01", "from": ["S-01"], "event": "E-01", "to": "S-02", "actions": ["start_my_timer"]},
            {"id": "T-02", "from": ["S-02"], "event": "E-02", "guard": "elapsed(my_timer) >= P-001", "to": "S-01"},
        ],
        parameters=[{"id": "P-001", "name": "thresh", "value": 5}],
    )
    tables = generate_tables(cfg)
    assert tables.timers == ("my_timer",)

@pytest.mark.parametrize("cfg", ALL_CONFIGS, ids=lambda c: c.config_id)
def test_render_header_declares_every_state_and_event_enum(cfg):
    tables = generate_tables(cfg)
    header = render_header(cfg, tables)
    for sid in tables.state_ids:
        assert f"STATE_{c_ident(sid)}" in header
    for eid in tables.event_ids:
        assert f"EVENT_{c_ident(eid)}" in header
    assert "AUTO-GENERATED FILE -- DO NOT HAND-EDIT" in header

@pytest.mark.parametrize("cfg", ALL_CONFIGS, ids=lambda c: c.config_id)
def test_render_source_contains_one_row_per_transition(cfg):
    tables = generate_tables(cfg)
    source = render_source(cfg, tables)
    for t in cfg.transitions:
        assert f'.id = "{t.id}"' in source

@pytest.mark.skipif(CC is None, reason="no C compiler (cc/gcc/clang) available on this host")
@pytest.mark.parametrize("cfg", ALL_CONFIGS, ids=lambda c: c.config_id)
def test_generated_c_compiles_warning_free(cfg, tmp_path):
    tables = generate_tables(cfg)
    (tmp_path / "engine_config_table.h").write_text(render_header(cfg, tables))
    (tmp_path / "engine_config_table.c").write_text(render_source(cfg, tables))
    result = subprocess.run(
        [
            CC,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-Werror",
            "-c",
            str(tmp_path / "engine_config_table.c"),
            "-I",
            str(tmp_path),
            "-o",
            str(tmp_path / "engine_config_table.o"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

@pytest.mark.skipif(CC is None, reason="no C compiler (cc/gcc/clang) available on this host")
def test_generated_c_links_and_reports_expected_counts(tmp_path):
    tables = generate_tables(CONFIG_A)
    (tmp_path / "engine_config_table.h").write_text(render_header(CONFIG_A, tables))
    (tmp_path / "engine_config_table.c").write_text(render_source(CONFIG_A, tables))
    main_c = tmp_path / "main.c"
    main_c.write_text(
        '#include "engine_config_table.h"\n'
        "#include <stdio.h>\n"
        "int main(void) {\n"
        '    printf("%u %u %u\\n", (unsigned)STATE_COUNT, g_parameters_count, g_transitions_count);\n'
        "    return 0;\n"
        "}\n"
    )
    exe = tmp_path / "smoke"
    result = subprocess.run(
        [CC, "-std=c11", "-Wall", "-Wextra", "-Werror", str(main_c), str(tmp_path / "engine_config_table.c"), "-o", str(exe)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    run_result = subprocess.run([str(exe)], capture_output=True, text=True)
    assert run_result.returncode == 0
    assert run_result.stdout.strip() == f"{len(CONFIG_A.states)} {len(tables.parameters)} {len(tables.transitions)}"

def test_runs_as_a_direct_script_against_all_three_configs(tmp_path):
    for config_name in ("config-a", "config-b", "config-c"):
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "tools" / "codegen_c_table.py"),
                str(REPO_ROOT / "config" / f"{config_name}.yaml"),
                "--out-dir",
                str(tmp_path / config_name),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert (tmp_path / config_name / "engine_config_table.c").exists()
        assert (tmp_path / config_name / "engine_config_table.h").exists()

def test_default_invocation_targets_config_a_and_the_canonical_mcu_output_dir():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "codegen_c_table.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "config-a" in result.stdout
    out_dir = REPO_ROOT / "mcu" / "firmware" / "app" / "src"
    assert (out_dir / "engine_config_table.c").exists()
    assert (out_dir / "engine_config_table.h").exists()
