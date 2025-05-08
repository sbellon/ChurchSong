# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import abc
import datetime
import typing

import pptx.enum.dml
import pptx.shapes.graphfrm
import pptx.table
import pptx.text.text
import pptx.util

from churchsong.churchtools import CalendarAppointmentBase, RepeatId
from churchsong.configuration import Configuration
from churchsong.powerpoint import PowerPointBase


class TableFillerBase(abc.ABC):
    type: typing.ClassVar[str]

    def __init__(
        self, config: Configuration, date_format: str, time_format: str
    ) -> None:
        self._log = config.log
        self._table = None
        self._font = None
        self._total_rows = 0
        self._current_row = 0
        self._date_format = date_format
        self._time_format = time_format
        self._unset_table_warning = False

    def set_table(self, table: pptx.table.Table) -> None:
        if self._table:
            self._log.warning('%s already set, not setting again', self.type)
        self._table = table
        self._total_rows = len(table.rows)
        self._current_row = 0
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.text_frame.paragraphs:
                    for run in paragraph.runs:
                        self._font = run.font
                        return

    def _set_font_properties(
        self,
        dst_font_element: pptx.text.text.Font,
        src_font_element: pptx.text.text.Font,
        scale: float = 1.0,
    ) -> None:
        for attr in ('name', 'bold', 'italic', 'underline', 'language_id'):
            if value := getattr(src_font_element, attr, None):
                setattr(dst_font_element, attr, value)
        if src_font_element.size:
            dst_font_element.size = pptx.util.Pt(src_font_element.size.pt * scale)

        match getattr(src_font_element.color, 'type', None):
            case pptx.enum.dml.MSO_COLOR_TYPE.RGB:
                dst_font_element.color.rgb = getattr(
                    src_font_element.color, 'rgb', None
                )
            case pptx.enum.dml.MSO_COLOR_TYPE.SCHEME:
                dst_font_element.color.theme_color = getattr(
                    src_font_element.color, 'theme_color', None
                )
            case _:
                pass

    def _set_cell_text(
        self,
        cell: pptx.table._Cell,  # pyright: ignore[reportPrivateUsage]
        line1: str,
        line2: str | None = None,
    ) -> None:
        font_of_run = {
            idx: run.font for idx, run in enumerate(cell.text_frame.paragraphs[0].runs)
        }
        cell.text_frame.paragraphs[0].text = f'{line1}\v{line2}' if line2 else line1
        for idx, run in enumerate(cell.text_frame.paragraphs[0].runs):
            if font := font_of_run.get(idx) or self._font:
                self._set_font_properties(
                    run.font,
                    font,
                    scale=0.66 if idx > 0 and idx not in font_of_run else 1.0,
                )

    @abc.abstractmethod
    def _date_and_time(self, appt: CalendarAppointmentBase) -> str: ...

    def add(self, appt: CalendarAppointmentBase) -> None:
        if not self._table:
            # Safeguard, no table registered.
            if not self._unset_table_warning:
                self._unset_table_warning = True
                self._log.warning('%s unset, ignoring all appointments', self.type)
            return
        if self._current_row >= self._total_rows:
            # All available table rows have been filled.
            self._log.warning('%s table is full, ignoring appointment', self.type)
            return
        self._set_cell_text(
            self._table.cell(self._current_row, 0),
            self._date_and_time(appt),
        )
        self._set_cell_text(
            self._table.cell(self._current_row, 1),
            appt.title,
            appt.subtitle or appt.description or appt.link,
        )
        self._current_row += 1

    def fill(self) -> None:
        if not self._table:
            # Safeguard, no table registered.
            return
        for row in range(self._current_row, self._total_rows):
            self._set_cell_text(self._table.cell(row, 0), '')
            self._set_cell_text(self._table.cell(row, 1), '')


class WeeklyTableFiller(TableFillerBase):
    type: typing.ClassVar[str] = 'Weekly Table'

    def _date_and_time(self, appt: CalendarAppointmentBase) -> str:
        local_start = appt.start_date.astimezone()
        return (
            f'{local_start:%A}'
            if appt.all_day
            else f'{local_start:%a. {self._time_format}}'
        )


class IrregularTableFiller(TableFillerBase):
    type: typing.ClassVar[str] = 'Irregular Table'

    def _date_and_time(self, appt: CalendarAppointmentBase) -> str:
        local_start = appt.start_date.astimezone()
        return (
            f'{local_start:%a. {self._date_format}}'
            if appt.all_day
            else f'{local_start:%a. {self._date_format} {self._time_format}}'
        )


class PowerPointAppointments(PowerPointBase):
    def __init__(self, config: Configuration) -> None:
        config.log.info('Creating PowerPoint appointments slides')
        super().__init__(
            config, config.songbeamer.powerpoint.appointments.template_pptx
        )
        self._weekly_table = WeeklyTableFiller(
            config=config,
            date_format=config.songbeamer.settings.date_format,
            time_format=config.songbeamer.settings.time_format,
        )
        self._irregular_table = IrregularTableFiller(
            config=config,
            date_format=config.songbeamer.settings.date_format,
            time_format=config.songbeamer.settings.time_format,
        )

    def _setup_tables(self) -> None:
        if not self._prs:
            return

        # Walk through the slides and shapes and register the weekly table and the
        # irregular table for later filling with the appropriate appointments.
        for slide in self._prs.slides:
            for shape in slide.shapes:
                if (
                    isinstance(shape, pptx.shapes.graphfrm.GraphicFrame)
                    and shape.has_table
                ):
                    match shape.name:
                        case self._weekly_table.type:
                            self._weekly_table.set_table(shape.table)
                        case self._irregular_table.type:
                            self._irregular_table.set_table(shape.table)
                        case _:
                            pass

    def create(
        self,
        appointments: typing.Iterable[CalendarAppointmentBase],
        from_date: datetime.datetime,
    ) -> None:
        if not self._prs:
            return

        self._setup_tables()

        # Walk through the appointments and put them in the appropriate table.
        next_8days = from_date + datetime.timedelta(days=8)
        for appt in appointments:
            match (appt.repeat_id, appt.repeat_frequency):
                case (RepeatId.WEEKLY, 1) if appt.start_date < next_8days:
                    self._weekly_table.add(appt)
                case (RepeatId.WEEKLY, 1):
                    pass  # ignore weekly appointments more than one week away
                case _:
                    self._irregular_table.add(appt)

        # Fill the tables to clean potential style templates in the cells.
        self._weekly_table.fill()
        self._irregular_table.fill()
