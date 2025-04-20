# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import dataclasses
import datetime
import re

import tzlocal


def now(tz: datetime.tzinfo | None = None) -> datetime.datetime:
    if tz is None:
        tz = tzlocal.get_localzone()
    return datetime.datetime.now(tz=tz)


@dataclasses.dataclass
class DateRange:
    from_date: datetime.datetime
    to_date: datetime.datetime


def parse_year_range(year_str: str) -> DateRange:
    local_tz = tzlocal.get_localzone()
    if not year_str:
        from_year = to_year = datetime.datetime.now(tz=local_tz).year
    elif m := re.fullmatch(r'(?P<year>\d{4})', year_str):
        from_year = to_year = int(m.group('year'))
    elif m := re.fullmatch(r'(?P<from_year>\d{4})?-(?P<to_year>\d{4})?', year_str):
        current_year = datetime.datetime.now(tz=local_tz).year
        from_year = int(m.group('from_year')) if m.group('from_year') else 2000
        to_year = int(m.group('to_year')) if m.group('to_year') else current_year
    else:
        msg = f'Invalid format: {year_str}'
        raise ValueError(msg)
    return DateRange(
        from_date=datetime.datetime(
            year=from_year,
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            tzinfo=local_tz,
        ),
        to_date=datetime.datetime(
            year=to_year,
            month=12,
            day=31,
            hour=23,
            minute=59,
            second=59,
            tzinfo=local_tz,
        ),
    )


def parse_datetime(date_str: str) -> datetime.datetime | None:
    if date_str.lower() == 'all':
        return None
    date = datetime.datetime.fromisoformat(date_str)
    if date.tzinfo is None or date.tzinfo.utcoffset(date) is None:
        # convert offset-naive datetime object to offset-aware
        date = date.replace(tzinfo=tzlocal.get_localzone())
    return date
