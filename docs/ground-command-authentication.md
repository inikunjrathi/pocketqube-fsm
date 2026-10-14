# Ground-Command Authentication via HMAC-SHA256 (Phase 7C)

Closes the critique finding "unauthenticated ground override": every mission
config declares `EventDef.source` (`onboard` / `ground` / `scheduler` /
`harness`, `engine/config_loader.py`), but before this phase nothing in
`engine/` or `sim/` ever read it — a `ground`-sourced event
(`GROUND_SAFE_MODE_CMD`, `GROUND_OVERRIDE_EXIT_SAFE`, `UPLINK_CMD_GENERIC`)
fired exactly like an `onboard` one, with no notion of who issued it or
whether they were allowed to.

## What is and isn't modeled

**What's real:** `engine/auth.py` implements an actual cryptographic
primitive — Python's stdlib `hmac`/`hashlib`, HMAC-SHA256, with
constant-time signature comparison (`hmac.compare_digest`) — not a
guard-grammar string check or a `source == "ground"` string comparison
standing in for security. `sign_command(event_id, now, secret_key)` signs
the exact string `f"{event_id}:{now}"`; `verify_command()` checks a
candidate signature against it. Binding the signature to both the event ID
and the simulated timestamp means a captured signature for one command
cannot be replayed against a different event, or against the same event at
a different time.

