# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import csv
import datetime
import io
import pathlib
import typing
import zipfile

import pytest
import typer
import xlsxwriter
import xlsxwriter.exceptions
from responses import matchers

from churchsong.churchtools.song_statistics import (
    AsciiFormatter,
    ChurchToolsSongStatistics,
    ExcelFormatter,
)
from churchsong.utils import CliError
from tests.conftest import CHURCHTOOLS_BASE_URL

if typing.TYPE_CHECKING:
    import responses

    from churchsong.churchtools import ChurchToolsAPI

FROM_DATE = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
TO_DATE = datetime.datetime(2026, 12, 31, tzinfo=datetime.UTC)


def make_song_json(song_id: int, name: str) -> dict[str, object]:
    return {
        'id': song_id,
        'name': name,
        'author': None,
        'ccli': None,
        'arrangements': [],
        'tags': [],
    }


def register_usage_endpoints(
    mocked_responses: responses.RequestsMock, from_date: str, to_date: str
) -> None:
    """Two events sharing one song; one song has no usable name."""
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/events',
        json={
            'data': [
                {
                    'id': event_id,
                    'name': 'Sunday Service',
                    'startDate': f'{start}T10:00:00Z',
                    'endDate': f'{start}T12:00:00Z',
                }
                for event_id, start in ((1, '2026-08-16'), (2, '2026-08-23'))
            ]
        },
        match=[matchers.query_param_matcher({'from': from_date, 'to': to_date})],
    )
    for event_id, songs in (
        (1, [make_song_json(10, 'Amazing Grace'), make_song_json(11, 'Be Thou')]),
        (2, [make_song_json(10, 'Amazing Grace'), make_song_json(12, '')]),
    ):
        mocked_responses.get(
            f'{CHURCHTOOLS_BASE_URL}/api/events/{event_id}/agenda/songs',
            json={'data': songs, 'meta': {'count': len(songs)}},
        )


def test_song_usage_counts_and_sorts_into_text_file(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
) -> None:
    register_usage_endpoints(mocked_responses, '2024-01-01', '2026-12-31')
    output_file = tmp_path / 'usage.txt'
    ChurchToolsSongStatistics(churchtools_api).song_usage(
        FROM_DATE,
        TO_DATE,
        output_file=output_file,
        output_format=ChurchToolsSongStatistics.FormatType.TEXT,
    )
    text = output_file.read_text(encoding='utf-8')
    assert 'Song statistics for 2024-2026' in text  # multi-year range in title
    (grace_row,) = [line for line in text.splitlines() if 'Amazing Grace' in line]
    assert '#10' in grace_row
    assert '2' in grace_row
    # Sorted by count descending, then by name; the unnamed song falls back
    # to its #id, which sorts before 'Be Thou'.
    assert text.index('Amazing Grace') < text.index('#12') < text.index('Be Thou')


def test_song_usage_rich_output_with_single_year_title(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    register_usage_endpoints(mocked_responses, '2026-01-01', '2026-12-31')
    ChurchToolsSongStatistics(churchtools_api).song_usage(
        datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        datetime.datetime(2026, 12, 31, tzinfo=datetime.UTC),
        output_format=ChurchToolsSongStatistics.FormatType.RICH,
    )
    out = capsys.readouterr().out
    assert 'Song statistics for 2026' in out
    assert 'Amazing Grace' in out
    assert 'Be Thou' in out


@pytest.mark.parametrize(
    'output_format',
    [
        ChurchToolsSongStatistics.FormatType.RICH,
        ChurchToolsSongStatistics.FormatType.TEXT,
    ],
)
def test_song_usage_prints_markup_in_a_song_name_verbatim(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    capsys: pytest.CaptureFixture[str],
    output_format: ChurchToolsSongStatistics.FormatType,
) -> None:
    # Both console formatters put arbitrary song names in front of rich.
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/events',
        json={
            'data': [
                {
                    'id': 1,
                    'name': 'Sunday Service',
                    'startDate': '2026-08-16T10:00:00Z',
                    'endDate': '2026-08-16T12:00:00Z',
                }
            ]
        },
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/events/1/agenda/songs',
        json={'data': [make_song_json(10, 'Lied [/x] Schluss')], 'meta': {'count': 1}},
    )
    ChurchToolsSongStatistics(churchtools_api).song_usage(
        FROM_DATE, TO_DATE, output_format=output_format
    )
    assert 'Lied [/x] Schluss' in capsys.readouterr().out


def test_song_usage_xlsx_requires_output_file(churchtools_api: ChurchToolsAPI) -> None:
    with pytest.raises(typer.BadParameter, match='requires'):
        ChurchToolsSongStatistics(churchtools_api).song_usage(
            FROM_DATE,
            TO_DATE,
            output_format=ChurchToolsSongStatistics.FormatType.XLSX,
        )


def test_ascii_formatter_writes_parseable_csv_without_title(
    tmp_path: pathlib.Path,
) -> None:
    output_file = tmp_path / 'usage.csv'
    formatter = AsciiFormatter(
        title='not part of csv output',
        output_format=ChurchToolsSongStatistics.FormatType.CSV,
        filename=output_file,
    )
    formatter.add_row(['#10', 'Song, with comma', '2'])
    formatter.done()
    content = output_file.read_text(encoding='utf-8', newline='')
    assert 'not part of csv output' not in content
    rows = list(csv.reader(io.StringIO(content)))
    assert rows[0] == ['Id', 'Song', 'Performed']
    assert rows[1] == ['#10', 'Song, with comma', '2']


