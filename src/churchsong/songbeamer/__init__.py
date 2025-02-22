import datetime
import os
import pathlib
import re
import subprocess
import sys
import typing

from churchsong import utils
from churchsong.churchtools.events import Person

if typing.TYPE_CHECKING:
    from churchsong.churchtools.events import AgendaFileItem
    from churchsong.configuration import (
        Configuration,
        SongBeamerColorReplacementsConfig,
    )

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

- Color: color like clBlack, clBlue, clAqua, or integer value, e.g.
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

- VerseOrder: description of verse order like #VerseOrder in .sng, e.g.
    VerseOrder = 'Verse 1,Chorus 1,Verse 2,Chorus 1,Misc 1,Chorus 1'

- Lang: selected song language, e.g.
    Lang = (
      1)
  or
    Lang = (
      2)

- AdvProps: multi-line string with properties, e.g.
    AdvProps = (
      'Video.EndAction=stop'
      'Video.Loop=false')

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
            \s*end>?\r?\n
        """,
        re.VERBOSE,
    )
    _replacements: typing.ClassVar = {
        # key: regexp to match with appropriate match group names
        # val: replacement with match group names using str.format()
        re.compile(
            # Regex inspired from https://stackoverflow.com/a/51870158
            r"""(https?://)?                               # Optional protocol.
                (                                          # Group up to Video ID.
                  ((m|www)\.)?                             # Optional subdomain.
                  (youtube(-nocookie)?|youtube.googleapis) # Possible domains.
                  \.com                                    # The .com at the end.
                  .*                                       # Match anything.
                                                           # ^ restricts to youtube URL.
                                                           # v finds the Video ID.
                  (v/|v=|vi=|vi/|e/|embed/|user/.*/u/\d+/) # Poss. before Video ID.
                  |                                        # Alternatively:
                  youtu\.be/                               # The link-shortening domain.
                )                                          # End of group.
                (?P<match>[0-9A-Za-z_-]{11})               # Video ID as match group.
            """,
            re.VERBOSE,
        ): 'https://www.youtube.com/embed/{match}'
    }

    def __init__(
        self,
        caption: str,
        color: str = 'clBlack',
        bgcolor: str | None = None,
        filename: str | None = None,
    ) -> None:
        self.caption = self._decode(caption)
        self.color = color
        self.bgcolor = bgcolor
        self.filename = self._fixup_links(self._decode(filename)) if filename else None

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
        return result if (result := AgendaItem._toggle_quotes(text)) else "''"

    @classmethod
    def _fixup_links(cls, url: str) -> str:
        for regexp, replacement in cls._replacements.items():
            if m := regexp.match(url):
                url = replacement.format(**m.groupdict())
        return url

    @classmethod
    def parse(cls, content: str) -> list[typing.Self]:
        return [
            cls(
                caption=match.group('caption'),
                color=match.group('color'),
                bgcolor=match.group('bgcolor'),
                filename=match.group('filename'),
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
        return utils.expand_envvars(result)


class Agenda:
    def __init__(
        self,
        *,
        songs_dir: pathlib.Path | None = None,
        color_replacements: list['SongBeamerColorReplacementsConfig'] | None = None,
    ) -> None:
        self._agenda_items = []
        self._songs_dir = songs_dir
        self._color_replacements = color_replacements or []

    def __iadd__(self, other: AgendaItem | list[AgendaItem]) -> typing.Self:
        if isinstance(other, AgendaItem):
            if self._songs_dir and other.filename and other.filename.endswith('.sng'):
                other.filename = os.fspath(self._songs_dir / other.filename)
            for rep in self._color_replacements:
                if other.color == rep.match_color:
                    other.color = rep.color if rep.color else other.color
                    other.bgcolor = rep.bgcolor if rep.bgcolor else other.bgcolor
            self._agenda_items.append(other)
        elif isinstance(other, list):
            for item in other:
                self += item
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


class SongBeamer:
    def __init__(self, config: 'Configuration') -> None:
        self._log = config.log
        self._app_name = config.package_name
        self._temp_dir = config.temp_dir.resolve()
        self._songs_dir = self._temp_dir / 'Songs'
        self._schedule_filepath = self._temp_dir / 'Schedule.col'
        self._event_datetime_format = config.event_datetime_format
        self._opening_slides = config.opening_slides
        self._closing_slides = config.closing_slides
        self._insert_slides = config.insert_slides
        self._color_service = config.color_service
        self._color_replacements = config.color_replacements
        self._already_running_notice = config.already_running_notice

    def modify_and_save_agenda(
        self,
        event_date: datetime.datetime,
        service_leads: dict[str, set[Person]],
        event_files: list['AgendaFileItem'],
    ) -> None:
        self._log.info('Modifying SongBeamer schedule')
        with self._schedule_filepath.open(mode='r', encoding='utf-8') as fd:
            schedule_content = fd.read()

        # Set environment variable(s) for use in agenda items in configuration.
        os.environ['CHURCHSONG_EVENT_DATETIME'] = (
            f'{event_date.astimezone():{self._event_datetime_format}}'
        )

        agenda = Agenda(
            songs_dir=self._songs_dir, color_replacements=self._color_replacements
        )
        for agenda_item in (
            AgendaItem.parse(self._opening_slides)
            + [
                AgendaItem(
                    caption=f"'{event_file.title}'", filename=f"'{event_file.filename}'"
                )
                for event_file in event_files
            ]
            + AgendaItem.parse(schedule_content)
            + AgendaItem.parse(self._closing_slides)
            + [
                AgendaItem(
                    caption=f"'{serv}: {', '.join(sorted(p.fullname for p in pers))}'",
                    color=self._color_service.color,
                    bgcolor=self._color_service.bgcolor,
                )
                for serv, pers in sorted(service_leads.items())
            ]
        ):
            agenda += agenda_item
            for slide in self._insert_slides:
                if any(keyword in agenda_item.caption for keyword in slide.keywords):
                    agenda += AgendaItem.parse(slide.content)

        with self._schedule_filepath.open(mode='w', encoding='utf-8') as fd:
            fd.write(str(agenda))

    def launch(self) -> None:
        self._log.info('Launching SongBeamer instance')
        if sys.platform == 'win32':
            from churchsong.songbeamer import windows

            if self._already_running_notice and windows.is_songbeamer_running():
                windows.open_message_box(self._app_name, self._already_running_notice)
                windows.bring_songbeamer_window_to_front()

            try:
                windows.start_songbeamer(self._temp_dir)
            except subprocess.CalledProcessError as e:
                self._log.error(e)
                sys.stderr.write(f'Error: cannot start SongBeamer: {e}\n')
                sys.exit(e.returncode)
        else:
            sys.stderr.write(
                f'Error: Starting SongBeamer not supported on {sys.platform}\n'
            )
            sys.exit(1)
