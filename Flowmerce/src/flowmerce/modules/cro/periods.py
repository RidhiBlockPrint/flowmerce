"""Which time window a CRO figure covers, and what it is compared with (pure, no I/O).

Rules from the manager's checklist (section 1):
  * The default period is yesterday, a complete day. "Today so far" and "Last 7 days" are options.
  * A day is compared with the same weekday: the 4-week same-weekday average (default) or the same
    weekday last week. Never with the day before, which mixes weekdays.
  * Today so far is compared with the same elapsed time on the same weekday last week.
  * Last 7 days is compared with the 7 days before it.
Days are the store's local days (Shopify's timezone for the store).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

PERIODS = ("yesterday", "today", "last7")
COMPARES = ("4week_avg", "last_week")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class Window:
    """[start, end) in UTC."""

    start: datetime
    end: datetime

    def contains(self, at: datetime) -> bool:
        """True when `at` falls inside the window."""
        return self.start <= at < self.end


@dataclass(frozen=True)
class Plan:
    """The current window, the baseline window(s) whose figures are averaged, and their labels."""

    period: str
    compare: str
    label: str
    baseline_label: str
    is_partial: bool
    target_day: date  # the (last) local day of the current window
    current: Window
    baselines: tuple[Window, ...]
    current_days: tuple[date, ...]
    baseline_days: tuple[tuple[date, ...], ...]  # per baseline window, its local days


def day_window(day: date, tz: ZoneInfo) -> Window:
    """One local day as a UTC window."""
    start = datetime.combine(day, time.min, tzinfo=tz)
    return Window(start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC))


def days_window(first: date, last: date, tz: ZoneInfo) -> Window:
    """Local days first..last (inclusive) as one UTC window."""
    return Window(day_window(first, tz).start, day_window(last, tz).end)


def _span(last: date, n: int) -> tuple[date, ...]:
    return tuple(last - timedelta(days=i) for i in range(n - 1, -1, -1))


def plan(period: str, compare: str, tz: ZoneInfo, now: datetime) -> Plan:
    """Resolve a period/compare choice into windows. Unknown values fall back to yesterday /
    4week_avg.
    """
    period = period if period in PERIODS else "yesterday"
    compare = compare if compare in COMPARES else "4week_avg"
    local_now = now.astimezone(tz)
    today = local_now.date()
    yesterday = today - timedelta(days=1)

    if period == "today":
        start = day_window(today, tz).start
        elapsed = now - start
        last_week = today - timedelta(days=7)
        lw_start = day_window(last_week, tz).start
        return Plan(
            period,
            "last_week",
            f"Today so far ({local_now:%a %d %b}, as of {local_now:%H:%M})",
            f"vs same time {WEEKDAYS[last_week.weekday()]} last week",
            True,
            today,
            Window(start, now),
            (Window(lw_start, lw_start + elapsed),),
            (today,),
            ((last_week,),),
        )

    if period == "last7":
        first = yesterday - timedelta(days=6)
        prior_last = yesterday - timedelta(days=7)
        return Plan(
            period,
            "prior_7",
            f"Last 7 days ({first:%d %b} - {yesterday:%d %b})",
            "vs prior 7 days",
            False,
            yesterday,
            days_window(first, yesterday, tz),
            (days_window(prior_last - timedelta(days=6), prior_last, tz),),
            _span(yesterday, 7),
            (_span(prior_last, 7),),
        )

    label = f"Yesterday ({yesterday:%a %d %b}, complete day)"
    weekday = WEEKDAYS[yesterday.weekday()]
    if compare == "last_week":
        same = yesterday - timedelta(days=7)
        return Plan(
            period,
            compare,
            label,
            f"vs same {weekday} last week",
            False,
            yesterday,
            day_window(yesterday, tz),
            (day_window(same, tz),),
            (yesterday,),
            ((same,),),
        )
    back = tuple(yesterday - timedelta(days=7 * w) for w in range(1, 5))
    return Plan(
        period,
        compare,
        label,
        f"vs 4-week {weekday} average",
        False,
        yesterday,
        day_window(yesterday, tz),
        tuple(day_window(d, tz) for d in back),
        (yesterday,),
        tuple((d,) for d in back),
    )


RANGE_COMPARES = (
    "previous",
    "previous_year",
    "previous_year_dow",
    "last_week",
    "4week_avg",
    "custom",
    "none",
)
MAX_RANGE_DAYS = 366


class RangeError(ValueError):
    """A from/to choice that cannot be used; the message says why."""


def _fmt(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def _year_back(d: date) -> int:
    """Days from the same calendar date a year earlier to `d` (29 Feb counts from 28 Feb)."""
    try:
        before = d.replace(year=d.year - 1)
    except ValueError:  # 29 February
        before = d.replace(year=d.year - 1, day=28)
    return (d - before).days


def range_plan(
    start: date,
    end: date,
    compare: str,
    tz: ZoneInfo,
    now: datetime,
    compare_start: date | None = None,
) -> Plan:
    """Any local-day range start..end (inclusive), as the team picks it on the calendar.

    compare (like Shopify's "Compare to"): 'previous' = the same number of days just before;
    'previous_year' = the same dates a year earlier; 'previous_year_dow' = 52 weeks earlier, so
    weekdays line up; 'last_week' = the same days one week earlier; '4week_avg' = for a single day,
    the average of the same weekday in the 4 weeks before (longer ranges fall back to 'previous');
    'custom' = the same number of days starting on `compare_start` (before `start`); 'none' = no
    comparison. A range that reaches today runs until now, and its comparison covers the same
    elapsed time.
    """
    today = now.astimezone(tz).date()
    if start > end:
        raise RangeError("The start date is after the end date.")
    if start > today:
        raise RangeError("The range starts in the future.")
    end = min(end, today)
    n = (end - start).days + 1
    if n > MAX_RANGE_DAYS:
        raise RangeError(f"Pick at most {MAX_RANGE_DAYS} days.")
    compare = compare if compare in RANGE_COMPARES else "previous"
    if compare == "4week_avg" and n != 1:
        compare = "previous"
    if compare == "custom":
        if compare_start is None:
            compare = "previous"
        elif compare_start >= start:
            raise RangeError("The comparison must start before the chosen days.")
    partial = end == today
    first = day_window(start, tz).start
    current = Window(first, now if partial else day_window(end, tz).end)
    days = tuple(start + timedelta(days=i) for i in range(n))

    def shifted(back: int) -> tuple[Window, tuple[date, ...]]:
        b_start = start - timedelta(days=back)
        b_first = day_window(b_start, tz).start
        b_end = (
            b_first + (current.end - current.start)
            if partial
            else day_window(end - timedelta(days=back), tz).end
        )
        return Window(b_first, b_end), tuple(d - timedelta(days=back) for d in days)

    if compare == "none":
        windows: list[tuple[Window, tuple[date, ...]]] = []
        base_label = "no comparison"
    elif compare == "last_week":
        windows = [shifted(7)]
        base_label = (
            "vs same days a week earlier"
            if n > 1
            else (f"vs same {WEEKDAYS[start.weekday()]} last week")
        )
    elif compare == "4week_avg":
        windows = [shifted(7 * w) for w in range(1, 5)]
        base_label = f"vs 4-week {WEEKDAYS[start.weekday()]} average"
    elif compare == "previous_year":
        windows = [shifted(_year_back(start))]
        base_label = "vs same dates last year"
    elif compare == "previous_year_dow":
        windows = [shifted(364)]
        base_label = "vs last year (same weekdays)"
    elif compare == "custom" and compare_start is not None:
        windows = [shifted((start - compare_start).days)]
        c_end = compare_start + timedelta(days=n - 1)
        base_label = (
            f"vs {_fmt(compare_start)}" if n == 1 else f"vs {_fmt(compare_start)} - {_fmt(c_end)}"
        )
    else:
        windows = [shifted(n)]
        base_label = "vs previous day" if n == 1 else f"vs previous {n} days"
    if n == 1:
        label = f"{WEEKDAYS[start.weekday()]} {_fmt(start)}"
    else:
        label = f"{_fmt(start)} - {_fmt(end)} ({n} days)"
    if partial:
        label += f", so far (as of {now.astimezone(tz):%H:%M})"
    return Plan(
        "range",
        compare,
        label,
        base_label,
        partial,
        end,
        current,
        tuple(w for w, _ in windows),
        days,
        tuple(d for _, d in windows),
    )


def parse_day(value: str | None) -> date | None:
    """A YYYY-MM-DD query value as a date; None when empty. Raises RangeError when malformed."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        raise RangeError(f"'{value[:20]}' is not a date like 2026-11-19.") from None


def pct_change(current: float | None, previous: float | None) -> float | None:
    """% change, or None when there is nothing to compare with."""
    if current is None or not previous:
        return None
    return round((current - previous) / previous * 100, 2)


def metric_block(
    value: float | None,
    baseline: float | None,
    too_early: bool,
    baseline_label: str,
    digits: int = 2,
) -> dict[str, object]:
    """One KPI with its baseline. When it is too early to compare, no change is given."""
    change = (
        None if value is None or baseline is None or too_early else round(value - baseline, digits)
    )
    return {
        "value": value,
        "baseline_value": baseline,
        "baseline_label": baseline_label,
        "change_abs": change,
        "change_pct": None if too_early else pct_change(value, baseline),
        "too_early": too_early,
    }
