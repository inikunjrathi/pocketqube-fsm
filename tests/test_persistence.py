# R-27 R-30

from __future__ import annotations

from engine.persistence import PersistenceLayer

def test_fresh_layer_has_nothing_to_load():
    layer = PersistenceLayer()
    assert layer.load() is None

def test_save_then_load_round_trips_state_and_context():
    layer = PersistenceLayer()
    layer.save("S-04", {"deployment_confirmed": True})
    assert layer.load() == {"state": "S-04", "context": {"deployment_confirmed": True}}

def test_successive_saves_alternate_banks():
    layer = PersistenceLayer()
    b1 = layer.save("S-01", {})
    b2 = layer.save("S-02", {})
    b3 = layer.save("S-03", {})
    assert b1 != b2
    assert b2 != b3
    assert b1 == b3

def test_last_written_bank_is_queryable():
    layer = PersistenceLayer()
    assert layer.last_written_bank is None
    bank = layer.save("S-01", {})
    assert layer.last_written_bank == bank

def test_load_returns_most_recently_written_state():
    layer = PersistenceLayer()
    layer.save("S-01", {"n": 1})
    layer.save("S-02", {"n": 2})
    assert layer.load() == {"state": "S-02", "context": {"n": 2}}

def test_corrupted_most_recent_bank_falls_back_to_other_valid_bank():
    layer = PersistenceLayer()
    bank_a = layer.save("S-01", {"deployment_confirmed": True})
    bank_b = layer.save("S-02", {"deployment_confirmed": True})
    layer.corrupt(bank_b)
    assert layer.load() == {"state": "S-01", "context": {"deployment_confirmed": True}}

def test_both_banks_corrupted_is_treated_as_no_persisted_state():
    layer = PersistenceLayer()
    bank_a = layer.save("S-01", {})
    bank_b = layer.save("S-02", {})
    layer.corrupt(bank_a)
    layer.corrupt(bank_b)
    assert layer.load() is None

def test_latch_survives_a_torn_write_on_the_bank_being_written():
    # R-29
    layer = PersistenceLayer()
    layer.save("S-03", {"deployment_confirmed": False})
    layer.save("S-04", {"deployment_confirmed": True})
    corrupted_bank = layer.save("S-04", {"deployment_confirmed": True})
    layer.corrupt(corrupted_bank)
    restored = layer.load()
    assert restored["context"]["deployment_confirmed"] is True

from engine.config_loader import load_config  # noqa: E402
from engine.fsm import step  # noqa: E402
from engine.persistence import BankRecord, _make_record  # noqa: E402
from pathlib import Path  # noqa: E402

_CONFIG_A = load_config(Path(__file__).resolve().parents[1] / "config" / "config-a.yaml")

def test_both_banks_corrupt_after_latch_reset_boots_fresh_and_loses_latch():
    layer = PersistenceLayer()
    layer.save("S-05", {"deployment_confirmed": True})
    layer.save("S-06", {"deployment_confirmed": True})
    layer.corrupt("A")
    layer.corrupt("B")
    result = step(_CONFIG_A, "S-06", "E-16", {"deployment_confirmed": True}, persisted=layer.load())
    assert result.new_state == _CONFIG_A.initial_state
    assert "deployment_confirmed" not in result.context

def test_save_after_both_banks_corrupt_continues_the_sequence_and_recovers():
    layer = PersistenceLayer()
    layer.save("S-01", {})
    layer.save("S-02", {})
    layer.corrupt("A")
    layer.corrupt("B")
    layer.save("S-03", {"n": 3})
    assert layer.load() == {"state": "S-03", "context": {"n": 3}}
    assert max(b.sequence for b in layer._banks.values()) == 2

def test_corrupting_an_empty_bank_is_a_no_op():
    layer = PersistenceLayer()
    layer.corrupt("A")
    assert layer.load() is None

def test_equal_sequence_numbers_resolve_to_bank_a():
    layer = PersistenceLayer()
    layer._banks["A"] = _make_record(7, "S-01", {"bank": "A"})
    layer._banks["B"] = _make_record(7, "S-02", {"bank": "B"})
    assert layer.load()["state"] == "S-01"

