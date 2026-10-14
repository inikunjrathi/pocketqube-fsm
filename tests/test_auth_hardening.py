from __future__ import annotations

import pytest

from engine.auth import AUTH_COUNTER_KEY, AuthConfigError, sign_command, verify_command
from engine.fsm import step
from engine.persistence import PersistenceLayer
from test_fsm import EVENTS, STATES, make_config

SECRET = b"test-secret-key-do-not-use-in-production"
GROUND_T = [{"id": "T-01", "from": ["S-01"], "event": "E-02", "to": "S-02"}]

@pytest.fixture
def cfg(tmp_path):
    return make_config(tmp_path, states=STATES, events=EVENTS, transitions=GROUND_T)

def _send(cfg, ctx, now, counter, sig=None, state="S-01", **kw):
    if sig is None:
        sig = sign_command("E-02", now, SECRET, counter)
    return step(
        cfg, state, "E-02", ctx, now=now, ground_auth_secret=SECRET,
        command_signature=sig, replay_protection=True, command_counter=counter, **kw,
    )

def test_counter_none_keeps_legacy_message_bytes():
    import hashlib
    import hmac
    legacy = hmac.new(SECRET, b"E-13:100.0", hashlib.sha256).hexdigest()
    assert sign_command("E-13", 100.0, SECRET) == legacy
    assert sign_command("E-13", 100.0, SECRET, 7) != legacy
    assert verify_command("E-13", 100.0, sign_command("E-13", 100.0, SECRET, 7), SECRET, 7)
    assert not verify_command("E-13", 100.0, sign_command("E-13", 100.0, SECRET, 7), SECRET, 8)

@pytest.mark.parametrize("secret", [None, b""])
def test_require_auth_without_secret_raises(cfg, secret):
    with pytest.raises(AuthConfigError):
        step(cfg, "S-01", "E-02", {}, now=0, ground_auth_secret=secret, require_auth=True)
    with pytest.raises(AuthConfigError):
        step(cfg, "S-01", "E-01", {}, now=0, ground_auth_secret=secret, require_auth=True)

def test_replay_protection_without_secret_raises(cfg):
    with pytest.raises(AuthConfigError):
        step(cfg, "S-01", "E-02", {}, now=0, replay_protection=True, command_counter=1)

def test_require_auth_rejects_missing_and_bad_signature(cfg):
    for sig in (None, "0" * 64, sign_command("E-02", 0, b"wrong")):
        r = step(cfg, "S-01", "E-02", {}, now=0, ground_auth_secret=SECRET,
                 command_signature=sig, require_auth=True)
        assert r.legal is False and r.new_state == "S-01"

def test_require_auth_accepts_valid_signature(cfg):
    r = step(cfg, "S-01", "E-02", {}, now=0, ground_auth_secret=SECRET,
             command_signature=sign_command("E-02", 0, SECRET), require_auth=True)
    assert r.legal is True and r.new_state == "S-02"

def test_default_still_unauthenticated_simulation(cfg):
    r = step(cfg, "S-01", "E-02", {}, now=0)
    assert r.legal is True and AUTH_COUNTER_KEY not in r.context

def test_fresh_counter_accepted_and_recorded(cfg):
    r = _send(cfg, {}, now=0, counter=1)
    assert r.legal is True and r.context[AUTH_COUNTER_KEY] == 1

def test_duplicate_delivery_same_time_rejected(cfg):
    sig = sign_command("E-02", 0, SECRET)
    legacy = [step(cfg, "S-01", "E-02", {}, now=0, ground_auth_secret=SECRET,
                   command_signature=sig).legal for _ in range(2)]
    assert legacy == [True, True]

    first = _send(cfg, {}, now=0, counter=1)
    again = _send(cfg, first.context, now=0, counter=1)
    assert first.legal is True and again.legal is False
    assert again.context[AUTH_COUNTER_KEY] == 1

