import datetime
import os
import pathlib
import re
import subprocess
import sys
import typing

from configuration import Configuration
from utils import string

r"""
SongBeamer agenda items look something like this:

  item
    KEY = VAL
    KEY = VAL
    ...
  end

With the following known KEYs:

- Caption: enclosed in single quote, e.g.
    Caption = 'This is a caption'

- Color: color like clBlack, clBlue, clAqua, or intger value, e.g.
    Color = clBlack
  or
    Color = 16711920

- BGColor: same as Color, e.g.
    BGColor = clYellow

- FileName: enclosed in single quotes, single-line and multi-line possible:
    FileName = 'some\path\document.txt'
    FileName =
      'some\path\doc' +
      'ument.txt'
  .strip("'") first, then concatenate, then translate

- Props: array with properties, e.g.
    Props = []

- AdvProps: multi-line string with properties, e.g.
    AdvProps = (
      'Video.EndAction=stop'
      'Video.Loop=false')

- Lang: selected song language, e.g.
    Lang = (
      1)
  or
    Lang = (
      2)

- StreamClass: information for embedded binary streaming data, e.g.
    StreamClass = 'TPresentationSlideShow'

- GUID: e.g.
    GUID = '{EE688E14-9FF7-11EF-8000-08BFB8140608}'
- Data: some binary encoded data, e.g.

    Data = {
      01234567890ABCDEF
      01234567890}

Parsing rules for VAL:

- Non-ASCII characters need escaping with the following syntax:

    'some'#252'mlaut'

  where chr(x) is the #x character.

- For multi-line values, use the following:

    1. "".join(line.strip("'") for line in multi_line)
    2. handle the '#x' non-ascii characters

For importing a ChurchTools export, we most likely only have to handle:
    - Caption
    - Color
    - FileName (optional)

And the values are all single-line, which makes parsing actually simple.
"""


class AgendaItem:
    _re_agenda_item = re.compile(
        r"""\s*item\r?\n
              \s*Caption\s=\s(?P<caption>.*?)\r?\n
              \s*Color\s=\s(?P<color>.*?)\r?\n
              (?:\s*BGColor\s=\s(?P<bgcolor>.*?)\r?\n)?
              (?:\s*FileName\s=\s(?P<filename>.*?)\r?\n)?
            \s*end\r?\n
        """,
        re.VERBOSE,
    )

    def __init__(
        self,
        caption: str,
        color: str,
        bgcolor: str | None = None,
        filename: str | None = None,
        *,
        songs_dir: pathlib.Path | None = None,
    ) -> None:
        self.caption = self._decode(caption)
        self.color = color
        self.bgcolor = bgcolor
        if filename:
            filename = self._decode(filename)
            if filename.endswith('.sng') and songs_dir:
                self.filename = os.fspath(songs_dir / filename)
            else:
                self.filename = filename
        else:
            self.filename = None

    @staticmethod
    def _toggle_quotes(text: str) -> str:
        text = text[1:] if text.startswith("'") else f"'{text}"
        return text[:-1] if text.endswith("'") else f"{text}'"

    @staticmethod
    def _decode(text: str) -> str:
        text = AgendaItem._toggle_quotes(text)
        return re.sub(r"'#(\d+)'", lambda x: chr(int(x.group(1))), text)

    @staticmethod
    def _encode(text: str) -> str:
        text = re.sub(r'[^\x00-\x7F]', lambda x: f"'#{ord(x.group(0))}'", text)
        return AgendaItem._toggle_quotes(text)

    @classmethod
    def parse(
        cls, content: str, songs_dir: pathlib.Path | None = None
    ) -> list[typing.Self]:
        return [
            cls(
                caption=match.group('caption'),
                color=match.group('color'),
                bgcolor=match.group('bgcolor'),
                filename=match.group('filename'),
                songs_dir=songs_dir,
            )
            for match in re.finditer(cls._re_agenda_item, content)
        ]

    def __str__(self) -> str:
        result = '\n    item'
        result += f'\n      Caption = {self._encode(self.caption)}'
        result += f'\n      Color = {self.color}'
        if self.bgcolor:
            result += f'\n      BGColor = {self.bgcolor}'
        if self.filename:
            result += f'\n      FileName = {self._encode(self.filename)}'
        result += '\n    end'
        return string.expand_envvars(result)


