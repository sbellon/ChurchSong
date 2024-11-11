import dataclasses
import os
import re
import subprocess
import sys

from configuration import Configuration

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


@dataclasses.dataclass
class AgendaItem:
    caption: str
    color: str
    bgcolor: str | None
    filename: str | None


class SongBeamer:
    _re_agenda_item = re.compile(
        r"""\s*item\r?\n
              \s*Caption\s=\s(?P<caption>.*?)\r?\n
              \s*Color\s=\s(?P<color>.*?)\r?\n
              (?:\s*FileName\s=\s(?P<filename>.*?)\r?\n)?
            \s*end\r?\n
        """,
        re.VERBOSE,
    )
    _preamble = 'object AblaufPlanItems: TAblaufPlanItems\n  items = <'
    _item_start = """
    item"""
    _item_caption = """
      Caption = {}"""
    _item_color = """
      Color = {}"""
    _item_bgcolor = """
      BGColor = {}"""
    _item_filename = """
      FileName = {}"""
    _item_end = """
    end"""
    _postamble = '>\nend'

    def __init__(self, config: Configuration) -> None:
        self._log = config.log
        self._temp_dir = config.temp_dir.resolve()
        self._schedule_filepath = self._temp_dir / 'Schedule.col'
        self._replacements = config.replacements

    def _parse_agenda_items(self, content: str) -> list[AgendaItem]:
        return [
            AgendaItem(
                caption=match.group('caption'),
                color=match.group('color'),
                bgcolor=None,
                filename=match.group('filename'),
            )
            for match in re.finditer(self._re_agenda_item, content)
        ]

    def _create_agenda_item(self, item: AgendaItem) -> str:
        result = self._item_start
        if item.caption:
            result += self._item_caption.format(item.caption)
        if item.color:
            result += self._item_color.format(item.color)
        if item.bgcolor:
            result += self._item_bgcolor.format(item.bgcolor)
        if item.filename:
            result += self._item_filename.format(item.filename)
        result += self._item_end
        return result

    def _replace_non_ascii(self, text: str) -> str:
        return re.sub(r'[^\x00-\x7F]', lambda x: f"'#{ord(x.group(0))}'", text)

    def modify_and_save_agenda(self, service_leads: dict[str, set[str]]) -> None:
        self._log.info('Modifying SongBeamer schedule')
        with self._schedule_filepath.open(mode='r', encoding='utf-8') as fd:
            content = fd.read()
        for search, replace in self._replacements:
            content = content.replace(search, replace)
        with self._schedule_filepath.open(mode='w', encoding='utf-8') as fd:
            fd.write(self._preamble)
            for item in self._parse_agenda_items(content):
                if not item.filename and item.color == '16711920':
                    item.color = 'clBlack'
                    item.bgcolor = 'clYellow'
                fd.write(self._create_agenda_item(item))
            for service, persons in sorted(service_leads.items()):
                caption = f"'{service}: {", ".join(sorted(persons))}'"
                fd.write(
                    self._create_agenda_item(
                        AgendaItem(
                            caption=self._replace_non_ascii(caption),
                            color='clBlack',
                            bgcolor='clAqua',
                            filename=None,
                        )
                    )
                )
            fd.write(self._postamble)

    def launch(self) -> None:
        self._log.info('Launching SongBeamer instance')
        if sys.platform == 'win32':
            subprocess.run(
                [os.environ.get('COMSPEC', 'cmd'), '/C', 'start Schedule.col'],
                check=True,
                cwd=self._temp_dir,
            )
        else:
            sys.stderr.write(
                f'Error: Starting SongBeamer not supported on {sys.platform}\n'
            )
            sys.exit(1)
