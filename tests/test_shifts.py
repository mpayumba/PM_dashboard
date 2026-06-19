"""Tests for the 12-hour shift model."""
from __future__ import annotations

from datetime import datetime

from src.shifts import DAY, NIGHT, current_shift, previous_shift, recent_shifts


def test_day_shift_window():
    s = current_shift(datetime(2026, 6, 19, 9, 0))
    assert s.name == DAY
    assert s.start == datetime(2026, 6, 19, 5, 0)
    assert s.end == datetime(2026, 6, 19, 17, 0)


def test_day_shift_starts_at_0500_inclusive():
    s = current_shift(datetime(2026, 6, 19, 5, 0))
    assert s.name == DAY
    assert s.start == datetime(2026, 6, 19, 5, 0)


def test_night_shift_evening():
    s = current_shift(datetime(2026, 6, 19, 17, 0))
    assert s.name == NIGHT
    assert s.start == datetime(2026, 6, 19, 17, 0)
    assert s.end == datetime(2026, 6, 20, 5, 0)


def test_night_shift_after_midnight_belongs_to_prior_day():
    s = current_shift(datetime(2026, 6, 19, 2, 0))
    assert s.name == NIGHT
    assert s.start == datetime(2026, 6, 18, 17, 0)
    assert s.end == datetime(2026, 6, 19, 5, 0)


def test_just_before_day_start_is_night():
    s = current_shift(datetime(2026, 6, 19, 4, 59))
    assert s.name == NIGHT
    assert s.end == datetime(2026, 6, 19, 5, 0)


def test_shift_id_and_label():
    s = current_shift(datetime(2026, 6, 19, 9, 0))
    assert s.shift_id == "2026-06-19 Day"
    assert "Day" in s.label and "05:00" in s.label


def test_previous_shift_alternates():
    day = current_shift(datetime(2026, 6, 19, 9, 0))
    prev = previous_shift(day)
    assert prev.name == NIGHT
    assert prev.start == datetime(2026, 6, 18, 17, 0)
    assert prev.end == datetime(2026, 6, 19, 5, 0)
    prev2 = previous_shift(prev)
    assert prev2.name == DAY
    assert prev2.start == datetime(2026, 6, 18, 5, 0)


def test_recent_shifts_newest_first_and_contiguous():
    shifts = recent_shifts(datetime(2026, 6, 19, 9, 0), 4)
    assert len(shifts) == 4
    assert [s.name for s in shifts] == [DAY, NIGHT, DAY, NIGHT]
    # contiguous: each shift ends where the next-newer one starts
    for newer, older in zip(shifts, shifts[1:]):
        assert older.end == newer.start
