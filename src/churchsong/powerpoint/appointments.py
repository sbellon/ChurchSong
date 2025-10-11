# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import datetime
import enum
import typing

import pptx.enum.dml
import pptx.shapes.graphfrm
import pptx.table
import pptx.text.text
import pptx.util

from churchsong.churchtools import RepeatId
from churchsong.configuration import CalendarSubtitleField
from churchsong.powerpoint import PowerPointBase

if typing.TYPE_CHECKING:
    from churchsong.churchtools import CalendarAppointmentBase
    from churchsong.configuration import Configuration


class TableType(enum.StrEnum):
    WEEKLY = 'Weekly Table'
    IRREGULAR = 'Irregular Table'


class TableFiller:
    type: typing.ClassVar[str]

    def __init__(  # noqa: PLR0913
        self,
        config: Configuration,
        table_type: TableType,
        regular_datetime_format: str,
        allday_datetime_format: str,
        multiday_datetime_format: str,
        subtitle_prio: list[CalendarSubtitleField],
    ) -> None:
        self._log = config.log
        self._table = None
        self._font = None
        self._total_rows = 0
        self._current_row = 0
        self._table_type = table_type
        self._regular_fmt = regular_datetime_format
        self._allday_fmt = allday_datetime_format
        self._multiday_fmt = multiday_datetime_format
        self._subtitle_prio = subtitle_prio
        self._unset_table_warning = False

    @property
    def table_type(self) -> str:
        return self._table_type

    def set_table(self, table: pptx.table.Table) -> None:
        if self._table:
            self._log.warning('%s already set, not setting again', self._table_type)
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

    def _date_and_time(self, appt: CalendarAppointmentBase) -> str:
        local_start = appt.start_date.astimezone()
        local_end = appt.end_date.astimezone()
        return (
            f'{local_start:{self._multiday_fmt}} - {local_end:{self._multiday_fmt}}'
            if (local_start.month, local_start.day) != (local_end.month, local_end.day)
            else f'{local_start:{self._allday_fmt}}'
            if appt.all_day
            else f'{local_start:{self._regular_fmt}}'
        )

    def _subtitle(self, appt: CalendarAppointmentBase) -> str:
        for subtitle in self._subtitle_prio:
            match subtitle:
                case CalendarSubtitleField.SUBTITLE if appt.subtitle:
                    return appt.subtitle
                case CalendarSubtitleField.DESCRIPTION if appt.description:
                    return appt.description
                case CalendarSubtitleField.LINK if appt.link:
                    return appt.link
                case CalendarSubtitleField.ADDRESS if appt.address:
                    city = f'{appt.address.zip or ""} {appt.address.city or ""}'.strip()
                    if address := (
                        ', '.join(
                            part
                            for part in [appt.address.name, appt.address.street, city]
                            if part
                        )
                    ):
                        return address
                case _:
                    pass
        return ''

    def add(self, appt: CalendarAppointmentBase) -> None:
        if not self._table:
            # Safeguard, no table registered.
            if not self._unset_table_warning:
                self._unset_table_warning = True
                self._log.warning(
                    '%s unset, ignoring all appointments', self._table_type
                )
            return
        if self._current_row >= self._total_rows:
            # All available table rows have been filled.
            self._log.info('%s is full, dropping "%s"', self._table_type, appt.title)
            return
        self._set_cell_text(
            self._table.cell(self._current_row, 0),
            self._date_and_time(appt),
        )
        self._set_cell_text(
            self._table.cell(self._current_row, 1),
            appt.title,
            self._subtitle(appt),
        )
        self._current_row += 1

    def fill(self) -> None:
        if not self._table:
            # Safeguard, no table registered.
            return
        for row in range(self._current_row, self._total_rows):
            self._set_cell_text(self._table.cell(row, 0), '')
            self._set_cell_text(self._table.cell(row, 1), '')


class PowerPointAppointments(PowerPointBase):
    def __init__(self, config: Configuration) -> None:
        config.log.info('Creating PowerPoint appointments slides')
        super().__init__(
            config, config.songbeamer.powerpoint.appointments.template_pptx
        )
        self._weekly_table = TableFiller(
            config=config,
            table_type=TableType.WEEKLY,
            regular_datetime_format=config.songbeamer.powerpoint.appointments.weekly.regular_datetime_format,
            allday_datetime_format=config.songbeamer.powerpoint.appointments.weekly.allday_datetime_format,
            multiday_datetime_format=config.songbeamer.powerpoint.appointments.weekly.multiday_datetime_format,
            subtitle_prio=config.songbeamer.powerpoint.appointments.weekly.subtitle_priority,
        )
        self._irregular_table = TableFiller(
            config=config,
            table_type=TableType.IRREGULAR,
            regular_datetime_format=config.songbeamer.powerpoint.appointments.irregular.regular_datetime_format,
            allday_datetime_format=config.songbeamer.powerpoint.appointments.irregular.allday_datetime_format,
            multiday_datetime_format=config.songbeamer.powerpoint.appointments.irregular.multiday_datetime_format,
            subtitle_prio=config.songbeamer.powerpoint.appointments.irregular.subtitle_priority,
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
                        case self._weekly_table.table_type:
                            self._weekly_table.set_table(shape.table)
                        case self._irregular_table.table_type:
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
