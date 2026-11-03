# SPDX-FileCopyrightText: 2024-2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import dataclasses
import datetime as dt
import re

import tzlocal


def now(tz: dt.tzinfo | None = None) -> dt.datetime:
    if tz is None:
        tz = tzlocal.get_localzone()
    return dt.datetime.now(tz=tz)


@dataclasses.dataclass
class DateRange:
    from_date: dt.datetime
    to_date: dt.datetime


def parse_year_range(year_str: str) -> DateRange:
    local_tz = tzlocal.get_localzone()
    if not year_str:
        from_year = to_year = dt.datetime.now(tz=local_tz).year
    elif m := re.fullmatch(r'(?P<year>\d{4})', year_str):
        from_year = to_year = int(m.group('year'))
    elif m := re.fullmatch(r'(?P<from_year>\d{4})?-(?P<to_year>\d{4})?', year_str):
        current_year = dt.datetime.now(tz=local_tz).year
        from_year = int(m.group('from_year')) if m.group('from_year') else 2000
        to_year = int(m.group('to_year')) if m.group('to_year') else current_year
    else:
        msg = f'Invalid format: {year_str}'
        raise ValueError(msg)
    return DateRange(
        from_date=dt.datetime(from_year, 1, 1, tzinfo=local_tz),
        to_date=dt.datetime.combine(
            dt.date(to_year, 12, 31), dt.time.max, tzinfo=local_tz
        ),
    )


def parse_datetime_or_all(date_str: str) -> dt.datetime | None:
    if date_str.lower() == 'all':
        return None
    return parse_datetime(date_str)


def parse_datetime(date_str: str) -> dt.datetime:
    date = dt.datetime.fromisoformat(date_str)
    if date.tzinfo is None or date.tzinfo.utcoffset(date) is None:
        # convert offset-naive datetime object to offset-aware
        date = date.replace(tzinfo=tzlocal.get_localzone())
    return date
