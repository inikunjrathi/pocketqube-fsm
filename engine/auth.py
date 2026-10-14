from __future__ import annotations

import hashlib
import hmac

AUTH_COUNTER_KEY = "_auth_last_counter"

class AuthConfigError(Exception):
    pass

def _message(event_id: str, now: float, counter: int | None) -> bytes:
    if counter is None:
        return f"{event_id}:{now}".encode("utf-8")
    return f"{event_id}:{now}:{counter}".encode("utf-8")

def sign_command(
    event_id: str, now: float, secret_key: bytes, counter: int | None = None
) -> str:
    return hmac.new(secret_key, _message(event_id, now, counter), hashlib.sha256).hexdigest()

def verify_command(
    event_id: str,
    now: float,
    signature: str | None,
    secret_key: bytes,
    counter: int | None = None,
) -> bool:
    if signature is None:
        return False
    expected = sign_command(event_id, now, secret_key, counter)
    return hmac.compare_digest(expected, signature)