class Agenda:
    def __init__(
        self,
        agenda_items: list[AgendaItem] | None = None,
        *,
        songs_dir: pathlib.Path | None = None,
    ) -> None:
        self._agenda_items = agenda_items if agenda_items else []
        self._songs_dir = songs_dir

    def parse(self, content: str) -> list[AgendaItem]:
        return AgendaItem.parse(content, self._songs_dir)

    def __iadd__(self, other: AgendaItem | list[AgendaItem]) -> typing.Self:
        if isinstance(other, AgendaItem):
            self._agenda_items.append(other)
        elif isinstance(other, list):
            self._agenda_items += other
        else:
            raise TypeError(  # noqa: TRY003
                'Unsupported operand type(s) for +=: '  # noqa: EM102
                f"'Agenda' and '{type(other).__name__}'"
            )
        return self

    def __iter__(self) -> typing.Iterator[AgendaItem]:
        return iter(self._agenda_items)

    def __str__(self) -> str:
        result = 'object AblaufPlanItems: TAblaufPlanItems\n  items = <'
        for item in self._agenda_items:
            result += str(item)
        result += '>\nend'
        return result

    def change_color(
        self,
        from_color: str,
        to_color: str | None = None,
        to_bgcolor: str | None = None,
    ) -> None:
        for item in self._agenda_items:
            if item.color == from_color:
                item.color = to_color if to_color else item.color
                item.bgcolor = to_bgcolor if to_bgcolor else item.bgcolor


class SongBeamer:
    def __init__(self, config: Configuration) -> None:
        self._log = config.log
        self._temp_dir = config.temp_dir.resolve()
        self._songs_dir = self._temp_dir / 'Songs'
        self._schedule_filepath = self._temp_dir / 'Schedule.col'
        self._event_datetime_format = config.event_datetime_format
        self._opening_slides = config.opening_slides
        self._closing_slides = config.closing_slides
        self._insert_slides = config.insert_slides
        self._color_service = config.color_service
        self._color_replacements = config.color_replacements

    def modify_and_save_agenda(
        self, event_date: datetime.datetime, service_leads: dict[str, set[str]]
    ) -> None:
        self._log.info('Modifying SongBeamer schedule')
        with self._schedule_filepath.open(mode='r', encoding='utf-8') as fd:
            content = fd.read()

        # Set environment variable(s) for use in agenda items in configuration.
        os.environ['CHURCHSONG_EVENT_DATETIME'] = (
            f'{event_date.astimezone():{self._event_datetime_format}}'
        )

        agenda = Agenda(songs_dir=self._songs_dir)
        for item in (
            agenda.parse(self._opening_slides)
            + agenda.parse(content)
            + agenda.parse(self._closing_slides)
        ):
            agenda += item
            for slide in self._insert_slides:
                if any(keyword in item.caption for keyword in slide.keywords):
                    agenda += agenda.parse(slide.content)
        for service, persons in sorted(service_leads.items()):
            agenda += AgendaItem(
                caption=f"'{service}: {", ".join(sorted(persons))}'",
                color=self._color_service.color,
                bgcolor=self._color_service.bgcolor,
            )
        for replacement in self._color_replacements:
            agenda.change_color(
                replacement.match_color, replacement.color, replacement.bgcolor
            )

        with self._schedule_filepath.open(mode='w', encoding='utf-8') as fd:
            fd.write(str(agenda))

    def launch(self) -> None:
        self._log.info('Launching SongBeamer instance')
        if sys.platform == 'win32':
            subprocess.run(  # noqa: S603
                [os.environ.get('COMSPEC', 'cmd'), '/C', 'start Schedule.col'],
                check=True,
                cwd=self._temp_dir,
            )
        else:
            sys.stderr.write(
                f'Error: Starting SongBeamer not supported on {sys.platform}\n'
            )
            sys.exit(1)
