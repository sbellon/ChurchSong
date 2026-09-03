# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import datetime
import pathlib
import subprocess
import sys
import typing

import pytest

import churchsong.songbeamer
from churchsong.churchtools.events import Item, ItemType
from churchsong.configuration import SongBeamerColorConfig, SongBeamerColorItemConfig
from churchsong.songbeamer import Agenda, AgendaItem, SongBeamer
from churchsong.utils import CliError
from tests.conftest import make_config


@pytest.mark.parametrize(
    ('decoded', 'encoded'),
    [
        ('', "''"),
        ('plain ascii', "'plain ascii'"),
        ('Mögen', "'M'#246'gen'"),
        ("it's", "'it'#39's'"),
        ('äöü', '#228#246#252'),
        ('Überfluß', "#220'berflu'#223"),
    ],
)
def test_encode(decoded: str, encoded: str) -> None:
    assert AgendaItem._encode(decoded) == encoded  # noqa: SLF001 # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    'text',
    ['', 'plain', 'Möge die Straße', "it's a 'quoted' text", 'äöü', '#no #escape'],
)
def test_encode_decode_round_trip(text: str) -> None:
    assert AgendaItem._decode(AgendaItem._encode(text)) == text  # noqa: SLF001 # pyright: ignore[reportPrivateUsage]


def test_parse_extracts_all_fields() -> None:
    content = (
        'object AblaufPlanItems: TAblaufPlanItems\n'
        '  items = <\n'
        '    item\n'
        "      Caption = 'M'#246'ge die Stra'#223'e'\n"
        '      Color = clBlue\n'
        '    end\n'
        '    item\n'
        "      Caption = 'Notes'\n"
        '      Color = clBlack\n'
        '      BGColor = clYellow\n'
        "      FileName = 'C:\\path\\notes.txt'\n"
        '    end>\n'
        'end\n'
    )
    first, second = AgendaItem.parse(content)
    assert first.caption == 'Möge die Straße'
    assert first.color == 'clBlue'
    assert first.bgcolor is None
    assert first.filename is None
    assert second.caption == 'Notes'
    assert second.bgcolor == 'clYellow'
    assert second.filename == 'C:\\path\\notes.txt'


def test_agenda_item_str_parses_back_identically() -> None:
    item = AgendaItem(
        caption="Über'm Weg",
        color='clBlue',
        bgcolor='clYellow',
        filename='C:\\path\\über.txt',
    )
    (parsed,) = AgendaItem.parse(f'{item}\n')
    assert parsed.caption == item.caption
    assert parsed.color == item.color
    assert parsed.bgcolor == item.bgcolor
    assert parsed.filename == item.filename


@pytest.mark.parametrize(
    ('url', 'expected'),
    [
        (
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'https://www.youtube.com/embed/dQw4w9WgXcQ',
        ),
        (
            'https://youtu.be/dQw4w9WgXcQ',
            'https://www.youtube.com/embed/dQw4w9WgXcQ',
        ),
        (
            'https://example.test/watch?v=dQw4w9WgXcQ',
            'https://example.test/watch?v=dQw4w9WgXcQ',
        ),
        (
            'C:\\path\\file.txt',
            'C:\\path\\file.txt',
        ),
    ],
)
def test_filename_youtube_links_are_rewritten_to_embed_urls(
    url: str, expected: str
) -> None:
    item = AgendaItem(caption='Video', color='clBlack', filename=url)
    assert item.filename == expected


def test_agenda_maps_item_type_to_configured_colors() -> None:
    colors = SongBeamerColorConfig(
        Song=SongBeamerColorItemConfig(color='clGreen', bgcolor='clYellow')
    )
    agenda = Agenda(colors=colors)
    agenda += Item(type=ItemType.HEADER, title='Welcome')
    agenda += Item(type=ItemType.SONG, title='Amazing Grace', filename='grace.sng')
    assert agenda[0].color == 'clBlack'
    assert agenda[0].bgcolor is None
    assert agenda[1].color == 'clGreen'
    assert agenda[1].bgcolor == 'clYellow'
    assert agenda[1].filename == 'grace.sng'


def test_agenda_str_produces_schedule_col_document() -> None:
    agenda = Agenda(colors=SongBeamerColorConfig())
    agenda += Item(type=ItemType.SONG, title='Amazing Grace')
    text = str(agenda)
    assert text.startswith('object AblaufPlanItems: TAblaufPlanItems\n  items = <')
    assert "Caption = 'Amazing Grace'" in text
    assert text.endswith('>\nend')


def test_agenda_rejects_unsupported_operand() -> None:
    agenda = Agenda(colors=SongBeamerColorConfig())
    with pytest.raises(TypeError, match='Unsupported operand'):
        agenda += typing.cast('Item', 'not an item')


