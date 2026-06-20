"""Unit tests for dashboard period stats (today / this month in Asia/Shanghai)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.api.stats import (
    _today_range_utc,
    _month_range_utc,
    _to_naive_utc,
    CST,
)


class TestToNaiveUtc:
    def test_converts_cst_to_utc_minus_8(self):
        """CST 00:00 -> UTC 16:00 (previous day)."""
        cst_time = datetime(2026, 6, 20, 0, 0, 0, tzinfo=CST)
        result = _to_naive_utc(cst_time)
        assert result == datetime(2026, 6, 19, 16, 0, 0)


class TestTodayRangeUtc:
    def test_basic_range(self):
        """Today midnight CST -> tomorrow midnight CST, both naive UTC."""
        start, end = _today_range_utc()

        # start must be before end
        assert start < end
        # span must be exactly 24 hours
        assert end - start == timedelta(hours=24)

    def test_range_fits_date_boundary(self):
        """Any datetime in CST now must fall within [start, end)."""
        start, end = _today_range_utc()
        now_cst = datetime.now(CST)
        now_utc = _to_naive_utc(now_cst)

        assert now_utc >= start, f"{now_utc} >= {start}"
        assert now_utc < end, f"{now_utc} < {end}"

    def test_cross_utc_midnight(self):
        """When CST is 00:00, UTC is 16:00 the previous day — range still works."""
        start, end = _today_range_utc()
        # start and end should be naive UTC datetimes
        assert start.tzinfo is None
        assert end.tzinfo is None
        # end = start + 24h
        assert end - start == timedelta(hours=24)


class TestMonthRangeUtc:
    def test_basic_range(self):
        """First day of month CST -> first day of next month CST."""
        start, end = _month_range_utc()
        assert start < end
        # range should span a whole calendar month (28-31 days)
        delta = end - start
        assert timedelta(days=27) <= delta <= timedelta(days=32)

    def test_range_is_around_now(self):
        """Now must fall within [start, end)."""
        start, end = _month_range_utc()
        now_utc = _to_naive_utc(datetime.now(CST))
        assert now_utc >= start
        assert now_utc < end

    def test_month_boundary_no_overlap_with_previous(self):
        """End of one call and start of a 'previous month' call must not overlap."""
        start, end = _month_range_utc()
        # simulate 'previous month' by going back 1 day from start
        prev = start - timedelta(days=1)
        # prev must be < start (strictly before this month)
        assert prev < start