def test_excel_formatter_writes_workbook(tmp_path: pathlib.Path) -> None:
    output_file = tmp_path / 'usage.xlsx'
    formatter = ExcelFormatter(title='Song statistics for 2026', filename=output_file)
    formatter.add_row(['#10', 'Amazing Grace', '2'])
    formatter.done()
    # xlsxwriter is write-only and the project has no xlsx reader, so peek
    # into the zip archive directly.
    with zipfile.ZipFile(output_file) as archive:
        workbook_xml = archive.read('xl/workbook.xml').decode()
        shared_strings = archive.read('xl/sharedStrings.xml').decode()
    assert 'Song statistics for 2026' in workbook_xml  # worksheet name
    for cell_value in ('Id', 'Song', 'Performed', '#10', 'Amazing Grace', '2'):
        assert f'<t>{cell_value}</t>' in shared_strings


def test_song_usage_text_output_goes_to_the_console(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    register_usage_endpoints(mocked_responses, '2024-01-01', '2026-12-31')
    ChurchToolsSongStatistics(churchtools_api).song_usage(
        FROM_DATE,
        TO_DATE,
        output_format=ChurchToolsSongStatistics.FormatType.TEXT,
    )
    out = capsys.readouterr().out
    assert 'Song statistics for 2024-2026' in out
    assert 'Amazing Grace' in out


def test_song_usage_writes_an_xlsx_workbook(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
) -> None:
    register_usage_endpoints(mocked_responses, '2024-01-01', '2026-12-31')
    output_file = tmp_path / 'usage.xlsx'
    ChurchToolsSongStatistics(churchtools_api).song_usage(
        FROM_DATE,
        TO_DATE,
        output_file=output_file,
        output_format=ChurchToolsSongStatistics.FormatType.XLSX,
    )
    with zipfile.ZipFile(output_file) as archive:
        assert '<t>Amazing Grace</t>' in archive.read('xl/sharedStrings.xml').decode()


def test_song_usage_creates_a_missing_output_directory(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
) -> None:
    register_usage_endpoints(mocked_responses, '2024-01-01', '2026-12-31')
    output_file = tmp_path / 'no' / 'such' / 'dir' / 'usage.csv'
    ChurchToolsSongStatistics(churchtools_api).song_usage(
        FROM_DATE,
        TO_DATE,
        output_file=output_file,
        output_format=ChurchToolsSongStatistics.FormatType.CSV,
    )
    assert 'Amazing Grace' in output_file.read_text(encoding='utf-8')


@pytest.mark.parametrize(
    'output_format',
    [
        ChurchToolsSongStatistics.FormatType.CSV,
        ChurchToolsSongStatistics.FormatType.XLSX,
    ],
)
def test_song_usage_reports_an_unwritable_output_file_before_the_walk(
    churchtools_api: ChurchToolsAPI,
    tmp_path: pathlib.Path,
    output_format: ChurchToolsSongStatistics.FormatType,
) -> None:
    # A file where a directory is expected makes the mkdir fail the same way a
    # missing permission or an unavailable network share does on a real installation.
    # No endpoint beyond the permissions of the fixture is registered, so a request
    # for the events would raise instead of reaching the assertions below - which is
    # what pins the check to run before the walk rather than after it.
    (tmp_path / 'blocker').write_text('not a directory', encoding='utf-8')
    output_file = tmp_path / 'blocker' / 'dir' / f'usage.{output_format.value}'
    with pytest.raises(CliError, match='Cannot write') as exc_info:
        ChurchToolsSongStatistics(churchtools_api).song_usage(
            FROM_DATE,
            TO_DATE,
            output_file=output_file,
            output_format=output_format,
        )
    assert str(output_file) in exc_info.value.format_message()


def test_song_usage_reports_an_output_file_that_breaks_during_the_walk(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The backstop for the file becoming unwritable after the check passed, e.g. by
    # Excel opening it. xlsxwriter raises FileCreateError, which is not an OSError.
    register_usage_endpoints(mocked_responses, '2024-01-01', '2026-12-31')
    output_file = tmp_path / 'usage.xlsx'

    def fail_to_close(_self: object) -> None:
        msg = f'[Errno 13] {output_file}'
        raise xlsxwriter.exceptions.FileCreateError(msg)

    monkeypatch.setattr(xlsxwriter.Workbook, 'close', fail_to_close)
    with pytest.raises(CliError, match='Cannot write') as exc_info:
        ChurchToolsSongStatistics(churchtools_api).song_usage(
            FROM_DATE,
            TO_DATE,
            output_file=output_file,
            output_format=ChurchToolsSongStatistics.FormatType.XLSX,
        )
    assert str(output_file) in exc_info.value.format_message()


def test_song_usage_hints_at_an_open_spreadsheet_on_a_refused_write(
    churchtools_api: ChurchToolsAPI,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse_touch(_self: object) -> None:
        raise PermissionError(13, 'Permission denied')

    monkeypatch.setattr(pathlib.Path, 'touch', refuse_touch)
    with pytest.raises(CliError, match='open in Excel'):
        ChurchToolsSongStatistics(churchtools_api).song_usage(
            FROM_DATE,
            TO_DATE,
            output_file=tmp_path / 'usage.xlsx',
            output_format=ChurchToolsSongStatistics.FormatType.XLSX,
        )


def test_song_usage_rich_format_does_not_create_the_output_file(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
) -> None:
    # The rich formatter ignores `output_file`, so the check must not leave an empty
    # file behind for it.
    register_usage_endpoints(mocked_responses, '2024-01-01', '2026-12-31')
    output_file = tmp_path / 'usage.txt'
    ChurchToolsSongStatistics(churchtools_api).song_usage(
        FROM_DATE,
        TO_DATE,
        output_file=output_file,
        output_format=ChurchToolsSongStatistics.FormatType.RICH,
    )
    assert not output_file.exists()
