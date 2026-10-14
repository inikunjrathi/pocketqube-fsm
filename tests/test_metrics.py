from __future__ import annotations

import ast
import statistics
from pathlib import Path

import pytest

from sim.driver import DeliveryRecord
from sim.metrics import BaselineMetrics, aggregate_metrics, compute_metrics

TTC = "TTC"
SSTV = "SSTV"
VOICE = "CODEC2_M17"
PRIORITY_ORDER = [TTC, SSTV, VOICE]

def _record(
    item_id: str,
    data_class: str,
    *,
    delivered: bool,
    latency_s: float | None = None,
    deadline_missed: bool = False,
    energy_wh: float | None = None,
    arrival_time_s: float = 0.0,
    delivery_time_s: float | None = None,
) -> DeliveryRecord:
    return DeliveryRecord(
        item_id=item_id,
        data_class=data_class,
        arrival_time_s=arrival_time_s,
        delivered=delivered,
        delivery_time_s=delivery_time_s,
        latency_s=latency_s,
        deadline_missed=deadline_missed,
        energy_wh=energy_wh,
    )

def test_empty_input_does_not_raise():
    metrics = compute_metrics(
        [], ttc_class_name=TTC, priority_order=PRIORITY_ORDER, size_bytes_by_item={}
    )

    assert metrics.delivery_success_rate == 0.0
    assert metrics.ttc_latency_min_s is None
    assert metrics.ttc_latency_median_s is None
    assert metrics.ttc_latency_p95_s is None
    assert metrics.ttc_latency_max_s is None
    assert metrics.energy_per_delivered_bit_j is None
    assert metrics.deadline_misses_by_class == {cls: 0 for cls in PRIORITY_ORDER}

def test_delivery_success_rate_computed_correctly():
    deliveries = [
        _record("i1", TTC, delivered=True, latency_s=1.0),
        _record("i2", TTC, delivered=True, latency_s=2.0),
        _record("i3", SSTV, delivered=False),
        _record("i4", VOICE, delivered=False),
        _record("i5", VOICE, delivered=True, latency_s=3.0),
    ]

    metrics = compute_metrics(
        deliveries,
        ttc_class_name=TTC,
        priority_order=PRIORITY_ORDER,
        size_bytes_by_item={},
    )

    assert metrics.delivery_success_rate == pytest.approx(3 / 5)

def test_ttc_latency_distribution_matches_hand_computed_values():
    # R-7
    latencies = [1.0, 2.0, 3.0, 4.0, 5.0]
    deliveries = [
        _record(f"i{i}", TTC, delivered=True, latency_s=lat)
        for i, lat in enumerate(latencies)
    ]

    metrics = compute_metrics(
        deliveries,
        ttc_class_name=TTC,
        priority_order=PRIORITY_ORDER,
        size_bytes_by_item={},
    )

    assert metrics.ttc_latency_min_s == pytest.approx(1.0)
    assert metrics.ttc_latency_median_s == pytest.approx(statistics.median(latencies))
    assert metrics.ttc_latency_p95_s == pytest.approx(4.8)
    assert metrics.ttc_latency_max_s == pytest.approx(5.0)

def test_non_ttc_deliveries_excluded_from_latency():
    deliveries = [
        _record("i1", TTC, delivered=True, latency_s=10.0),
        _record("i2", SSTV, delivered=True, latency_s=999.0),
        _record("i3", VOICE, delivered=True, latency_s=999.0),
        _record("i4", TTC, delivered=False, latency_s=None),
    ]

    metrics = compute_metrics(
        deliveries,
        ttc_class_name=TTC,
        priority_order=PRIORITY_ORDER,
        size_bytes_by_item={},
    )

    assert metrics.ttc_latency_min_s == pytest.approx(10.0)
    assert metrics.ttc_latency_median_s == pytest.approx(10.0)
    assert metrics.ttc_latency_p95_s == pytest.approx(10.0)
    assert metrics.ttc_latency_max_s == pytest.approx(10.0)

def test_energy_per_bit_computed_correctly():
    deliveries = [
        _record("i1", TTC, delivered=True, latency_s=1.0, energy_wh=0.001),
        _record("i2", SSTV, delivered=True, latency_s=1.0, energy_wh=0.002),
        _record("i3", VOICE, delivered=False, energy_wh=None),
    ]
    size_bytes_by_item = {"i1": 100, "i2": 200, "i3": 999}

    metrics = compute_metrics(
        deliveries,
        ttc_class_name=TTC,
        priority_order=PRIORITY_ORDER,
        size_bytes_by_item=size_bytes_by_item,
    )

    assert metrics.energy_per_delivered_bit_j == pytest.approx(0.0045)

def test_deadline_misses_grouped_by_class_including_zero():
    deliveries = [
        _record("i1", TTC, delivered=True, deadline_missed=True),
        _record("i2", TTC, delivered=True, deadline_missed=True),
        _record("i3", SSTV, delivered=False, deadline_missed=True),
        _record("i4", VOICE, delivered=True, deadline_missed=False),
    ]

    metrics = compute_metrics(
        deliveries,
        ttc_class_name=TTC,
        priority_order=PRIORITY_ORDER,
        size_bytes_by_item={},
    )

    assert metrics.deadline_misses_by_class == {TTC: 2, SSTV: 1, VOICE: 0}

