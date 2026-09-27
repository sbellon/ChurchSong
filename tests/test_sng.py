# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import codecs
import pathlib

import pytest

from churchsong.songbeamer.sng import SngFile


@pytest.mark.parametrize(
    ('content', 'expected'),
    [
        (b'#Title=A\r\n#BackgroundImage=sky.jpg\r\n---\r\nVerse\r\n', True),
        (codecs.BOM_UTF8 + b'#BackgroundImage=sky.jpg\n#Title=A\n---\n', True),
        (b'#Title=A\r\n---\r\nVerse\r\n', False),
        # A verse line looking like the key is lyrics, not the header entry.
        (b'#Title=A\r\n---\r\n#BackgroundImage=sky.jpg\r\n', False),
        (b'', False),
    ],
)
def test_has_background_image_looks_at_the_header_only(
    content: bytes, *, expected: bool
) -> None:
    assert SngFile.has_background_image(SngFile(content).header) is expected


@pytest.mark.parametrize(
    ('content', 'header', 'body'),
    [
        (
            b'#Title=A\r\n#LangCount=1\r\n---\r\n#Verse\r\n',
            ['#Title=A\r\n', '#LangCount=1\r\n'],
            ['---\r\n', '#Verse\r\n'],
        ),
        (b'#Title=A', ['#Title=A'], []),
        (b'Verse\n', [], ['Verse\n']),
        (b'', [], []),
    ],
)
def test_lines_are_split_into_header_and_body(
    content: bytes, header: list[str], body: list[str]
) -> None:
    # The header ends at the first line that is no `#Key=Value` line, so that a
    # verse line starting with `#` belongs to the body.
    sng = SngFile(content)
    assert (sng.header, sng.body) == (header, body)


def test_lines_are_decoded_like_songbeamer_does() -> None:
    # With a byte order mark UTF-8, which is not part of the first line ...
    utf8 = SngFile(codecs.BOM_UTF8 + '#Title=Größer\r\n'.encode())
    assert utf8.header == ['#Title=Größer\r\n']
    # ... and without one the ANSI code page, even if the bytes are valid UTF-8.
    ansi = SngFile('#Title=Größer\n'.encode())
    assert ansi.header == ['#Title=GrÃ¶ÃŸer\n']


def test_lines_are_split_at_line_breaks_only() -> None:
    # U+2028 is a line break for `str.splitlines()`, but not for SongBeamer.
    sng = SngFile(codecs.BOM_UTF8 + '#Title=A\u2028B\n---\n'.encode())
    assert sng.header == ['#Title=A\u2028B\n']
    assert sng.body == ['---\n']


@pytest.mark.parametrize(
    'content',
    [
        b'#Title=Gr\xf6\xdfer\r\n---\r\nVerse \x81\r\n',  # \x81 is undefined in cp1252
        codecs.BOM_UTF8 + b'#Title=A\n---\nVerse \xff\n',  # \xff is invalid UTF-8
        b'#Title=A\r---\rVerse',  # old Mac line endings, no final line break
    ],
)
def test_unchanged_content_is_written_back_exactly(content: bytes) -> None:
    assert bytes(SngFile(content)) == content


def test_set_background_image_keeps_utf8_bom_and_crlf(tmp_path: pathlib.Path) -> None:
    sng = SngFile(codecs.BOM_UTF8 + '#Title=Größer\r\n---\r\nVerse ä\r\n'.encode())
    image = tmp_path / 'Hintergründe' / 'asset.jpg'
    sng.set_background_image(image)
    assert bytes(sng) == codecs.BOM_UTF8 + (
        f'#Title=Größer\r\n#BackgroundImage={image}\r\n---\r\nVerse ä\r\n'.encode()
    )
    assert SngFile.has_background_image(sng.header)


def test_set_background_image_writes_ansi_into_a_file_without_bom(
    tmp_path: pathlib.Path,
) -> None:
    # Bytes that are invalid in the code page have to survive untouched.
    sng = SngFile(b'#Title=Gr\xf6\xdfer\n---\nVerse \x81\n')
    image = tmp_path / 'Hintergründe' / 'asset.jpg'
    sng.set_background_image(image)
    assert bytes(sng) == (
        b'#Title=Gr\xf6\xdfer\n#BackgroundImage='
        + str(image).encode('cp1252')
        + b'\n---\nVerse \x81\n'
    )


def test_set_background_image_rejects_a_path_ansi_cannot_encode(
    tmp_path: pathlib.Path,
) -> None:
    content = b'#Title=A\r\n---\r\nVerse\r\n'
    sng = SngFile(content)
    with pytest.raises(UnicodeEncodeError):
        sng.set_background_image(tmp_path / '背景.jpg')
    assert bytes(sng) == content


def test_set_background_image_ends_the_line_like_the_first_line(
    tmp_path: pathlib.Path,
) -> None:
    # Old Mac line endings: a `\n` would join the lines for SongBeamer.
    sng = SngFile(b'#Title=A\r---\rVerse\r')
    sng.set_background_image(tmp_path / 'asset.jpg')
    assert bytes(sng) == (
        f'#Title=A\r#BackgroundImage={tmp_path / "asset.jpg"}\r---\rVerse\r'.encode()
    )


def test_set_background_image_into_a_header_without_final_line_break(
    tmp_path: pathlib.Path,
) -> None:
    sng = SngFile(b'#Title=A')
    sng.set_background_image(tmp_path / 'asset.jpg')
    assert bytes(sng) == (
        f'#Title=A\n#BackgroundImage={tmp_path / "asset.jpg"}\n'.encode()
    )


def test_set_background_image_uses_an_absolute_path(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    sng = SngFile(b'#Title=A\n---\n')
    sng.set_background_image(pathlib.Path('Backgrounds/asset.jpg'))
    assert str(tmp_path / 'Backgrounds' / 'asset.jpg').encode() in bytes(sng)


def test_read_and_write_round_trip_a_file(tmp_path: pathlib.Path) -> None:
    sng_file = tmp_path / 'song.sng'
    sng_file.write_bytes(codecs.BOM_UTF8 + b'#Title=A\r\n---\r\n')
    sng = SngFile.read(sng_file)
    sng.set_background_image(tmp_path / 'asset.jpg')
    sng.write(sng_file)
    assert SngFile.has_background_image(SngFile.read(sng_file).header)
    assert sng_file.read_bytes().startswith(codecs.BOM_UTF8 + b'#Title=A\r\n')
