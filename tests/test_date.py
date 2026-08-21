# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import datetime

import pytest
import tzlocal

from churchsong.utils.date import (
    parse_datetime,
    parse_datetime_or_all,
    parse_year_range,
)


def test_parse_year_range_single_year() -> None:
    date_range = parse_year_range('2024')
    assert date_range.from_date.year == 2024
    assert date_range.from_date.month == 1
    assert date_range.from_date.day == 1
    assert date_range.to_date.year == 2024
    assert date_range.to_date.month == 12
    assert date_range.to_date.day == 31


def test_parse_year_range_explicit_range() -> None:
    date_range = parse_year_range('2024-2026')
    assert date_range.from_date.year == 2024
    assert date_range.from_date.month == 1
    assert date_range.from_date.day == 1
    assert date_range.to_date.year == 2026
    assert date_range.to_date.month == 12
    assert date_range.to_date.day == 31


def test_parse_year_range_open_start_defaults_to_2000() -> None:
    date_range = parse_year_range('-2026')
    assert date_range.from_date.year == 2000
    assert date_range.from_date.month == 1
    assert date_range.from_date.day == 1
    assert date_range.to_date.year == 2026
    assert date_range.to_date.month == 12
    assert date_range.to_date.day == 31


def test_parse_year_range_open_end_defaults_to_current_year() -> None:
    current_year = datetime.datetime.now(tz=tzlocal.get_localzone()).year
    date_range = parse_year_range('2024-')
    assert date_range.from_date.year == 2024
    assert date_range.from_date.month == 1
    assert date_range.from_date.day == 1
    assert date_range.to_date.year == current_year
    assert date_range.to_date.month == 12
    assert date_range.to_date.day == 31


def test_parse_year_range_empty_defaults_to_current_year() -> None:
    current_year = datetime.datetime.now(tz=tzlocal.get_localzone()).year
    date_range = parse_year_range('')
    assert date_range.from_date.year == current_year
    assert date_range.from_date.month == 1
    assert date_range.from_date.day == 1
    assert date_range.to_date.year == current_year
    assert date_range.to_date.month == 12
    assert date_range.to_date.day == 31


def test_parse_year_range_rejects_invalid_format() -> None:
    with pytest.raises(ValueError, match='Invalid format'):
        parse_year_range('20x4')


def test_parse_datetime_makes_naive_datetime_timezone_aware() -> None:
    date = parse_datetime('2026-08-16T10:00:00')
    assert date.tzinfo is not None
    assert date.utcoffset() is not None


def test_parse_datetime_keeps_explicit_timezone() -> None:
    date = parse_datetime('2026-08-16T10:00:00+02:00')
    assert date.utcoffset() == datetime.timedelta(hours=2)


def test_parse_datetime_or_all() -> None:
    assert parse_datetime_or_all('all') is None
    assert parse_datetime_or_all('ALL') is None
    assert parse_datetime_or_all('2026-08-16') is not None
