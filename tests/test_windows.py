"""Tests for the window maths: projection, year-wrapping, next-pruning (2.4, 3.2).

Pure logic. Every test passes an explicit reference date, so nothing depends on
the real clock.
"""

from __future__ import annotations

from datetime import date

from custom_components.garden_companion.models import Window
from custom_components.garden_companion.windows import (
    contains,
    is_pruning_now,
    next_pruning,
    next_start,
)


def _w(start: str, end: str) -> Window:
    """Build a Window with placeholder prose."""
    return Window(start=start, end=end, description={"nl": "x", "en": "y"})


def test_contains_is_inclusive_of_both_bounds() -> None:
    """A non-wrapping window includes its start and end days."""
    window = _w("02-15", "03-31")
    assert contains(window, date(2026, 2, 15))
    assert contains(window, date(2026, 3, 31))
    assert contains(window, date(2026, 3, 1))
    assert not contains(window, date(2026, 2, 14))
    assert not contains(window, date(2026, 4, 1))


def test_contains_handles_a_year_wrap() -> None:
    """A wrapping window includes days on both sides of New Year."""
    window = _w("12-01", "02-28")
    assert contains(window, date(2026, 12, 1))
    assert contains(window, date(2026, 1, 15))
    assert contains(window, date(2026, 2, 28))
    assert not contains(window, date(2026, 3, 1))
    assert not contains(window, date(2026, 11, 30))


def test_next_start_inside_returns_this_years_start() -> None:
    """On 20 February the window that opened on the 15th projects to the 15th."""
    window = _w("02-15", "03-31")
    assert next_start(window, date(2026, 2, 20)) == date(2026, 2, 15)


def test_next_start_before_the_window_is_this_year() -> None:
    """Ahead of the window, the next start is this year's."""
    window = _w("02-15", "03-31")
    assert next_start(window, date(2026, 1, 1)) == date(2026, 2, 15)


def test_next_start_after_the_window_rolls_to_next_year() -> None:
    """Past the window, the next start is next year's."""
    window = _w("02-15", "03-31")
    assert next_start(window, date(2026, 4, 1)) == date(2027, 2, 15)


def test_january_window_in_march_is_next_january() -> None:
    """A January window seen in March is next January, not last."""
    window = _w("01-15", "02-15")
    assert next_start(window, date(2026, 3, 1)) == date(2027, 1, 15)


def test_wrap_active_in_january_is_last_years_start() -> None:
    """Inside a wrap during January, the start is last year's."""
    window = _w("12-01", "02-28")
    assert next_start(window, date(2026, 1, 15)) == date(2025, 12, 1)


def test_wrap_active_in_december_is_this_years_start() -> None:
    """Inside a wrap during December, the start is this year's."""
    window = _w("12-01", "02-28")
    assert next_start(window, date(2026, 12, 15)) == date(2026, 12, 1)


def test_wrap_not_active_is_this_years_start() -> None:
    """Outside a wrap, the next start is this year's opening."""
    window = _w("12-01", "02-28")
    assert next_start(window, date(2026, 3, 1)) == date(2026, 12, 1)


def test_next_pruning_earliest_upcoming_window_wins() -> None:
    """With nothing active, the soonest upcoming start wins."""
    summer = _w("07-15", "08-31")
    winter = _w("01-15", "02-15")
    result, window = next_pruning([summer, winter], date(2026, 6, 1))
    assert result == date(2026, 7, 15)
    assert window is summer


def test_next_pruning_active_window_wins_over_upcoming() -> None:
    """An open window projects to a past start and beats an upcoming window."""
    spring = _w("02-15", "03-31")
    summer = _w("07-15", "08-31")
    result, window = next_pruning([spring, summer], date(2026, 2, 20))
    assert result == date(2026, 2, 15)
    assert window is spring


def test_is_pruning_now() -> None:
    """prune_now is on only while today falls inside a window."""
    spring = _w("02-15", "03-31")
    summer = _w("07-15", "08-31")
    assert is_pruning_now([spring, summer], date(2026, 3, 1))
    assert not is_pruning_now([spring, summer], date(2026, 5, 1))
