from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass
from typing import Any, Callable, Optional

class SchedulerError(Exception):
    pass

@dataclass(frozen=True)
class Item:
    id: str
    data_class: str
    size_bytes: int = 0
    deadline: Optional[float] = None

class Scheduler:
    def __init__(self, priority_order: list[str]) -> None:
        self._priority_rank = {cls: rank for rank, cls in enumerate(priority_order)}
        self._heap: list[tuple[int, int, Item]] = []
        self._seq = itertools.count()

    def insert(self, item: Item) -> None:
        rank = self._priority_rank.get(item.data_class)
        if rank is None:
            raise SchedulerError(f"item {item.id!r} has unknown data class: {item.data_class!r}")
        heapq.heappush(self._heap, (rank, next(self._seq), item))

    def select_next(self, key: Optional[Callable[[Item], Any]] = None) -> Optional[Item]:
        if not self._heap:
            return None
        if key is None:
            _, _, item = heapq.heappop(self._heap)
            return item

        top_rank = self._heap[0][0]
        top_class_entries = [entry for entry in self._heap if entry[0] == top_rank]
        chosen = min(top_class_entries, key=lambda entry: (key(entry[2]), entry[1]))
        self._heap.remove(chosen)
        heapq.heapify(self._heap)
        return chosen[2]

    def all_items(self) -> list[Item]:
        return [entry[2] for entry in self._heap]

    def peek_next_class(self) -> Optional[str]:
        if not self._heap:
            return None
        return self._heap[0][2].data_class

    def candidate_classes(self) -> list[str]:
        return [item.data_class for _, _, item in sorted(self._heap)]

    def is_empty(self) -> bool:
        return not self._heap
