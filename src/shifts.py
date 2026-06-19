"""12-hour production shift model.

Heliene runs 24/7 with two shifts:
    Day   shift: 05:00 -> 17:00
    Night shift: 17:00 -> 05:00 (next day)

All times are LOCAL machine time. Functions are pure and take an explicit `now`
so shift math is deterministic and unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

DAY = "Day"
NIGHT = "Night"

DEFAULT_DAY_START = time(5, 0)
DEFAULT_NIGHT_START = time(17, 0)
SHIFT_HOURS = 12


@dataclass(frozen=True)
class Shift:
    name: str          # "Day" or "Night"
    start: datetime
    end: datetime

    @property
    def shift_id(self) -> str:
        """Stable id: the date the shift STARTED plus its name, e.g. '2026-06-19 Day'."""
        return f"{self.start.date().isoformat()} {self.name}"

    @property
    def label(self) -> str:
        return f"{self.start:%a %m/%d} {self.name} ({self.start:%H:%M}–{self.end:%H:%M})"

    def contains(self, when: datetime) -> bool:
        return self.start <= when < self.end


def current_shift(
    now: datetime,
    day_start: time = DEFAULT_DAY_START,
    night_start: time = DEFAULT_NIGHT_START,
) -> Shift:
    """The shift that `now` falls within."""
    today = now.date()
    day_start_dt = datetime.combine(today, day_start)
    night_start_dt = datetime.combine(today, night_start)

    if day_start_dt <= now < night_start_dt:
        # Day shift: 05:00 today -> 17:00 today.
        return Shift(DAY, day_start_dt, night_start_dt)
    if now >= night_start_dt:
        # Night shift that started this evening -> 05:00 tomorrow.
        end = datetime.combine(today + timedelta(days=1), day_start)
        return Shift(NIGHT, night_start_dt, end)
    # now < day_start: night shift that started yesterday evening -> 05:00 today.
    start = datetime.combine(today - timedelta(days=1), night_start)
    return Shift(NIGHT, start, day_start_dt)


def previous_shift(
    shift: Shift,
    day_start: time = DEFAULT_DAY_START,
    night_start: time = DEFAULT_NIGHT_START,
) -> Shift:
    """The shift immediately before `shift`."""
    return current_shift(shift.start - timedelta(minutes=1), day_start, night_start)


def recent_shifts(
    now: datetime,
    n: int,
    day_start: time = DEFAULT_DAY_START,
    night_start: time = DEFAULT_NIGHT_START,
) -> list[Shift]:
    """The current shift and the n-1 shifts before it, newest first."""
    shifts: list[Shift] = []
    s = current_shift(now, day_start, night_start)
    for _ in range(max(n, 1)):
        shifts.append(s)
        s = previous_shift(s, day_start, night_start)
    return shifts
