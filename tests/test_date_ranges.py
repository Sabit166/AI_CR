from datetime import date, datetime, timezone

import pytest

import date_ranges as dr

# 2026-10-11 is a Sunday.
SUN, MON, TUE, THU, FRI, SAT = (date(2026, 10, d) for d in (11, 12, 13, 15, 16, 17))


@pytest.mark.parametrize('today,start,end', [
    (SUN, date(2026, 10, 11), date(2026, 10, 15)),
    (MON, date(2026, 10, 11), date(2026, 10, 15)),
    (THU, date(2026, 10, 11), date(2026, 10, 15)),
    (FRI, date(2026, 10, 11), date(2026, 10, 15)),   # the week that just ended
    (SAT, date(2026, 10, 11), date(2026, 10, 15)),
])
def test_academic_week_of(today, start, end):
    week = dr.academic_week_of(today)
    assert (week.start, week.end) == (start, end)
    assert week.start.strftime('%A') == 'Sunday' and week.end.strftime('%A') == 'Thursday'


@pytest.mark.parametrize('today,expected', [
    (SUN, (date(2026, 10, 11), date(2026, 10, 15))),
    (MON, (date(2026, 10, 12), date(2026, 10, 15))),
    (THU, (date(2026, 10, 15), date(2026, 10, 15))),
    (FRI, None),
    (SAT, None),
])
def test_this_week_remaining(today, expected):
    r = dr.this_week_remaining(today)
    assert (None if r is None else (r.start, r.end)) == expected


@pytest.mark.parametrize('today', [SUN, MON, TUE, THU, FRI, SAT])
def test_next_week_is_following_sunday_to_thursday(today):
    r = dr.next_week(today)
    assert (r.start, r.end) == (date(2026, 10, 18), date(2026, 10, 22))


@pytest.mark.parametrize('today,start,end', [
    (date(2026, 10, 29), date(2026, 11, 1), date(2026, 11, 5)),    # month boundary (Thu -> next week in Nov)
    (date(2026, 12, 30), date(2027, 1, 3), date(2027, 1, 7)),      # year boundary (Wed)
    (date(2026, 12, 31), date(2027, 1, 3), date(2027, 1, 7)),      # Thu, last day of year
    (date(2028, 2, 24), date(2028, 2, 27), date(2028, 3, 2)),      # leap year: week spans Feb 29
    (date(2024, 2, 29), date(2024, 3, 3), date(2024, 3, 7)),       # asked on Feb 29 itself
])
def test_next_week_boundaries(today, start, end):
    r = dr.next_week(today)
    assert (r.start, r.end) == (start, end)


def test_this_week_spanning_month_and_leap_day():
    week = dr.academic_week_of(date(2028, 3, 1))  # Wednesday
    assert (week.start, week.end) == (date(2028, 2, 27), date(2028, 3, 2))
    assert dr.this_week_remaining(date(2028, 2, 29)) == dr.DateRange(date(2028, 2, 29), date(2028, 3, 2))


def test_year_boundary_this_week():
    # Sunday 2026-12-27 .. Thursday 2026-12-31
    assert dr.academic_week_of(date(2026, 12, 29)) == dr.DateRange(date(2026, 12, 27), date(2026, 12, 31))
    # Fri 2027-01-01 is weekend -> nothing left; next week starts Sun 2027-01-03
    assert dr.this_week_remaining(date(2027, 1, 1)) is None
    assert dr.next_week(date(2027, 1, 1)).start == date(2027, 1, 3)


@pytest.mark.parametrize('utc_moment,local_date', [
    # 17:59 UTC = 23:59 Dhaka (same day); 18:00 UTC = 00:00 next day in Dhaka
    (datetime(2026, 10, 15, 17, 59, tzinfo=timezone.utc), date(2026, 10, 15)),
    (datetime(2026, 10, 15, 18, 0, tzinfo=timezone.utc), date(2026, 10, 16)),
    (datetime(2026, 12, 31, 18, 30, tzinfo=timezone.utc), date(2027, 1, 1)),
])
def test_today_uses_dhaka_not_server_timezone(utc_moment, local_date):
    assert dr.today_local(lambda: utc_moment) == local_date


def test_timezone_boundary_changes_week_answer():
    # Thursday 23:30 Dhaka still has "this week"; 30 minutes later (Friday) it does not.
    thursday_night = datetime(2026, 10, 15, 17, 30, tzinfo=timezone.utc)
    friday_early = datetime(2026, 10, 15, 18, 30, tzinfo=timezone.utc)
    assert dr.this_week_remaining(dr.today_local(lambda: thursday_night)) is not None
    assert dr.this_week_remaining(dr.today_local(lambda: friday_early)) is None


def test_naive_clock_rejected():
    with pytest.raises(ValueError):
        dr.now_local(lambda: datetime(2026, 1, 1))


@pytest.mark.parametrize('today,weekday,expected', [
    (MON, 'monday', MON),
    (MON, 'sunday', date(2026, 10, 18)),
    (FRI, 'saturday', SAT),
    (SAT, 'sunday', date(2026, 10, 18)),
])
def test_next_weekday(today, weekday, expected):
    assert dr.next_weekday(today, weekday) == expected


@pytest.mark.parametrize('today,start_wd,end_wd,start,end', [
    (TUE, 'sunday', 'thursday', SUN, THU),                              # current week while running
    (FRI, 'sunday', 'thursday', date(2026, 10, 18), date(2026, 10, 22)), # weekend -> next week
    (MON, 'monday', 'wednesday', MON, date(2026, 10, 14)),
    (MON, 'thursday', 'sunday', THU, date(2026, 10, 18)),               # wraps over the weekend
])
def test_weekday_range(today, start_wd, end_wd, start, end):
    assert dr.weekday_range(today, start_wd, end_wd) == dr.DateRange(start, end)


def test_resolve_calendar_date():
    assert dr.resolve_calendar_date(date(2026, 10, 13), 27, 10) == date(2026, 10, 27)
    assert dr.resolve_calendar_date(date(2026, 10, 13), 3, 8) == date(2026, 8, 3)     # recent past stays
    assert dr.resolve_calendar_date(date(2026, 12, 20), 5, 1) == date(2027, 1, 5)     # rolls to next year
    assert dr.resolve_calendar_date(date(2026, 10, 13), 29, 2, 2028) == date(2028, 2, 29)
    with pytest.raises(ValueError):
        dr.resolve_calendar_date(date(2026, 10, 13), 29, 2, 2027)


def test_range_validation_and_format():
    with pytest.raises(ValueError):
        dr.DateRange(date(2026, 1, 2), date(2026, 1, 1))
    assert dr.format_day(date(2026, 8, 3)) == 'Monday, 3 August 2026'