def test_delayed_delivery_of_older_command_rejected(cfg):
    newer = _send(cfg, {}, now=100, counter=5)
    older = _send(cfg, newer.context, now=100, counter=4)
    assert newer.legal is True and older.legal is False

def test_delayed_delivery_at_a_different_time_rejected(cfg):
    sig = sign_command("E-02", 100, SECRET, 1)
    assert _send(cfg, {}, now=160, counter=1, sig=sig).legal is False

def test_counter_tampering_breaks_signature(cfg):
    sig = sign_command("E-02", 0, SECRET, 1)
    assert _send(cfg, {}, now=0, counter=2, sig=sig).legal is False

@pytest.mark.parametrize("bad", [None, True, 1.0, "3"])
def test_missing_or_non_int_counter_rejected(cfg, bad):
    r = step(cfg, "S-01", "E-02", {}, now=0, ground_auth_secret=SECRET,
             command_signature=sign_command("E-02", 0, SECRET), replay_protection=True,
             command_counter=bad)
    assert r.legal is False

def test_verified_counter_consumed_even_when_no_transition_legal(cfg):
    r = _send(cfg, {}, now=0, counter=1, state="S-02")
    assert r.legal is False and r.context[AUTH_COUNTER_KEY] == 1
    assert _send(cfg, r.context, now=0, counter=1).legal is False

def test_onboard_events_ignore_counter(cfg, tmp_path):
    c = make_config(tmp_path, states=STATES, events=EVENTS,
                    transitions=[{"id": "T-01", "from": ["S-01"], "event": "E-01", "to": "S-02"}])
    r = step(c, "S-01", "E-01", {AUTH_COUNTER_KEY: 9}, now=0, ground_auth_secret=SECRET,
             replay_protection=True)
    assert r.legal is True and r.context[AUTH_COUNTER_KEY] == 9

def test_replay_after_reset_rejected_when_counter_persisted(tmp_path):
    cfg = make_config(tmp_path, states=STATES, events=EVENTS, transitions=GROUND_T + [
        {"id": "T-02", "from": ["S-01", "S-02"], "event": "E-16", "to": "reload_from_persistence"},
    ])
    store = PersistenceLayer()
    r = _send(cfg, {}, now=0, counter=1)
    store.save(r.new_state, r.context)
    reset = step(cfg, r.new_state, "E-16", r.context, now=10, persisted=store.load())
    assert reset.context[AUTH_COUNTER_KEY] == 1
    assert _send(cfg, reset.context, now=0, counter=1).legal is False

def test_replay_after_reset_without_persisted_record_is_the_documented_limit(tmp_path):
    cfg = make_config(tmp_path, states=STATES, events=EVENTS, transitions=GROUND_T + [
        {"id": "T-02", "from": ["S-01", "S-02"], "event": "E-16", "to": "reload_from_persistence"},
    ])
    r = _send(cfg, {}, now=0, counter=1)
    reset = step(cfg, r.new_state, "E-16", r.context, now=10, persisted=None)
    assert AUTH_COUNTER_KEY not in reset.context
    assert _send(cfg, reset.context, now=0, counter=1).legal is True

def test_ground_reset_to_persistence_does_not_roll_counter_back(tmp_path):
    events = [dict(e, source="ground") if e["id"] == "E-16" else e for e in EVENTS]
    cfg = make_config(tmp_path, states=STATES, events=events, transitions=[
        {"id": "T-01", "from": ["S-01"], "event": "E-01", "to": "S-02"},
        {"id": "T-02", "from": ["S-01"], "event": "E-16", "to": "reload_from_persistence"},
    ])
    persisted = {"state": "S-01", "context": {AUTH_COUNTER_KEY: 2}}
    sig = sign_command("E-16", 0, SECRET, 3)
    r = step(cfg, "S-01", "E-16", {AUTH_COUNTER_KEY: 2}, now=0, persisted=persisted,
             ground_auth_secret=SECRET, command_signature=sig,
             replay_protection=True, command_counter=3)
    assert r.legal is True and r.context[AUTH_COUNTER_KEY] == 3
