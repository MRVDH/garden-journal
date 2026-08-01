"""Project pruning windows onto the calendar and find the next one (2.4, 3.2).

Pure logic over the Window dataclass, no Home Assistant. Dates arrive as
datetime.date; Home Assistant decides what "today" means through its configured
timezone and passes it in (3.5), so no clock is read here. 02-29 is rejected at
validation, so every MM-DD maps to a real date in any year.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from .models import Window


class Span(Protocol):
    """An inclusive MM-DD range: a pruning window or a care season (2.4, 2.9).

    The two mean different things to a gardener and behave identically on a
    calendar, so the range maths below is written once against this.
    """

    @property
    def start(self) -> str:
        """The inclusive start, as a validated "MM-DD" string."""

    @property
    def end(self) -> str:
        """The inclusive end, as a validated "MM-DD" string."""


def _month_day(value: str) -> tuple[int, int]:
    """Parse a validated "MM-DD" string into a (month, day) pair."""
    month, day = value.split("-")
    return int(month), int(day)


def wraps(span: Span) -> bool:
    """Return whether the range spans the New Year (end before start in the year)."""
    return _month_day(span.end) < _month_day(span.start)


def contains(span: Span, day: date) -> bool:
    """Return whether day falls inside the range, inclusive of both bounds (2.4)."""
    start = _month_day(span.start)
    end = _month_day(span.end)
    point = (day.month, day.day)
    if wraps(span):
        return point >= start or point <= end
    return start <= point <= end


def next_start(window: Window, today: date) -> date:
    """Return the window's start as its current-or-next occurrence (3.2).

    While today is inside the window, this is the start of the occurrence in
    progress: a past-or-today date, and for a year-wrapping window it can be last
    year's. Otherwise it is the next start on or after today.
    """
    month, day = _month_day(window.start)
    if contains(window, today):
        if wraps(window) and (today.month, today.day) <= _month_day(window.end):
            # In the January-to-end tail of a wrap, the window opened last year.
            return date(today.year - 1, month, day)
        return date(today.year, month, day)
    this_year = date(today.year, month, day)
    if this_year >= today:
        return this_year
    return date(today.year + 1, month, day)


def next_pruning(windows: list[Window], today: date) -> tuple[date, Window]:
    """Return the next-pruning date and the window it comes from (3.2).

    Each window is projected to its current-or-next start and the earliest wins.
    A window in progress projects to a past start, so an active window always
    beats an upcoming one: this is why the sensor shows the open window while
    prune_now is on (3.3). Requires at least one window, which the schema
    guarantees.
    """
    projected = [(next_start(window, today), window) for window in windows]
    return min(projected, key=lambda pair: pair[0])


def in_season(spans: list[Window] | list[Span], today: date) -> bool:
    """Return whether today falls inside any of the ranges (3.3).

    Answers both "is it pruning time" over windows and "is the care season open"
    over care, since the question is the same one.
    """
    return any(contains(span, today) for span in spans)


def occurrence_start(window: Window, year: int) -> date:
    """Return the start date of the window occurrence that begins in the given year."""
    month, day = _month_day(window.start)
    return date(year, month, day)


def occurrence_end(window: Window, start: date) -> date:
    """Return the end date of the window occurrence that began on start."""
    month, day = _month_day(window.end)
    year = start.year + 1 if wraps(window) else start.year
    return date(year, month, day)


def occurrences_in_range(
    window: Window, range_start: date, range_end: date
) -> list[tuple[int, date, date]]:
    """Return each yearly occurrence overlapping the half-open range (3.4).

    Each is (start year, start date, end date), with the end inclusive of the
    last pruning day. range_end is exclusive. A caller wanting the iCal all-day
    end adds a day to the inclusive end.
    """
    occurrences: list[tuple[int, date, date]] = []
    for year in range(range_start.year - 1, range_end.year + 2):
        start = occurrence_start(window, year)
        end = occurrence_end(window, start)
        if start < range_end and end >= range_start:
            occurrences.append((year, start, end))
    return occurrences