def _metrics(
    delivery_success_rate: float,
    ttc_latency_p95_s: float | None,
    energy_per_delivered_bit_j: float | None,
) -> BaselineMetrics:
    return BaselineMetrics(
        delivery_success_rate=delivery_success_rate,
        ttc_latency_min_s=None,
        ttc_latency_median_s=None,
        ttc_latency_p95_s=ttc_latency_p95_s,
        ttc_latency_max_s=None,
        energy_per_delivered_bit_j=energy_per_delivered_bit_j,
        deadline_misses_by_class={},
    )

def test_aggregate_metrics_empty_runs_raises():
    with pytest.raises(ValueError):
        aggregate_metrics([])

def test_aggregate_metrics_single_run_has_zero_stdev_and_ci_width():
    agg = aggregate_metrics([_metrics(0.9185, 39819.859, 3.389e-4)])

    assert agg.n_runs == 1
    assert agg.delivery_success_rate.n == 1
    assert agg.delivery_success_rate.mean == pytest.approx(0.9185)
    assert agg.delivery_success_rate.stdev == 0.0
    assert agg.delivery_success_rate.ci95_low == pytest.approx(0.9185)
    assert agg.delivery_success_rate.ci95_high == pytest.approx(0.9185)

def test_aggregate_metrics_hand_computed_mean_and_ci():
    runs = [
        _metrics(0.90, 100.0, 1e-4),
        _metrics(0.92, 200.0, 2e-4),
        _metrics(0.94, 300.0, 3e-4),
    ]

    agg = aggregate_metrics(runs)

    assert agg.n_runs == 3
    assert agg.delivery_success_rate.n == 3
    assert agg.delivery_success_rate.mean == pytest.approx(0.92)
    assert agg.delivery_success_rate.stdev == pytest.approx(statistics.stdev([0.90, 0.92, 0.94]))
    expected_margin = 1.96 * statistics.stdev([0.90, 0.92, 0.94]) / (3 ** 0.5)
    assert agg.delivery_success_rate.ci95_low == pytest.approx(0.92 - expected_margin)
    assert agg.delivery_success_rate.ci95_high == pytest.approx(0.92 + expected_margin)

    assert agg.ttc_latency_p95_s is not None
    assert agg.ttc_latency_p95_s.mean == pytest.approx(200.0)
    assert agg.energy_per_delivered_bit_j is not None
    assert agg.energy_per_delivered_bit_j.mean == pytest.approx(2e-4)

def test_aggregate_metrics_skips_none_valued_runs_for_optional_metrics():
    runs = [
        _metrics(0.5, None, None),
        _metrics(0.7, 50.0, 1e-4),
        _metrics(0.9, 150.0, 3e-4),
    ]

    agg = aggregate_metrics(runs)

    assert agg.n_runs == 3
    assert agg.delivery_success_rate.n == 3
    assert agg.ttc_latency_p95_s is not None
    assert agg.ttc_latency_p95_s.n == 2
    assert agg.ttc_latency_p95_s.mean == pytest.approx(100.0)
    assert agg.energy_per_delivered_bit_j is not None
    assert agg.energy_per_delivered_bit_j.n == 2
    assert agg.energy_per_delivered_bit_j.mean == pytest.approx(2e-4)

def test_aggregate_metrics_all_none_optional_metric_yields_none():
    runs = [_metrics(0.5, None, None), _metrics(0.6, None, None)]

    agg = aggregate_metrics(runs)

    assert agg.ttc_latency_p95_s is None
    assert agg.energy_per_delivered_bit_j is None

def test_no_network_access():
    import sim.metrics as metrics_module

    source = Path(metrics_module.__file__).read_text()
    tree = ast.parse(source)

    banned = {"requests", "urllib", "socket"}
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module.split(".")[0])

    assert not (imported_modules & banned), (
        f"sim/metrics.py imports network modules: {imported_modules & banned}"
    )

def test_deadline_success_ratio_counts_only_on_time_deliveries_over_generated():
    records = [
        _record("t1", TTC, delivered=True, latency_s=1.0),
        _record("t2", TTC, delivered=True, latency_s=9.0, deadline_missed=True),
        _record("t3", TTC, delivered=False, deadline_missed=True),
        _record("s1", SSTV, delivered=True, latency_s=2.0),
    ]
    m = compute_metrics(records, ttc_class_name=TTC, priority_order=PRIORITY_ORDER, size_bytes_by_item={})
    assert m.delivery_success_rate == 0.75
    assert m.deadline_success_ratio == 0.5
    assert m.deadline_success_ratio_by_class == {TTC: 1 / 3, SSTV: 1.0, VOICE: 0.0}
    agg = aggregate_metrics([m, m])
    assert agg.deadline_success_ratio.mean == 0.5
    assert agg.deadline_success_ratio_by_class[TTC].mean == 1 / 3