**What's explicitly still out of scope, unchanged from the project plan**
(section 9: "Flight qualification, RF implementation ... other programmes'
tracks"): real RF/flight-hardware crypto keying, key provisioning and
rotation, and physical uplink security. This is a software-layer control
inside the simulation/engine boundary only — it demonstrates that
`EventDef.source` can be made to actually matter to dispatch, not that this
codebase now specifies a flight-qualified command-authentication system.
By default there is no replay protection: `now` must match exactly, which
the driver (the only caller that fires ground events during a simulation)
always satisfies by construction since it signs and dispatches in the same
tick, but the same signed message delivered twice at the same `now` is
accepted twice. The opt-in `replay_protection` mode below closes that gap.

## Enforcement point

`engine/fsm.py::step()` gained two new keyword-only parameters:

- `ground_auth_secret: bytes | None = None`
- `command_signature: str | None = None`

When `ground_auth_secret` is `None` (the default, and every call site in
this codebase before Phase C), `EventDef.source` is not consulted at all —
byte-identical to pre-Phase-C behavior. When a secret **is** configured,
any event whose `EventDef.source == "ground"` must additionally pass
`engine.auth.verify_command(event_id, now, command_signature,
ground_auth_secret)`; failing that check makes the attempt indistinguishable
from "no legal transition" (`StepResult.legal = False`), regardless of
whether its guard would otherwise have passed. Non-`ground` events are
never gated, even when a secret is configured.

`sim/driver.py::run_simulation()` gained a matching optional
`ground_auth_secret` parameter, threaded through `_try_fire()` and
`_maybe_recover_from_safe_mode()` — the only place this driver ever fires a
ground-sourced event is `GROUND_OVERRIDE_EXIT_SAFE`, the SAFE_MODE recovery
path modeled in `sim/driver.py`'s tick loop. The driver models the
legitimate ground station: whenever a secret is configured, it signs its
own attempt with that same key before calling `step()`, so a correctly
configured simulation authenticates every ground command it issues.

## Opt-in hardening: `require_auth` and `replay_protection`

Added after external review (points 5.1 and 5.2). Both are keyword-only
`step()` parameters that default to `False`, so every existing call site,
including `sim/driver.py` and the recorded 35,763-call C-port trace,
behaves exactly as before. That was checked by re-capturing the seed-42 Config A
trace with the modified engine; it is line-for-line identical to
`mcu/host_bridge/evidence/task8_baseline_seed42/config-a/python_trace.jsonl.gz`.

- **No secret means unauthenticated simulation, and only by default.**
  Omitting `ground_auth_secret` still skips authentication entirely. That
  default exists only for simulation. `require_auth=True` fails closed:
  `step()` raises `engine.auth.AuthConfigError` before evaluating anything
  if the secret is `None` or empty (`b""`). With a secret configured, a
  missing or invalid signature on a `ground` event gives `legal=False`,
  as before.
- **`replay_protection=True`** implies `require_auth`. A ground event
  must also carry `command_counter`, an `int >= 0` that is signed into the
  message, which becomes `f"{event_id}:{now}:{counter}"` (with no counter
  the legacy two-field message is unchanged, so the C golden vectors still
  apply). The counter must be strictly greater than
  `context["_auth_last_counter"]` (`engine.auth.AUTH_COUNTER_KEY`).
  Duplicates, non-increasing values, missing or non-int counters, and a
  counter that differs from the signed one are all rejected (`legal=False`).
- A verified counter is consumed even when no transition is legal: the
  returned context carries it, so a command that was rejected by its guard
  cannot be replayed later when the guard would pass. A ground-sourced
  `reload_from_persistence` transition never rolls the counter back.
- **Persistence and reset.** The counter lives in the ordinary context
  dict, so `engine.persistence` stores it in its existing JSON record with
  no format change. It survives `RESET` only if the caller saves the
  returned context after every authenticated step, legal or not (the same
  save-after-step contract as the latches). If no valid record exists
  (`persisted=None`: cold boot, or both banks corrupt), the counter restarts
  from "none seen" and any earlier captured command is accepted again. That
  limit is tested, and documented rather than hidden.
- **Delayed delivery.** A late copy of an older command is rejected by the
  counter. A command delivered at a different `now` than it was signed for
  is rejected by the existing timestamp binding. There is still no
  tolerance window. A real uplink, where the ground cannot predict onboard
  `now` exactly, would sign a ground timestamp and check it against a
  freshness window instead.
- **C port.** `replay_protection` is implemented in Python only.
  `engine_auth.c` and `engine_fsm_step()` keep the legacy two-field
  message, and their fixed signatures carry no counter. Mirroring it would
  need a new UART `CTR` token, a counter slot in `engine_context_t` and new
  golden vectors. `require_auth` already has a C equivalent: with
  `ENGINE_GROUND_AUTH_ENABLED=1`, `engine_auth_verify_command()` fails
  closed if no secret, or an empty one, has been provisioned. A host check
  for this was added to `run_auth_equivalence.py`. Note that Python's
  `verify_command(..., b"")` accepts an empty-key HMAC while C rejects it,
  which is a deliberate divergence. On the Python side,
  `require_auth=True` covers it by refusing an empty secret.

Tests: `tests/test_auth_hardening.py` (fail-closed config errors; missing,
forged and wrong-key signatures; duplicate delivery at the same time;
delayed delivery of an older counter; delayed delivery at a different time;
counter tampering; non-int counters; consumption on illegal steps; replay
after reset with and without a persisted record; ground reset not rolling
the counter back; unchanged legacy message bytes).

## Test evidence

The security property — a forged or missing signature is rejected — is
proven exhaustively at the `engine.fsm.step()` unit level
(`tests/test_fsm.py`), where it can be tested precisely and cheaply:

- a `ground` event fires with no auth check at all when no secret is
  configured (backward compatibility);
- a `ground` event is rejected outright when a secret is configured but no
  signature is supplied;
- a `ground` event is rejected when the supplied signature was produced
  with the wrong secret key;
- a `ground` event fires normally when the supplied signature is valid;
- an `onboard` event is completely unaffected by auth enforcement, even
  when a secret is configured and no signature is supplied.

`engine/auth.py` itself is unit-tested directly (`tests/test_auth.py`):
determinism, correct-signature acceptance, and rejection of a wrong secret,
a signature for a different event, a signature for a different timestamp,
a missing signature, and a garbage signature.

At the driver/system level (`tests/test_driver.py`), two properties are
proven instead: (1) omitting `ground_auth_secret` entirely reproduces
pre-Phase-C dispatch exactly, and (2) enabling it with the correct key
produces byte-identical deliveries to running without it on the real 48h
reference scenario — auth is a real, enforced gate that never silently
changes a legitimate simulation's results, because the driver always signs
with the same key it configures `step()` to verify against.

## Parameter documentation

`P-023` (Config A) / `PB-009` (Config B), `ground_override_command_auth_model`
— see `docs/parameters.md` for the full before/after entry. Both moved from
`TBD`/`null` ("explicitly out of scope, no defensible placeholder") to
`Assumed` (`hmac-sha256`), with the original out-of-scope boundary
(flight-hardware RF/crypto) explicitly retained rather than silently
dropped.
