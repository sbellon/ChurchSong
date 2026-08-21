# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import pytest
import typer

from churchsong.churchtools import Arrangement, Song
from churchsong.churchtools.song_verification import (
    ChurchToolsSongVerification,
    SongChecks,
)


def make_arrangement(
    *,
    source: dict[str, str] | None = None,
    source_reference: str | None = None,
    duration: int | None = 180,
    files: list[dict[str, str]] | None = None,
    sng_lines: list[str] | None = None,
) -> Arrangement:
    arrangement = Arrangement.model_validate(
        {
            'id': 1,
            'name': 'Default',
            'isDefault': True,
            'source': source,
            'sourceReference': source_reference,
            'key': 'G',
            'beat': '4/4',
            'tempo': 72,
            'duration': duration,
            'files': files or [],
        }
    )
    if sng_lines is not None:
        arrangement.sng_file_content = sng_lines
    return arrangement


def make_song(
    *,
    author: str | None = 'John Newton',
    ccli: str | None = '22025',
    tags: list[str] | None = None,
    arrangements: list[Arrangement] | None = None,
) -> Song:
    return Song.model_validate(
        {
            'id': 42,
            'name': 'Amazing Grace',
            'author': author,
            'ccli': ccli,
            'arrangements': arrangements or [],
            'tags': [{'id': i, 'name': name} for i, name in enumerate(tags or [])],
        }
    )


def run_check(name: str, song: Song, arrangements: list[Arrangement]) -> list[str]:
    check = SongChecks.get(name)
    assert check is not None
    return check(song, arrangements)


def test_ccli_check_flags_missing_author_or_ccli() -> None:
    arrangements = [make_arrangement()]
    assert run_check('CCLI', make_song(), arrangements) == ['']
    assert run_check('CCLI', make_song(ccli=None), arrangements) == ['miss']
    assert run_check('CCLI', make_song(author=None), arrangements) == ['miss']


def test_source_check_flags_missing_source_reference() -> None:
    with_source = make_arrangement(
        source={'name': 'Feiert Jesus 5', 'shorty': 'FJ5'}, source_reference='123'
    )
    without_source = make_arrangement()
    assert run_check('Src.', make_song(), [with_source]) == ['']
    assert run_check('Src.', make_song(), [without_source]) == ['miss']


def test_duration_check_flags_missing_duration() -> None:
    assert run_check('Dur.', make_song(), [make_arrangement(duration=None)]) == ['miss']
    assert run_check('Dur.', make_song(), [make_arrangement()]) == ['']


def test_sng_file_check_flags_default_arrangement_without_sng_file() -> None:
    with_sng = make_arrangement(
        files=[{'name': 'song.sng', 'fileUrl': 'https://churchtools.test/f/1'}]
    )
    without_sng = make_arrangement(
        files=[{'name': 'chords.pdf', 'fileUrl': 'https://churchtools.test/f/2'}]
    )
    assert run_check('.sng', make_song(), [with_sng]) == ['']
    assert run_check('.sng', make_song(), [without_sng]) == ['miss']


def test_tags_check_flags_missing_source_tag() -> None:
    arrangement = make_arrangement(
        source={'name': 'Feiert Jesus 5', 'shorty': 'FJ5'}, source_reference='123'
    )
    assert run_check('Tags', make_song(tags=['FJ5 123']), [arrangement]) == ['']
    assert run_check('Tags', make_song(), [arrangement]) == ['miss "FJ5 123"']


def test_tags_check_flags_missing_en_de_tag_for_multilang_sng() -> None:
    arrangement = make_arrangement(sng_lines=['#LangCount=2', '#Title=Amazing Grace'])
    assert run_check('Tags', make_song(tags=['EN/DE']), [arrangement]) == ['']
    assert run_check('Tags', make_song(), [arrangement]) == ['miss "EN/DE"']


def test_bgimage_check_flags_sng_without_background_image() -> None:
    with_bg = make_arrangement(sng_lines=['#BackgroundImage=bg.jpg'])
    without_bg = make_arrangement(sng_lines=['#Title=Amazing Grace'])
    no_content = make_arrangement()
    assert run_check('BGImg', make_song(), [with_bg]) == ['']
    assert run_check('BGImg', make_song(), [without_bg]) == ['miss']
    assert run_check('BGImg', make_song(), [no_content]) == ['']


def test_languages_check_flags_en_de_tagged_song_without_lang_markers() -> None:
    song = make_song(tags=['EN/DE'])
    incomplete = make_arrangement(sng_lines=['#Title=Amazing Grace'])
    complete = make_arrangement(sng_lines=['#LangCount=2', '#TitleLang2=Gnade'])
    assert run_check('#Lang', song, [incomplete]) == [
        'miss #LangCount, miss #TitleLang'
    ]
    assert run_check('#Lang', song, [complete]) == ['']


def test_registry_rejects_duplicate_registration() -> None:
    with pytest.raises(RuntimeError, match='already registered'):
        SongChecks.register('CCLI')(lambda _song, _arrangements: [])


def test_sng_file_content_requirement_is_detected_from_source() -> None:
    checks = SongChecks.available_checks()
    needs = {
        name: ChurchToolsSongVerification._is_sng_file_content_required(check)  # noqa: SLF001 # pyright: ignore[reportPrivateUsage]
        for name, check in checks.items()
    }
    assert needs['BGImg'] is True
    assert needs['#Lang'] is True
    assert needs['CCLI'] is False
    assert needs['Src.'] is False


def test_validate_checks_accepts_known_and_rejects_unknown() -> None:
    assert ChurchToolsSongVerification.validate_checks('CCLI,Tags') == 'CCLI,Tags'
    with pytest.raises(typer.BadParameter, match='not a valid check'):
        ChurchToolsSongVerification.validate_checks('NoSuchCheck')
