from __future__ import annotations

import json
import zlib
from dataclasses import dataclass
from typing import Any, Optional

_BANK_NAMES = ("A", "B")

@dataclass(frozen=True)
class BankRecord:
    sequence: int
    payload: bytes
    crc32: int

    def is_valid(self) -> bool:
        return zlib.crc32(self.payload) == self.crc32

def _serialize(sequence: int, state: str, context: dict) -> bytes:
    return json.dumps(
        {"sequence": sequence, "state": state, "context": context}, sort_keys=True
    ).encode("utf-8")

def _make_record(sequence: int, state: str, context: dict) -> BankRecord:
    payload = _serialize(sequence, state, context)
    return BankRecord(sequence=sequence, payload=payload, crc32=zlib.crc32(payload))

class PersistenceLayer:
    def __init__(self) -> None:
        self._banks: dict[str, Optional[BankRecord]] = {name: None for name in _BANK_NAMES}
        self._last_written: Optional[str] = None

    def save(self, state: str, context: dict) -> str:
        target = "B" if self._last_written == "A" else "A"
        sequence = self._next_sequence()
        self._banks[target] = _make_record(sequence, state, context)
        self._last_written = target
        return target

    def load(self) -> Optional[dict[str, Any]]:
        valid = [b for b in self._banks.values() if b is not None and b.is_valid()]
        if not valid:
            return None
        best = max(valid, key=lambda b: b.sequence)
        data = json.loads(best.payload)
        return {"state": data["state"], "context": data["context"]}

    @property
    def last_written_bank(self) -> Optional[str]:
        return self._last_written

    def corrupt(self, bank: str) -> None:
        record = self._banks[bank]
        if record is None:
            return
        tampered = bytearray(record.payload)
        tampered[0] ^= 0xFF
        self._banks[bank] = BankRecord(
            sequence=record.sequence, payload=bytes(tampered), crc32=record.crc32
        )

    def _next_sequence(self) -> int:
        known = [b.sequence for b in self._banks.values() if b is not None]
        return (max(known) + 1) if known else 0
