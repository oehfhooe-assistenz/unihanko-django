# utils.py
from __future__ import annotations
from datetime import date, timedelta
from typing import Iterable, Optional, Set

# Default: Monday(0) .. Friday(4)
WEEKDAYS_MON_FRI: Set[int] = {0, 1, 2, 3, 4}

def weekdays_between(
    start: Optional[date],
    end: Optional[date],
    *,
    inclusive: bool = False,
    weekday_mask: Iterable[int] = WEEKDAYS_MON_FRI,
    clamp_negative: bool = True,
) -> Optional[int]:
    """
    Count days whose weekday() is in `weekday_mask` between two dates.

    Range semantics:
      - inclusive=False (default): counts in [start, end)  → end NOT included
      - inclusive=True:            counts in [start, end]  → end included

    Args:
        start: date or None
        end:   date or None
        inclusive: include the end date in the count
        weekday_mask: which weekdays to count (0=Mon ... 6=Sun).
                      Default counts Mon–Fri only.
        clamp_negative: if start > end → return 0 (True) or raise ValueError (False)

    Returns:
        int count, or None if either date is None.

    Examples:
        >>> from datetime import date
        >>> weekdays_between(date(2025,10,20), date(2025,10,24))  # Mon..Thu
        4
        >>> weekdays_between(date(2025,10,20), date(2025,10,24), inclusive=True)  # Mon..Fri
        5
        >>> weekdays_between(date(2025,10,25), date(2025,10,27))  # Sat..Mon (exclusive end)
        1
    """
    if start is None or end is None:
        return None

    if inclusive:
        end = end + timedelta(days=1)

    if start > end:
        if clamp_negative:
            return 0
        raise ValueError("start date is after end date")

    total_days = (end - start).days
    if total_days <= 0:
        return 0

    mask = set(int(d) for d in weekday_mask)
    if not mask.issubset({0, 1, 2, 3, 4, 5, 6}):
        raise ValueError("weekday_mask must contain integers 0..6")

    # Full weeks contribute len(mask) each
    full_weeks, extra_days = divmod(total_days, 7)
    count = full_weeks * len(mask)

    # Remainder window starting at start.weekday(), length = extra_days
    start_wd = start.weekday()
    for i in range(extra_days):
        if ((start_wd + i) % 7) in mask:
            count += 1

    return count