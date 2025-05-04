# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

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


class TableFiller:
    def __init__(
        self,
        dayofweek_format: str,
        date_format: str,
        time_format: str,
        weekly: bool = False,
    ) -> None:
        self._table = None
        self._font = None
        self._total_rows = 0
        self._current_row = 0
        self._dayofweek_format = dayofweek_format
        self._date_format = date_format
        self._time_format = time_format
        self._weekly = weekly

    def set_table(self, table: pptx.table.Table) -> None:
        self._table = table
        self._total_rows = len(table.rows)
        self._current_row = 0
        if table.cell(0, 0).text_frame.paragraphs[0].runs:
            self._font = table.cell(0, 0).text_frame.paragraphs[0].runs[0].font

    def _set_font(
        self,
        target_font_elem: pptx.text.text.Font,
        source_font_elem: pptx.text.text.Font,
        scale: float = 1.0,
    ) -> None:
        for attr in ('name', 'bold', 'italic', 'underline', 'language_id'):
            if value := getattr(source_font_elem, attr, None):
                setattr(target_font_elem, attr, value)
        if source_font_elem.size:
            target_font_elem.size = pptx.util.Pt(source_font_elem.size.pt * scale)

        match getattr(source_font_elem.color, 'type', None):
            case pptx.enum.dml.MSO_COLOR_TYPE.RGB:
                target_font_elem.color.rgb = getattr(
                    source_font_elem.color, 'rgb', None
                )
            case pptx.enum.dml.MSO_COLOR_TYPE.SCHEME:
                target_font_elem.color.theme_color = getattr(
                    source_font_elem.color, 'theme_color', None
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
                self._set_font(
                    run.font,
                    font,
                    scale=0.66 if idx > 0 and idx not in font_of_run else 1.0,
                )

    def add(self, appt: CalendarAppointmentBase) -> None:
        if not self._table:
            return
        if self._current_row >= self._total_rows:
            return
        local_start = appt.start_date.astimezone()
        if appt.all_day:
            date_and_time = f'{local_start:{self._date_format}}'
        elif self._weekly:
            date_and_time = (
                f'{local_start:{self._dayofweek_format} {self._time_format}}'
                if self._dayofweek_format
                else f'{local_start:{self._time_format}}'
            )
        else:
            date_and_time = f'{local_start:{self._date_format} {self._time_format}}'
        self._set_cell_text(self._table.cell(self._current_row, 0), date_and_time)
        self._set_cell_text(
            self._table.cell(self._current_row, 1),
            appt.title,
            appt.subtitle or appt.description or appt.link,
        )
        self._current_row += 1

    def fill(self) -> None:
        if not self._table:
            return
        for row in range(self._current_row, self._total_rows):
            self._set_cell_text(self._table.cell(row, 0), '')
            self._set_cell_text(self._table.cell(row, 1), '')


class PowerPointAppointments(PowerPointBase):
    def __init__(self, config: Configuration) -> None:
        super().__init__(config, config.appointments_template_pptx, config.output_dir)
        self._weekly_table = TableFiller(
            dayofweek_format=config.dayofweek_format,
            date_format=config.date_format,
            time_format=config.time_format,
            weekly=True,
        )
        self._irregular_table = TableFiller(
            dayofweek_format=config.dayofweek_format,
            date_format=config.date_format,
            time_format=config.time_format,
        )

    def create(
        self,
        appointments: typing.Iterable[CalendarAppointmentBase],
        from_date: datetime.datetime,
    ) -> None:
        for slide in self._prs.slides:
            for shape in slide.shapes:
                if (
                    isinstance(shape, pptx.shapes.graphfrm.GraphicFrame)
                    and shape.has_table
                ):
                    if 'weekly' in shape.name.lower():
                        self._weekly_table.set_table(shape.table)
                    elif 'irregular' in shape.name.lower():
                        self._irregular_table.set_table(shape.table)

        in_2hours = from_date + datetime.timedelta(hours=2)
        in_8days = from_date + datetime.timedelta(days=8)
        for appt in appointments:
            if appt.start_date < in_2hours:
                continue  # ignore appointments less than two hours away
            match (appt.repeat_id, appt.repeat_frequency):
                case (RepeatId.WEEKLY, 1) if appt.start_date < in_8days:
                    self._weekly_table.add(appt)
                case (RepeatId.WEEKLY, 1):
                    pass  # ignore weekly appointments more than one week away
                case _:
                    self._irregular_table.add(appt)

        self._weekly_table.fill()
        self._irregular_table.fill()
