# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import abc
import datetime
import enum
import pathlib
import typing
from collections import defaultdict

import prettytable
import rich
import typer
import xlsxwriter

from churchsong.churchtools import ChurchToolsAPI
from churchsong.configuration import Configuration
from churchsong.utils.progress import progress


# The values of FormatType are the accepted formats of prettytable and openpyxl.
class FormatType(str, enum.Enum):
    TEXT = 'text'
    HTML = 'html'
    JSON = 'json'
    CSV = 'csv'
    LATEX = 'latex'
    MEDIAWIKI = 'mediawiki'
    XLSX = 'xlsx'


class BaseFormatter(abc.ABC):
    _columns: typing.ClassVar = ['Id', 'Song', 'Performed']

    @abc.abstractmethod
    def __init__(self, title: str) -> None: ...

    @abc.abstractmethod
    def add_row(self, row: list[str]) -> None: ...

    @abc.abstractmethod
    def done(self) -> None: ...


class AsciiFormatter(BaseFormatter):
    def __init__(
        self,
        title: str,
        *,
        output_format: FormatType,
        filename: pathlib.Path | None = None,
    ) -> None:
        self._filename = filename
        self._output_format = output_format
        self._title = f'{title}\n' if output_format == FormatType.TEXT else ''
        self._table = prettytable.PrettyTable()
        self._table.field_names = self._columns
        self._table.align['Id'] = 'r'
        self._table.align['Song'] = 'l'
        self._table.align['Performed'] = 'r'

    def add_row(self, row: list[str]) -> None:
        self._table.add_row(row)

    def done(self) -> None:
        table_text = self._table.get_formatted_string(  # pyright: ignore[reportUnknownMemberType]
            out_format=self._output_format.value, print_empty=False
        )
        text = f'{self._title}{table_text}'
        if self._filename:
            with self._filename.open('w', encoding='utf-8') as fd:
                fd.write(f'{text}\n')
        else:
            rich.print(text)


class ExcelFormatter(BaseFormatter):
    def __init__(self, title: str, *, filename: pathlib.Path) -> None:
        self._filename = filename
        self._workbook = xlsxwriter.Workbook(str(self._filename))
        self._worksheet = self._workbook.add_worksheet(name=title)

        self._align_left = self._workbook.add_format({'align': 'left'})
        self._align_right = self._workbook.add_format({'align': 'right'})

        self._row_index = 0
        self._col_widths = [len(col) for col in self._columns]
        self.add_row(self._columns)

    def add_row(self, row: list[str]) -> None:
        formats = [self._align_right, self._align_left, self._align_right]
        for col_index, (value, fmt) in enumerate(zip(row, formats, strict=True)):
            self._worksheet.write(self._row_index, col_index, value, fmt)
            self._col_widths[col_index] = max(self._col_widths[col_index], len(value))
        self._row_index += 1

    def done(self) -> None:
        for col_index, width in enumerate(self._col_widths):
            self._worksheet.set_column(col_index, col_index, width + 1)
        self._workbook.close()


class ChurchToolsSongStatistics:
    def __init__(self, cta: ChurchToolsAPI, config: Configuration) -> None:
        self.cta = cta
        self._log = config.log

    def song_usage(
        self,
        from_date: datetime.datetime,
        to_date: datetime.datetime,
        *,
        output_file: pathlib.Path | None = None,
        output_format: FormatType,
    ) -> None:
        self._log.info('Building song usage statistics')

        year_range = (
            f'{from_date.year}-{to_date.year}'
            if from_date.year != to_date.year
            else f'{from_date.year}'
        )
        title = f'Song statistics for {year_range}'
        if output_format == FormatType.XLSX:
            if not output_file:
                msg = 'Format "xlsx" requires to specify an output file.'
                raise typer.BadParameter(msg)
            formatter = ExcelFormatter(title=title, filename=output_file)
        else:
            formatter = AsciiFormatter(
                title=title, output_format=output_format, filename=output_file
            )

        # Iterate over events and songs and count usage.
        song_counts: dict[tuple[int, str], int] = defaultdict(int)
        with progress:
            task = progress.add_task('Calculating statistics', total=None)
            for event in self.cta.get_events(from_date, to_date):
                _, songs = self.cta.get_songs(event, require_tags=False)
                for song in songs:
                    song_counts[song.id, song.name or f'#{song.id}'] += 1
                    progress.advance(task)

        for (song_id, song_name), count in sorted(
            song_counts.items(), key=lambda s: (-s[1], s[0][1])
        ):
            formatter.add_row([f'#{song_id}', song_name, f'{count}'])

        # Output according to the selected formatter.
        formatter.done()
