# Decision Record 0004 — Scheduler Dynamic Reordering

**Date:** 2026-07-21

## What was done

Added one additive parameter to the frozen `engine/scheduler.Scheduler`:
`select_next(self, key: Optional[Callable[[Item], Any]] = None)`.
`key=None` (every pre-Phase-5 call site) is byte-identical to the prior
`(rank, seq)` FIFO-within-class pop, verified by the full 589-test
pre-Phase-5 suite passing unmodified. When `key` is given, selection is
restricted to the current top-priority nonempty class, then returns the
item minimizing `key(item)`. Also added `all_items()`, a non-destructive
read of every queued item.

## Why

Plan section 5 lists "priority-queue scheduler **with dynamic
reordering**" as an engine architecture goal (tied to the Sem III Data
Structures and Algorithms row in section 3's traceability table), but the
scheduler shipped in Phase 2/3 is static FIFO-within-class only — dynamic
reordering was never actually delivered. Phase 5's RQ3 comparison needs a
deadline-aware within-class tie-break (Earliest-Deadline-First, a
closed-form optimal rule for this single-server case), which requires this hook. This closes a Phase 2 gap rather
than opening new ground.

## Consequences

This reopens the Phase 3 "engine files byte-identical" freeze invariant.
The exception is documented here: every engine file remains byte-identical
except this one additive, default-preserving change to
`engine/scheduler.py`. `all_items()` similarly changes no existing
behavior — it is a new read accessor alongside `candidate_classes()`.
