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
    layer.save("S-01", {"deployment_confirmed": True})
    layer._write("A", "S-02", {"deployment_confirmed": True})
    layer.corrupt("A")
    assert layer.load() == {"state": "S-01", "context": {"deployment_confirmed": True}}


def test_both_banks_corrupted_is_treated_as_no_persisted_state():
    layer = PersistenceLayer()
    layer.save("S-01", {})
    layer.save("S-02", {})
    layer.corrupt("A")
    layer.corrupt("B")
    assert layer.load() is None


def test_latch_survives_a_torn_write_on_the_bank_being_written():
    # R-29: once deployment_confirmed is set, no sequence of resets or
    layer = PersistenceLayer()
    layer.save("S-03", {"deployment_confirmed": False})
    layer.save("S-04", {"deployment_confirmed": True})
    corrupted_bank = layer.save("S-05", {"deployment_confirmed": True})
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


def test_save_after_both_banks_corrupt_restarts_the_sequence_and_recovers():
    layer = PersistenceLayer()
    layer.save("S-01", {})
    layer.save("S-02", {})
    layer.corrupt("A")
    layer.corrupt("B")
    layer.save("S-03", {"n": 3})
    assert layer.load() == {"state": "S-03", "context": {"n": 3}}
    assert sorted(r.sequence for r in layer._banks.values()) == [0, 1]


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


def test_sequence_has_no_32_bit_wraparound_in_python():
    layer = PersistenceLayer()
    layer._banks["A"] = _make_record(2**32 - 1, "S-01", {})
    layer.save("S-02", {})
    assert layer._banks["B"].sequence == 2**32
    assert layer.load()["state"] == "S-02"


def test_latch_survives_corruption_of_newest_bank_right_after_first_latched_save():
    # R-29: the window the single-write design left open. The latch is set
    layer = PersistenceLayer()
    layer.save("S-03", {"deployment_confirmed": False})
    layer.save("S-04", {"deployment_confirmed": True})
    for bank in ("A", "B"):
        probe = PersistenceLayer()
        probe._banks = dict(layer._banks)
        probe.corrupt(bank)
        assert probe.load()["context"]["deployment_confirmed"] is True, bank


def test_latch_survives_a_torn_mirror_write():
    # R-29: a RESET tearing the second (mirror) write leaves the first
    layer = PersistenceLayer()
    layer.save("S-03", {"deployment_confirmed": False})
    layer.save("S-04", {"deployment_confirmed": True})
    layer.corrupt(layer.last_written_bank)
    assert layer.load() == {"state": "S-04", "context": {"deployment_confirmed": True}}


def test_latch_survives_any_single_bank_corruption_after_any_save_sequence():
    # R-29, exhaustive over short histories: every prefix of saves after the
    states = ["S-03", "S-04", "S-05", "S-06", "S-07"]
    for latch_at in range(len(states)):
        for stop in range(latch_at + 1, len(states) + 1):
            layer = PersistenceLayer()
            for i, state in enumerate(states[:stop]):
                layer.save(state, {"deployment_confirmed": i >= latch_at})
            for bank in ("A", "B"):
                probe = PersistenceLayer()
                probe._banks = dict(layer._banks)
                probe.corrupt(bank)
                restored = probe.load()
                assert restored is not None
                assert restored["context"]["deployment_confirmed"] is True, (latch_at, stop, bank)


def _bank_writes(layer):
    writes = []
    original = layer._write

    def counting(bank, state, context):
        writes.append(bank)
        original(bank, state, context)

    layer._write = counting
    return writes


def _torn(sequence):
    return BankRecord(sequence=sequence, payload=b"\xff\x00garbage", crc32=0)


def test_unchanged_content_writes_nothing():
    layer = PersistenceLayer()
    writes = _bank_writes(layer)
    context = {"deployment_confirmed": False, "n": 1}
    first = layer.save("S-03", context)
    for _ in range(5):
        assert layer.save("S-03", dict(context)) == first
    assert writes == ["A", "B"]


def test_each_context_change_counts_as_a_change():
    layer = PersistenceLayer()
    writes = _bank_writes(layer)
    layer.save("S-03", {"n": 1})
    layer.save("S-03", {"n": 2})
    assert len(writes) == 4


def test_save_never_overwrites_the_only_valid_bank():
    layer = PersistenceLayer()
    layer.save("S-03", {"deployment_confirmed": True})
    good = layer.last_written_bank
    torn = "A" if good == "B" else "B"
    layer._banks[torn] = _torn(layer._banks[good].sequence + 1)
    writes = _bank_writes(layer)
    layer.save("S-04", {"n": 1})
    assert writes == [torn, good]
    assert layer.load()["state"] == "S-04"


def test_garbage_sequence_in_an_invalid_bank_is_ignored():
    layer = PersistenceLayer()
    layer._banks["A"] = _make_record(5, "S-01", {})
    layer._banks["B"] = _torn(2**32 - 1)
    layer.save("S-02", {})
    assert layer._banks["B"].sequence == 6
    assert layer.load()["state"] == "S-02"


def test_baseline_run_writes_flash_only_on_change():
    from sim.driver import run_simulation

    writes = []
    original = PersistenceLayer._write

    def counting(self, bank, state, context):
        writes.append(bank)
        original(self, bank, state, context)

    PersistenceLayer._write = counting
    try:
        run_simulation(_CONFIG_A, duration_s=12 * 3600.0, dt_s=10.0, seed=42)
    finally:
        PersistenceLayer._write = original
    assert 0 < len(writes) < 100


def test_each_change_writes_the_older_bank_then_the_newer():
    layer = PersistenceLayer()
    writes = _bank_writes(layer)
    layer.save("S-01", {})
    layer.save("S-02", {})
    assert writes == ["A", "B", "A", "B"]
    assert sorted(r.sequence for r in layer._banks.values()) == [2, 3]


def test_either_bank_restores_the_last_committed_record():
    layer = PersistenceLayer()
    layer.save("S-03", {"deployment_confirmed": False})
    layer.save("S-04", {"deployment_confirmed": True})
    for bank in ("A", "B"):
        probe = PersistenceLayer()
        probe._banks = dict(layer._banks)
        probe.corrupt(bank)
        assert probe.load() == {"state": "S-04", "context": {"deployment_confirmed": True}}


def test_unchanged_save_repairs_a_damaged_bank_with_one_write():
    layer = PersistenceLayer()
    layer.save("S-02", {})
    layer.corrupt("A")
    writes = _bank_writes(layer)
    layer.save("S-02", {})
    assert writes == ["A"]
    layer.corrupt("B")
    assert layer.load()["state"] == "S-02"


def test_save_after_a_torn_second_write_repairs_the_stale_bank():
    layer = PersistenceLayer()
    layer.save("S-01", {})
    writes = _bank_writes(layer)
    layer._write("A", "S-02", {})
    layer._banks["B"] = _torn(layer._banks["A"].sequence + 1)
    assert layer.load()["state"] == "S-02"
    layer.save("S-02", {})
    assert writes == ["A", "B"]
    assert all(r.is_valid() for r in layer._banks.values())


def test_flipped_sequence_invalidates_the_record():
    layer = PersistenceLayer()
    layer._banks["A"] = _make_record(0, "S-03", {})
    layer._banks["B"] = _make_record(1, "S-04", {})
    stale = layer._banks["A"]
    layer._banks["A"] = BankRecord(sequence=stale.sequence | (1 << 31), payload=stale.payload, crc32=stale.crc32)
    assert not layer._banks["A"].is_valid()
    assert layer.load()["state"] == "S-04"
