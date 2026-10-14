# R-29

from __future__ import annotations

from pathlib import Path

from engine.config_loader import load_config
from engine.fsm import step
from engine.persistence import PersistenceLayer
from tests.fixtures.drive import _drive

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_A = REPO_ROOT / "config" / "config-a.yaml"
CONFIG_B = REPO_ROOT / "config" / "config-b.yaml"

def test_r29_latch_survives_reset_after_a_torn_write_config_a():
    cfg = load_config(CONFIG_A)
    persistence = PersistenceLayer()

    state, context = _drive(
        cfg,
        [("E-01", 0), ("E-02", 1900), ("E-03", 1900), ("E-04", 1900)],
        persistence,
    )
    assert context["deployment_confirmed"] is True

    persistence.save(state, context)
    persistence.corrupt(persistence.last_written_bank)

    result = step(cfg, state, "E-16", context, now=2000, persisted=persistence.load())
    assert result.legal is True
    assert result.context["deployment_confirmed"] is True

def test_r29_latch_survives_reset_after_a_torn_write_config_b():
    cfg = load_config(CONFIG_B)
    persistence = PersistenceLayer()

    state, context = _drive(
        cfg,
        [("E-01", 0), ("E-14", 10)],
        persistence,
    )
    assert context["deployment_confirmed"] is True

    persistence.save(state, context)
    persistence.corrupt(persistence.last_written_bank)

    result = step(cfg, state, "E-12", context, now=20, persisted=persistence.load())
    assert result.legal is True
    assert result.context["deployment_confirmed"] is True

def test_reset_before_any_save_has_nothing_to_restore_and_boots_fresh():
    cfg = load_config(CONFIG_A)
    persistence = PersistenceLayer()

    state, context = cfg.initial_state, {}
    result = step(cfg, state, "E-01", context, now=0)
    state, context = result.new_state, result.context

    reset_result = step(cfg, state, "E-16", context, now=1, persisted=persistence.load())
    assert reset_result.legal is True
    assert reset_result.new_state == cfg.initial_state
    assert reset_result.context == {"ground_contact_timer": 1}
