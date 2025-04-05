import datetime
import os
import re
import subprocess
import sys
import typing

from churchsong import utils
from churchsong.churchtools.events import Item

if typing.TYPE_CHECKING:
    from churchsong.configuration import Configuration, SongBeamerColorConfig

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

- Color: predefined color like clBlack, clMaroon, clGreen, clOlive, clNavy, clPurple,
         clTeal, clGray, clSilver, clRed, clLime, clYellow, clBlue, clFuchsia, clAqua,
         clWhite or integer value, e.g.
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
        color: str,
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
        text = re.sub(r"[^\x00-\x7F]|'", lambda x: f"'#{ord(x.group(0))}'", text)
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
    def __init__(self, *, colors: 'SongBeamerColorConfig') -> None:
        self._agenda_items: list[AgendaItem] = []
        self._colors = colors

    def __iadd__(self, other: AgendaItem | Item) -> typing.Self:
        match other:
            case AgendaItem():
                self._agenda_items.append(other)
            case Item():
                color_attr = getattr(self._colors, other.type.value)
                color = color_attr.color
                bgcolor = color_attr.bgcolor
                self._agenda_items.append(
                    AgendaItem(
                        caption=f"'{other.title}'",
                        color=color,
                        bgcolor=bgcolor,
                        filename=f"'{other.filename}'" if other.filename else None,
                    )
                )
            case _:
                msg = (
                    'Unsupported operand type(s) for +=: '
                    f'"Agenda" and "{type(other).__name__}"'
                )
                raise TypeError(msg)
        return self

    def __getitem__(self, index: int) -> AgendaItem:
        return self._agenda_items[index]

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
        self._schedule_filepath = self._temp_dir / 'Schedule.col'
        self._event_datetime_format = config.event_datetime_format
        self._opening_slides = config.opening_slides
        self._closing_slides = config.closing_slides
        self._insert_slides = config.insert_slides
        self._colors = config.colors

    def create_schedule(
        self,
        *,
        event_date: datetime.datetime,
        agenda_items: list[Item],
        service_items: list[Item],
    ) -> None:
        self._log.info('Creating SongBeamer Schedule.col')

        # Set environment variable(s) for use in agenda items in configuration.
        os.environ['CHURCHSONG_EVENT_DATETIME'] = (
            f'{event_date.astimezone():{self._event_datetime_format}}'
        )

        agenda = Agenda(colors=self._colors)
        for agenda_item in (
            AgendaItem.parse(self._opening_slides)
            + agenda_items
            + AgendaItem.parse(self._closing_slides)
            + service_items
        ):
            agenda += agenda_item
            for slide in self._insert_slides:
                if any(keyword in agenda[-1].caption for keyword in slide.keywords):
                    for insert_item in AgendaItem.parse(slide.content):
                        agenda += insert_item

        with self._schedule_filepath.open(mode='w', encoding='utf-8') as fd:
            fd.write(str(agenda))

    def launch(self) -> None:
        self._log.info('Launching SongBeamer instance')
        if sys.platform == 'win32':
            from churchsong.songbeamer import windows

            if windows.is_songbeamer_running():
                already_running_notice = _(
                    """SongBeamer is already running.

If you have modified your agenda but not saved it,
SongBeamer will ask now whether you want to save the agenda.

Answer:

- Yes: save and keep your modified agenda.
- No: discard your changes and reload agenda from ChurchTools.
- Cancel: keep your modified agenda but do not save it.

The PowerPoint slides will get updated in any case!

Click OK to continue.
"""
                )
                windows.open_message_box(self._app_name, already_running_notice)
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
