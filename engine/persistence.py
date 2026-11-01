from __future__ import annotations

import json
import zlib
from dataclasses import dataclass
from typing import Any, Iterable, Optional

_BANK_NAMES = ("A", "B")


@dataclass(frozen=True)
class BankRecord:
    sequence: int
    payload: bytes
    crc32: int

    def is_valid(self) -> bool:
        return _crc(self.sequence, self.payload) == self.crc32


def _crc(sequence: int, payload: bytes) -> int:
    return zlib.crc32(b"%d:" % sequence + payload)


def _serialize(sequence: int, state: str, context: dict) -> bytes:
    return json.dumps(
        {"sequence": sequence, "state": state, "context": context}, sort_keys=True
    ).encode("utf-8")


def _make_record(sequence: int, state: str, context: dict) -> BankRecord:
    payload = _serialize(sequence, state, context)
    return BankRecord(sequence=sequence, payload=payload, crc32=_crc(sequence, payload))


class PersistenceLayer:
    def __init__(self) -> None:
        self._banks: dict[str, Optional[BankRecord]] = {name: None for name in _BANK_NAMES}
        self._last_written: Optional[str] = None

    def save(self, state: str, context: dict) -> str:
        newest = self._newest_bank()
        target = "B" if newest == "A" else "A"
        other = "B" if target == "A" else "A"
        if self._holds(target, state, context) and self._holds(other, state, context):
            return newest
        self._write(target, state, context)
        if not self._holds(other, state, context):
            self._write(other, state, context)
        return self._last_written

    def _newest_bank(self) -> Optional[str]:
        valid = [n for n, b in self._banks.items() if b is not None and b.is_valid()]
        return max(valid, key=lambda n: self._banks[n].sequence, default=None)

    def _write(self, bank: str, state: str, context: dict) -> None:
        self._banks[bank] = _make_record(self._next_sequence(), state, context)
        self._last_written = bank

    def _holds(self, bank: str, state: str, context: dict) -> bool:
        record = self._banks[bank]
        return (record is not None and record.is_valid()
                and record.payload == _serialize(record.sequence, state, context))

    def load(self) -> Optional[dict[str, Any]]:
        newest = self._newest_bank()
        if newest is None:
            return None
        data = json.loads(self._banks[newest].payload)
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
        newest = self._newest_bank()
        return self._banks[newest].sequence + 1 if newest is not None else 0
