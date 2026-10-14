# R-15 R-16 R-17 R-18

from __future__ import annotations

import math

import pytest

from engine.scheduler import Item, Scheduler, SchedulerError

PRIORITY = ["TTC", "SSTV", "CODEC2_M17"]

def test_empty_scheduler_selects_none_and_reports_empty():
    s = Scheduler(PRIORITY)
    assert s.is_empty() is True
    assert s.select_next() is None

@pytest.mark.requirement("R-15")
def test_selects_highest_priority_class_regardless_of_insertion_order():
    s = Scheduler(PRIORITY)
    s.insert(Item(id="v1", data_class="CODEC2_M17"))
    s.insert(Item(id="i1", data_class="SSTV"))
    s.insert(Item(id="t1", data_class="TTC"))
    assert s.select_next().id == "t1"
    assert s.select_next().id == "i1"
    assert s.select_next().id == "v1"
    assert s.select_next() is None

def test_same_class_items_are_fifo():
    s = Scheduler(PRIORITY)
    s.insert(Item(id="sstv-1", data_class="SSTV"))
    s.insert(Item(id="sstv-2", data_class="SSTV"))
    assert s.select_next().id == "sstv-1"
    assert s.select_next().id == "sstv-2"

@pytest.mark.requirement("R-16")
def test_newly_arrived_higher_priority_item_preempts_queued_lower_priority_items():
    s = Scheduler(PRIORITY)
    s.insert(Item(id="v1", data_class="CODEC2_M17"))
    s.insert(Item(id="i1", data_class="SSTV"))
    s.insert(Item(id="t1", data_class="TTC"))
    assert s.select_next().id == "t1"
    assert s.select_next().id == "i1"
    assert s.select_next().id == "v1"

def test_unknown_data_class_raises_scheduler_error():
    s = Scheduler(PRIORITY)
    with pytest.raises(SchedulerError, match="BOGUS"):
        s.insert(Item(id="x", data_class="BOGUS"))

def test_peek_next_class_does_not_remove_item():
    s = Scheduler(PRIORITY)
    s.insert(Item(id="i1", data_class="SSTV"))
    assert s.peek_next_class() == "SSTV"
    assert s.is_empty() is False
    assert s.select_next().id == "i1"

def test_candidate_classes_reports_service_order_without_removing_items():
    # R-32
    s = Scheduler(PRIORITY)
    s.insert(Item(id="v1", data_class="CODEC2_M17"))
    s.insert(Item(id="i1", data_class="SSTV"))
    s.insert(Item(id="t1", data_class="TTC"))
    assert s.candidate_classes() == ["TTC", "SSTV", "CODEC2_M17"]
    assert s.is_empty() is False
    assert s.select_next().id == "t1"

def test_candidate_classes_empty_scheduler():
    s = Scheduler(PRIORITY)
    assert s.candidate_classes() == []

def test_select_next_key_none_is_unchanged():
    s = Scheduler(PRIORITY)
    s.insert(Item(id="v1", data_class="CODEC2_M17"))
    s.insert(Item(id="i1", data_class="SSTV"))
    s.insert(Item(id="t1", data_class="TTC"))
    assert s.select_next(key=None).id == "t1"
    assert s.select_next().id == "i1"
    assert s.select_next(key=None).id == "v1"

def test_select_next_key_picks_earliest_deadline_within_top_class():
    s = Scheduler(PRIORITY)
    s.insert(Item(id="sstv-late", data_class="SSTV", deadline=500.0))
    s.insert(Item(id="sstv-early", data_class="SSTV", deadline=100.0))
    s.insert(Item(id="ttc-1", data_class="TTC", deadline=200.0))
    key = lambda item: item.deadline if item.deadline is not None else math.inf
    assert s.select_next(key=key).id == "ttc-1"
    assert s.select_next(key=key).id == "sstv-early"
    assert s.select_next(key=key).id == "sstv-late"

def test_select_next_key_ties_broken_by_arrival_order():
    s = Scheduler(PRIORITY)
    s.insert(Item(id="first", data_class="SSTV", deadline=100.0))
    s.insert(Item(id="second", data_class="SSTV", deadline=100.0))
    key = lambda item: item.deadline if item.deadline is not None else math.inf
    assert s.select_next(key=key).id == "first"
    assert s.select_next(key=key).id == "second"

def test_select_next_key_ignores_items_of_a_lower_class():
    s = Scheduler(PRIORITY)
    s.insert(Item(id="ttc-1", data_class="TTC", deadline=9999.0))
    s.insert(Item(id="sstv-urgent", data_class="SSTV", deadline=1.0))
    key = lambda item: item.deadline if item.deadline is not None else math.inf
    assert s.select_next(key=key).id == "ttc-1"

def test_all_items_returns_every_queued_item_without_removing():
    s = Scheduler(PRIORITY)
    s.insert(Item(id="t1", data_class="TTC"))
    s.insert(Item(id="i1", data_class="SSTV"))
    ids = {item.id for item in s.all_items()}
    assert ids == {"t1", "i1"}
    assert s.is_empty() is False
    assert len(s.all_items()) == 2
