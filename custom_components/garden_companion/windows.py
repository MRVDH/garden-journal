"""Project pruning windows onto the calendar and find the next one (2.4, 3.2).

Pure logic over the Window dataclass, no Home Assistant. Dates arrive as
datetime.date; Home Assistant decides what "today" means through its configured
timezone and passes it in (3.5), so no clock is read here. 02-29 is rejected at
validation, so every MM-DD maps to a real date in any year.
"""

from __future__ import annotations

from datetime import date

from .models import Window


def _month_day(value: str) -> tuple[int, int]:
    """Parse a validated "MM-DD" string into a (month, day) pair."""
    month, day = value.split("-")
    return int(month), int(day)


def wraps(window: Window) -> bool:
    """Return whether the window spans the New Year (end before start in the year)."""
    return _month_day(window.end) < _month_day(window.start)


def contains(window: Window, day: date) -> bool:
    """Return whether day falls inside the window, inclusive of both bounds (2.4)."""
    start = _month_day(window.start)
    end = _month_day(window.end)
    point = (day.month, day.day)
    if wraps(window):
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


def is_pruning_now(windows: list[Window], today: date) -> bool:
    """Return whether today falls inside any of the windows."""
    return any(contains(window, today) for window in windows)