def test_create_schedule_assembles_slides_agenda_and_services(
    tmp_path: pathlib.Path,
) -> None:
    config = make_config(
        output_dir=str(tmp_path),
        songbeamer={
            'Slides': {
                'datetime_format': '%d.%m.%Y %H:%M',
                'Opening': {
                    'content': "item\n  Caption = 'Opening'\n  Color = clBlack\nend\n"
                },
                'Closing': {
                    'content': "item\n  Caption = 'Closing'\n  Color = clBlack\nend\n"
                },
                'Insert': [
                    {
                        'keywords': ['Infos'],
                        'content': (
                            "item\n  Caption = 'Information'\n  Color = clRed\nend\n"
                        ),
                    }
                ],
            }
        },
    )
    event_date = datetime.datetime(2026, 8, 23, 10, 0, tzinfo=datetime.UTC)
    SongBeamer(config).create_schedule(
        event_date=event_date,
        agenda_items=[
            Item(ItemType.SONG, 'Amazing Grace', filename='grace.sng'),
            Item(ItemType.HEADER, 'Infos'),
        ],
        service_items=[Item(ItemType.SERVICE, 'Music: Jane Doe')],
    )
    content = (tmp_path / 'Schedule.col').read_text(encoding='utf-8')
    captions = [item.caption for item in AgendaItem.parse(content)]
    assert captions == [
        f'{event_date.astimezone():%d.%m.%Y %H:%M}',
        'Opening',
        'Amazing Grace',
        'Infos',
        'Information',  # insert slide triggered by the keyword
        'Closing',
        'Music: Jane Doe',
    ]


def test_agenda_is_iterable() -> None:
    agenda = Agenda(colors=SongBeamerColorConfig())
    agenda += Item(type=ItemType.HEADER, title='Welcome')
    agenda += Item(type=ItemType.SONG, title='Amazing Grace')
    assert [item.caption for item in agenda] == ['Welcome', 'Amazing Grace']


def test_encode_decode_round_trip_of_random_texts() -> None:
    # The module ships its own fuzzing round-trip check.
    AgendaItem._test_encode_decode()  # noqa: SLF001 # pyright: ignore[reportPrivateUsage]


class FakeWindows:
    """Stands in for the win32-only churchsong.songbeamer.windows module."""

    def __init__(
        self, *, running: bool = False, start_error: Exception | None = None
    ) -> None:
        self.calls: list[str] = []
        self._running = running
        self._start_error = start_error

    def is_songbeamer_running(self) -> bool:
        return self._running

    def open_message_box(self, _title: str, _message: str) -> None:
        self.calls.append('message_box')

    def bring_songbeamer_window_to_front(self) -> None:
        self.calls.append('to_front')

    def start_songbeamer(self, cwd: pathlib.Path) -> None:
        self.calls.append(f'start:{cwd}')
        if self._start_error:
            raise self._start_error


def install_fake_windows(monkeypatch: pytest.MonkeyPatch, fake: FakeWindows) -> None:
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(churchsong.songbeamer, 'windows', fake, raising=False)


def test_launch_is_unsupported_off_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    with pytest.raises(CliError, match='not supported on linux'):
        SongBeamer(make_config(output_dir=str(tmp_path))).launch()


def test_launch_starts_songbeamer_in_the_output_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    fake = FakeWindows()
    install_fake_windows(monkeypatch, fake)
    SongBeamer(make_config(output_dir=str(tmp_path))).launch()
    assert fake.calls == [f'start:{tmp_path.resolve()}']


def test_launch_notifies_about_an_already_running_songbeamer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    fake = FakeWindows(running=True)
    install_fake_windows(monkeypatch, fake)
    SongBeamer(make_config(output_dir=str(tmp_path))).launch()
    # The user is warned about the unsaved agenda before SongBeamer reloads it.
    assert fake.calls == [
        'message_box',
        'to_front',
        f'start:{tmp_path.resolve()}',
    ]


def test_launch_reports_a_failing_songbeamer_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    error = subprocess.CalledProcessError(returncode=1, cmd=['SongBeamer.exe'])
    install_fake_windows(monkeypatch, FakeWindows(start_error=error))
    with pytest.raises(CliError, match='Cannot start SongBeamer'):
        SongBeamer(make_config(output_dir=str(tmp_path))).launch()


def test_create_schedule_keeps_the_previous_schedule_if_it_cannot_be_replaced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    schedule = tmp_path / 'Schedule.col'
    schedule.write_text('previous schedule', encoding='utf-8')

    def failing_replace(_self: pathlib.Path, _target: object) -> typing.NoReturn:
        msg = 'No space left on device'
        raise OSError(msg)

    monkeypatch.setattr(pathlib.Path, 'replace', failing_replace)
    with pytest.raises(CliError, match='Cannot write'):
        SongBeamer(make_config(output_dir=str(tmp_path))).create_schedule(
            event_date=datetime.datetime(2026, 8, 23, 10, 0, tzinfo=datetime.UTC),
            agenda_items=[Item(ItemType.SONG, 'Amazing Grace')],
            service_items=[],
        )

    assert schedule.read_text(encoding='utf-8') == 'previous schedule'
    assert list(tmp_path.iterdir()) == [schedule]  # no temporary file left behind


def test_create_schedule_writes_crlf_line_endings(tmp_path: pathlib.Path) -> None:
    SongBeamer(make_config(output_dir=str(tmp_path))).create_schedule(
        event_date=datetime.datetime(2026, 8, 23, 10, 0, tzinfo=datetime.UTC),
        agenda_items=[Item(ItemType.SONG, 'Amazing Grace')],
        service_items=[],
    )
    # SongBeamer's own line ending, independent of the platform generating it.
    content = (tmp_path / 'Schedule.col').read_bytes()
    assert b'\r\n' in content
    assert b'\n' not in content.replace(b'\r\n', b'')