def test_higher_sequence_with_invalid_crc_is_skipped_even_if_far_newer():
    layer = PersistenceLayer()
    layer._banks["A"] = _make_record(1, "S-04", {"deployment_confirmed": True})
    bad = _make_record(10**6, "S-01", {})
    layer._banks["B"] = BankRecord(sequence=bad.sequence, payload=bad.payload, crc32=bad.crc32 ^ 1)
    assert layer.load() == {"state": "S-04", "context": {"deployment_confirmed": True}}

def test_sequence_field_is_not_covered_by_the_crc():
    layer = PersistenceLayer()
    layer.save("S-03", {"deployment_confirmed": False})
    layer.save("S-04", {"deployment_confirmed": True})
    old = layer._banks["A"]
    layer._banks["A"] = BankRecord(sequence=old.sequence | (1 << 31), payload=old.payload, crc32=old.crc32)
    assert layer._banks["A"].is_valid()
    assert layer.load() == {"state": "S-03", "context": {"deployment_confirmed": False}}

def test_sequence_has_no_32_bit_wraparound_in_python():
    layer = PersistenceLayer()
    layer._banks["A"] = _make_record(2**32 - 1, "S-01", {})
    layer._last_written = "A"
    bank = layer.save("S-02", {})
    assert bank == "B"
    assert layer._banks["B"].sequence == 2**32
    assert layer.load()["state"] == "S-02"

LATCH = ("deployment_confirmed",)

def test_latch_survives_corruption_of_newest_bank_right_after_first_latched_save():
    # R-29
    layer = PersistenceLayer(LATCH)
    layer.save("S-03", {"deployment_confirmed": False})
    layer.save("S-04", {"deployment_confirmed": True})
    for bank in ("A", "B"):
        probe = PersistenceLayer(LATCH)
        probe._banks = dict(layer._banks)
        probe.corrupt(bank)
        assert probe.load()["context"]["deployment_confirmed"] is True, bank

def test_without_latch_names_the_single_write_window_is_open():
    layer = PersistenceLayer()
    layer.save("S-03", {"deployment_confirmed": False})
    bank = layer.save("S-04", {"deployment_confirmed": True})
    layer.corrupt(bank)
    assert layer.load()["context"]["deployment_confirmed"] is False

def test_latch_survives_a_torn_mirror_write():
    # R-29
    layer = PersistenceLayer(LATCH)
    layer.save("S-03", {"deployment_confirmed": False})
    layer.save("S-04", {"deployment_confirmed": True})
    layer.corrupt(layer.last_written_bank)
    assert layer.load() == {"state": "S-04", "context": {"deployment_confirmed": True}}

def test_mirror_write_happens_once_then_saves_alternate():
    layer = PersistenceLayer(LATCH)
    layer.save("S-03", {"deployment_confirmed": False})
    layer.save("S-04", {"deployment_confirmed": True})
    sequences = sorted(r.sequence for r in layer._banks.values())
    assert sequences == [1, 2]
    banks = [layer.save("S-05", {"deployment_confirmed": True}) for _ in range(4)]
    assert banks[0] != banks[1] and banks[0] == banks[2] and banks[1] == banks[3]
    assert max(r.sequence for r in layer._banks.values()) == 6

def test_latch_survives_any_single_bank_corruption_after_any_save_sequence():
    # R-29
    states = ["S-03", "S-04", "S-05", "S-06", "S-07"]
    for latch_at in range(len(states)):
        for stop in range(latch_at + 1, len(states) + 1):
            layer = PersistenceLayer(LATCH)
            for i, state in enumerate(states[:stop]):
                layer.save(state, {"deployment_confirmed": i >= latch_at})
            for bank in ("A", "B"):
                probe = PersistenceLayer(LATCH)
                probe._banks = dict(layer._banks)
                probe.corrupt(bank)
                restored = probe.load()
                assert restored is not None
                assert restored["context"]["deployment_confirmed"] is True, (latch_at, stop, bank)
