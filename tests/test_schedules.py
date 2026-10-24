from datetime import datetime

import pytest
from xp_core.services.automation import ScheduleError, next_run_after, parse_schedule


def test_every_minutes_and_aliases():
    assert next_run_after("every 5m", datetime(2026, 10, 24, 10, 0)) == datetime(2026, 10, 24, 10, 5)
    assert parse_schedule("hourly").seconds == 3600
    with pytest.raises(ScheduleError):
        parse_schedule("every 10s")


def test_daily_several_times_in_lagos_time():
    # 08:00 and 18:30 Lagos (UTC+1) -> 07:00 and 17:30 UTC
    expr = "daily 08:00,18:30 tz Africa/Lagos"
    assert next_run_after(expr, datetime(2026, 10, 24, 6, 0)) == datetime(2026, 10, 24, 7, 0)
    assert next_run_after(expr, datetime(2026, 10, 24, 7, 0)) == datetime(2026, 10, 24, 17, 30)
    assert next_run_after(expr, datetime(2026, 10, 24, 18, 0)) == datetime(2026, 10, 25, 7, 0)


def test_weekly_and_monthly():
    # 2026-10-24 is a Saturday
    assert next_run_after("weekly mon,fri 09:00", datetime(2026, 10, 24, 12, 0)) == datetime(2026, 10, 26, 9, 0)
    assert next_run_after("monthly 1 07:00", datetime(2026, 10, 24)) == datetime(2026, 11, 1, 7, 0)
    with pytest.raises(ScheduleError):
        parse_schedule("weekly funday 09:00")
    with pytest.raises(ScheduleError):
        parse_schedule("daily 08:00 tz Mars/Base")
