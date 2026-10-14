from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from sim.driver import DeliveryRecord

_JOULES_PER_WATT_HOUR = 3600.0
_BITS_PER_BYTE = 8

_P50 = 0.50
_P95 = 0.95

@dataclass(frozen=True)
class BaselineMetrics:
    delivery_success_rate: float
    ttc_latency_min_s: float | None
    ttc_latency_median_s: float | None
    ttc_latency_p95_s: float | None
    ttc_latency_max_s: float | None
    energy_per_delivered_bit_j: float | None
    deadline_misses_by_class: dict[str, int]
    deadline_success_ratio: float = 0.0
    deadline_success_ratio_by_class: dict[str, float] = field(default_factory=dict)

def _percentile(sorted_values: list[float], p: float) -> float:
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    rank = p * (n - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_values[lo]
    frac = rank - lo
    return sorted_values[lo] + frac * (sorted_values[hi] - sorted_values[lo])

def compute_metrics(
    deliveries: list[DeliveryRecord],
    *,
    ttc_class_name: str,
    priority_order: list[str],
    size_bytes_by_item: dict[str, int],
) -> BaselineMetrics:
    total_count = len(deliveries)
    delivered = [d for d in deliveries if d.delivered]
    delivered_count = len(delivered)

    delivery_success_rate = (
        delivered_count / total_count if total_count > 0 else 0.0
    )

    ttc_latencies = sorted(
        d.latency_s
        for d in delivered
        if d.data_class == ttc_class_name and d.latency_s is not None
    )
    if ttc_latencies:
        ttc_latency_min_s = ttc_latencies[0]
        ttc_latency_median_s = _percentile(ttc_latencies, _P50)
        ttc_latency_p95_s = _percentile(ttc_latencies, _P95)
        ttc_latency_max_s = ttc_latencies[-1]
    else:
        ttc_latency_min_s = None
        ttc_latency_median_s = None
        ttc_latency_p95_s = None
        ttc_latency_max_s = None

    if delivered:
        total_energy_j = sum(
            (d.energy_wh or 0.0) * _JOULES_PER_WATT_HOUR for d in delivered
        )
        total_bits = sum(
            size_bytes_by_item.get(d.item_id, 0) * _BITS_PER_BYTE for d in delivered
        )
        energy_per_delivered_bit_j = (
            total_energy_j / total_bits if total_bits > 0 else None
        )
    else:
        energy_per_delivered_bit_j = None

    deadline_misses_by_class: dict[str, int] = {cls: 0 for cls in priority_order}
    for d in deliveries:
        if d.deadline_missed:
            deadline_misses_by_class[d.data_class] = (
                deadline_misses_by_class.get(d.data_class, 0) + 1
            )

    on_time = [d for d in delivered if not d.deadline_missed]
    deadline_success_ratio = len(on_time) / total_count if total_count > 0 else 0.0
    deadline_success_ratio_by_class = {}
    for cls in priority_order:
        n_cls = sum(1 for d in deliveries if d.data_class == cls)
        n_ok = sum(1 for d in on_time if d.data_class == cls)
        deadline_success_ratio_by_class[cls] = n_ok / n_cls if n_cls else 0.0

    return BaselineMetrics(
        delivery_success_rate=delivery_success_rate,
        ttc_latency_min_s=ttc_latency_min_s,
        ttc_latency_median_s=ttc_latency_median_s,
        ttc_latency_p95_s=ttc_latency_p95_s,
        ttc_latency_max_s=ttc_latency_max_s,
        energy_per_delivered_bit_j=energy_per_delivered_bit_j,
        deadline_misses_by_class=deadline_misses_by_class,
        deadline_success_ratio=deadline_success_ratio,
        deadline_success_ratio_by_class=deadline_success_ratio_by_class,
    )

_Z_95 = 1.96

@dataclass(frozen=True)
class MetricSummary:

    n: int
    mean: float
    stdev: float
    ci95_low: float
    ci95_high: float

@dataclass(frozen=True)
class AggregatedMetrics:

    n_runs: int
    delivery_success_rate: MetricSummary
    ttc_latency_p95_s: MetricSummary | None
    energy_per_delivered_bit_j: MetricSummary | None
    deadline_success_ratio: MetricSummary | None = None
    deadline_success_ratio_by_class: dict[str, MetricSummary] = field(default_factory=dict)

def _summarize(values: list[float]) -> MetricSummary:
    n = len(values)
    mean = statistics.mean(values)
    if n > 1:
        stdev = statistics.stdev(values)
        margin = _Z_95 * stdev / math.sqrt(n)
    else:
        stdev = 0.0
        margin = 0.0
    return MetricSummary(
        n=n, mean=mean, stdev=stdev, ci95_low=mean - margin, ci95_high=mean + margin
    )

def aggregate_metrics(runs: list[BaselineMetrics]) -> AggregatedMetrics:
    if not runs:
        raise ValueError("aggregate_metrics requires at least one run")

    delivery_success_rate = _summarize([r.delivery_success_rate for r in runs])

    p95_values = [r.ttc_latency_p95_s for r in runs if r.ttc_latency_p95_s is not None]
    energy_values = [
        r.energy_per_delivered_bit_j for r in runs if r.energy_per_delivered_bit_j is not None
    ]

    return AggregatedMetrics(
        n_runs=len(runs),
        delivery_success_rate=delivery_success_rate,
        ttc_latency_p95_s=_summarize(p95_values) if p95_values else None,
        energy_per_delivered_bit_j=_summarize(energy_values) if energy_values else None,
        deadline_success_ratio=_summarize([r.deadline_success_ratio for r in runs]),
        deadline_success_ratio_by_class={
            cls: _summarize([r.deadline_success_ratio_by_class.get(cls, 0.0) for r in runs])
            for cls in runs[0].deadline_success_ratio_by_class
        },
    )
