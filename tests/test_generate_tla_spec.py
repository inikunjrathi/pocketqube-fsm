from __future__ import annotations

from pathlib import Path

import pytest

from engine.config_loader import load_config
from tools.generate_tla_spec import (
    _bool_vars,
    _expand_from_states,
    _guard_expr,
    _tla_id,
    generate_tla_config,
    generate_tla_module,
    load_independent_requirements,
    write_tla_spec,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_A = REPO_ROOT / "config" / "config-a.yaml"
CONFIG_B = REPO_ROOT / "config" / "config-b.yaml"
CONFIG_C = REPO_ROOT / "config" / "config-c.yaml"

def test_tla_id_replaces_hyphen():
    assert _tla_id("S-01") == "S_01"
    assert _tla_id("S-10") == "S_10"

def test_expand_from_states_star_means_every_state():
    cfg = load_config(CONFIG_A)
    expanded = _expand_from_states(cfg, "*")
    assert set(expanded) == set(cfg.states.keys())

def test_expand_from_states_tuple_passes_through():
    cfg = load_config(CONFIG_A)
    expanded = _expand_from_states(cfg, ("S-01", "S-02"))
    assert expanded == ("S-01", "S-02")

def _block(module: str, name: str) -> str:
    lines = module.splitlines()
    start = lines.index(f"{name} ==")
    end = lines.index("", start)
    return "\n".join(lines[start:end])

def test_bool_vars_are_latches_then_boolean_context_flags():
    assert _bool_vars(load_config(CONFIG_A)) == [
        "deployment_confirmed", "path_a_confirmed", "path_b_confirmed",
    ]
    assert _bool_vars(load_config(CONFIG_B)) == ["deployment_confirmed"]

def test_guard_expr_encodes_boolean_context_guards_and_abstracts_the_rest():
    assert _guard_expr(None) == "TRUE"
    assert _guard_expr("context.path_b_confirmed == true") == "(path_b_confirmed = TRUE)"
    assert _guard_expr("context.x != false") == "(x # FALSE)"
    assert _guard_expr("elapsed(rf_inhibit_timer) >= P-010") is None
    assert _guard_expr("battery_soc <= P-013") is None

def test_latch_clear_action_is_modelled_as_a_no_op_on_the_latch(tmp_path):
    cfg = load_config(CONFIG_B)
    t = cfg.transitions[0]
    cleared = type(t)(**{**t.__dict__, "actions": t.actions + ("set context.deployment_confirmed = false",)})
    cfg2 = type(cfg)(**{**cfg.__dict__, "transitions": (cleared,) + cfg.transitions[1:]})
    assert "deployment_confirmed' = deployment_confirmed" in _block(generate_tla_module(cfg2), "T_01")

def test_generate_tla_module_contains_every_state_and_latch():
    cfg = load_config(CONFIG_A)
    module = generate_tla_module(cfg)

    assert "MODULE config_a" in module
    for state_id in cfg.states:
        assert f'"{_tla_id(state_id)}"' in module
    for latch in cfg.latches:
        assert latch.name in module
    assert "TypeOK" in module
    assert "Init" in module
    assert "Next ==" in module
    assert "Stutter ==" in module
    assert "deployment_confirmedNeverClears" in module

def test_generate_tla_module_every_transition_becomes_an_action():
    cfg = load_config(CONFIG_A)
    module = generate_tla_module(cfg)
    for t in cfg.transitions:
        action_name = t.id.replace("-", "_")
        assert f"{action_name} ==" in module

def test_generate_tla_module_latch_set_by_transition_sets_true():
    cfg = load_config(CONFIG_A)
    module = generate_tla_module(cfg)
    block = _block(module, "T_04")
    assert "deployment_confirmed' = TRUE" in block

def test_generate_tla_module_non_set_by_transition_carries_latch_forward():
    cfg = load_config(CONFIG_A)
    module = generate_tla_module(cfg)
    block = _block(module, "T_01")
    assert "deployment_confirmed' = deployment_confirmed" in block

def test_generate_tla_module_reload_restores_the_persisted_snapshot():
    module = generate_tla_module(load_config(CONFIG_A))
    block = _block(module, "T_22")
    assert "pc' = b_pc" in block
    assert "deployment_confirmed' = b_deployment_confirmed" in block
    assert "Persist" in block

def test_first_matching_row_rule_blocks_later_rows_with_exact_guards():
    module = generate_tla_module(load_config(CONFIG_A))
    assert '~(pc \\in {"S_03"} /\\ (path_b_confirmed = FALSE))' in _block(module, "T_04")

def test_generate_tla_config_lists_typeok_and_latch_properties():
    cfg = load_config(CONFIG_A)
    tla_config = generate_tla_config(cfg)
    assert "SPECIFICATION Spec" in tla_config
    assert "INVARIANT TypeOK" in tla_config
    assert "PROPERTY deployment_confirmedDurableNeverClears" in tla_config
    assert "INVARIANT deployment_confirmedLiveOnceDurable" in tla_config
    assert "PROPERTY deployment_confirmedNeverClears" not in tla_config

def test_independent_requirements_add_properties_for_every_shipped_config():
    reqs = load_independent_requirements()
    for config_path in (CONFIG_A, CONFIG_B, CONFIG_C):
        cfg = load_config(config_path)
        tla_config = generate_tla_config(cfg, reqs)
        module = generate_tla_module(cfg, reqs)
        for name in ("PostLatchStatesHaveLatch", "GroundSafeAvailableExactly",
                     "ResetAlwaysAvailable", "SafeExitOnlyVia", "LatchRisesOnlyVia"):
            assert name in tla_config
            assert f"{name} ==" in module

def test_independent_requirement_naming_an_unknown_state_raises():
    reqs = load_independent_requirements()
    bad = {"config-b": {**reqs["config-b"], "pre_latch_states": ["NO_SUCH_STATE"]}}
    with pytest.raises(ValueError, match="unknown states"):
        generate_tla_module(load_config(CONFIG_B), bad)

def test_write_tla_spec_writes_both_files(tmp_path):
    cfg = load_config(CONFIG_A)
    tla_path, cfg_path = write_tla_spec(cfg, output_dir=tmp_path)
    assert tla_path.exists()
    assert cfg_path.exists()
    assert tla_path.name == "config_a.tla"
    assert cfg_path.name == "config_a.cfg"
    assert "MODULE config_a" in tla_path.read_text()

def test_both_shipped_configs_generate_without_error():
    for config_path in (CONFIG_A, CONFIG_B, CONFIG_C):
        cfg = load_config(config_path)
        module = generate_tla_module(cfg)
        tla_config = generate_tla_config(cfg)
        assert module
        assert tla_config
