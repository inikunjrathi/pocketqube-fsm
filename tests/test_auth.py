from __future__ import annotations

from engine.auth import sign_command, verify_command

SECRET = b"test-secret-key-do-not-use-in-production"
OTHER_SECRET = b"a-different-secret-key"

def test_sign_command_is_deterministic():
    sig1 = sign_command("E-13", 100.0, SECRET)
    sig2 = sign_command("E-13", 100.0, SECRET)
    assert sig1 == sig2

def test_sign_command_returns_hex_sha256_length_string():
    sig = sign_command("E-13", 100.0, SECRET)
    assert isinstance(sig, str)
    assert len(sig) == 64
    int(sig, 16)

def test_verify_command_accepts_correct_signature():
    sig = sign_command("E-13", 100.0, SECRET)
    assert verify_command("E-13", 100.0, sig, SECRET) is True

def test_verify_command_rejects_wrong_secret_key():
    sig = sign_command("E-13", 100.0, SECRET)
    assert verify_command("E-13", 100.0, sig, OTHER_SECRET) is False

def test_verify_command_rejects_signature_for_different_event():
    sig = sign_command("E-13", 100.0, SECRET)
    assert verify_command("E-14", 100.0, sig, SECRET) is False

def test_verify_command_rejects_signature_for_different_time():
    sig = sign_command("E-13", 100.0, SECRET)
    assert verify_command("E-13", 200.0, sig, SECRET) is False

def test_verify_command_rejects_none_signature():
    assert verify_command("E-13", 100.0, None, SECRET) is False

def test_verify_command_rejects_garbage_signature():
    assert verify_command("E-13", 100.0, "not-a-real-signature", SECRET) is False
