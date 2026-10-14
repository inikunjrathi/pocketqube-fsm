from __future__ import annotations

import itertools
import random

from policy.bound import fluid_completions, moore_hodgson

def test_moore_hodgson_matches_brute_force():
    rng = random.Random(3)
    for _ in range(50):
        jobs = [(rng.randint(0, 20), rng.randint(1, 8)) for _ in range(7)]
        best = 0
        for r in range(len(jobs) + 1):
            for subset in itertools.combinations(jobs, r):
                load, ok = 0, True
                for deadline, size in sorted(subset):
                    load += size
                    ok &= load <= deadline
                if ok:
                    best = max(best, r)
        assert moore_hodgson(jobs) == best

def test_fluid_completions_capacity_and_rerouting():
    assert fluid_completions([(0, 1, 4)] * 3, 1, 10) == 2.5
    assert fluid_completions([(0, 2, 1), (0, 1, 1)], 2, 1) == 2.0
    assert fluid_completions([(1, 1, 5)], 2, 10) == 0.0
