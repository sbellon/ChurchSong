# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import datetime
import logging
import typing

import pytest
import typer
from responses import matchers

from churchsong.churchtools import MAX_SONGS_PAGE_SIZE, Arrangement, Song
from churchsong.churchtools.song_verification import (
    ChurchToolsSongVerification,
    SongChecks,
)
from tests.conftest import CHURCHTOOLS_BASE_URL

if typing.TYPE_CHECKING:
    import responses

    from churchsong.churchtools import ChurchToolsAPI


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
    return check.func(song, arrangements)


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


def test_every_check_returns_one_result_per_arrangement() -> None:
    # The invariant verify_songs() relies on when zipping the check results:
    # a check that returns more or fewer results breaks the whole run.
    song = make_song()
    for name, check in SongChecks.available_checks().items():
        assert check.func(song, []) == [], name
        assert len(check.func(song, [make_arrangement()])) == 1, name


def test_registry_rejects_duplicate_registration() -> None:
    with pytest.raises(RuntimeError, match='already registered'):
        SongChecks.register('CCLI')(lambda _song, _arrangements: [])


def test_declared_sng_content_need_matches_what_the_checks_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Whether a check reads the .sng file content is declared at registration, and a
    # wrong declaration is silent: verify_songs() skips the download when no active
    # check asks for the content, so an undeclared read sees an empty list and
    # produces a wrong result instead of an error. The declaration is therefore not
    # trusted but watched - which, unlike inspecting the check source, also catches
    # content reached through a helper, an alias or a comprehension variable.
    # Two scenarios, because some checks only consult the content for some songs:
    # check_languages looks at it for an EN/DE tagged song only.
    scenarios = [
        (
            'untagged song',
            make_song(),
            [
                make_arrangement(
                    source={'name': 'Feiert Jesus 5', 'shorty': 'FJ5'},
                    source_reference='123',
                    files=[{'name': 'song.sng', 'fileUrl': 'https://ct.test/f/1'}],
                    sng_lines=['#LangCount=2', '#Title=Amazing Grace'],
                )
            ],
        ),
        (
            'EN/DE tagged song',
            make_song(tags=['EN/DE']),
            [make_arrangement(sng_lines=['#Title=Amazing Grace'])],
        ),
    ]

    # Patch after building the arrangements, as the recording property has no setter.
    reads: list[str] = []
    original_fget = Arrangement.sng_file_content.fget
    assert original_fget is not None

    def recording_fget(arrangement: Arrangement) -> list[str]:
        reads.append(arrangement.name)
        return original_fget(arrangement)

    monkeypatch.setattr(Arrangement, 'sng_file_content', property(recording_fget))

    for name, check in SongChecks.available_checks().items():
        read_content = False
        for _label, song, arrangements in scenarios:
            reads.clear()
            check.func(song, arrangements)
            read_content = read_content or bool(reads)
        assert read_content == check.needs_sng_file_contents, (
            f'check {name} is registered with needs_sng_content='
            f'{check.needs_sng_file_contents}, but it '
            f'{"reads" if read_content else "never reads"} sng_file_content'
        )


def test_validate_checks_accepts_known_and_rejects_unknown() -> None:
    assert ChurchToolsSongVerification.validate_checks('CCLI,Tags') == 'CCLI,Tags'
    with pytest.raises(typer.BadParameter, match='not a valid check'):
        ChurchToolsSongVerification.validate_checks('NoSuchCheck')


def make_arrangement_json(
    *,
    arrangement_id: int = 1,
    name: str = 'Default',
    is_default: bool = True,
    duration: int | None = 180,
    files: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        'id': arrangement_id,
        'name': name,
        'isDefault': is_default,
        'source': None,
        'sourceReference': None,
        'key': 'G',
        'beat': '4/4',
        'tempo': 72,
        'duration': duration,
        'files': files or [],
    }


def make_song_json(
    song_id: int,
    name: str,
    *,
    ccli: str | None = '22025',
    tags: list[str] | None = None,
    arrangements: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        'id': song_id,
        'name': name,
        'author': 'John Newton',
        'ccli': ccli,
        'tags': [{'id': i, 'name': tag} for i, tag in enumerate(tags or [])],
        'arrangements': (
            [make_arrangement_json()] if arrangements is None else arrangements
        ),
    }


def register_all_songs(
    mocked_responses: responses.RequestsMock, songs: list[dict[str, object]]
) -> None:
    """Register the single result page of GET /api/songs."""
    meta = {
        'count': len(songs),
        'pagination': {
            'total': len(songs),
            'limit': len(songs),
            'current': 1,
            'lastPage': 1,
        },
    }
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/songs',
        json={'data': songs, 'meta': meta},
        match=[
            matchers.query_param_matcher(
                {'page': '1', 'include': 'tags', 'limit': str(MAX_SONGS_PAGE_SIZE)}
            )
        ],
    )


SNG_FILE = {'name': 'song.sng', 'fileUrl': f'{CHURCHTOOLS_BASE_URL}/files/1/song.sng'}


def test_verify_songs_lists_only_songs_with_findings(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    register_all_songs(
        mocked_responses,
        [
            make_song_json(42, 'Amazing Grace'),
            make_song_json(43, 'Be Thou My Vision', ccli=None),
        ],
    )
    ChurchToolsSongVerification(churchtools_api).verify_songs(
        date=None,
        include_tags=[],
        exclude_tags=[],
        execute_checks=['CCLI'],
        all_arrangements=False,
    )
    out = capsys.readouterr().out
    assert '#43' in out
    assert 'Be Thou My Vision' in out
    assert 'miss' in out
    assert 'Amazing Grace' not in out  # the complete song stays out of the table


def test_verify_songs_reports_a_song_without_any_arrangement(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    register_all_songs(
        mocked_responses, [make_song_json(42, 'Amazing Grace', arrangements=[])]
    )
    ChurchToolsSongVerification(churchtools_api).verify_songs(
        date=None,
        include_tags=[],
        exclude_tags=[],
        execute_checks=['CCLI'],
        all_arrangements=False,
    )
    out = capsys.readouterr().out
    assert 'Amazing Grace' in out
    assert 'miss' in out


def test_verify_songs_reports_a_song_without_a_default_arrangement(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    register_all_songs(
        mocked_responses,
        [
            make_song_json(
                42,
                'Amazing Grace',
                arrangements=[make_arrangement_json(name='Acoustic', is_default=False)],
            )
        ],
    )
    ChurchToolsSongVerification(churchtools_api).verify_songs(
        date=None,
        include_tags=[],
        exclude_tags=[],
        execute_checks=['CCLI'],
        all_arrangements=False,
    )
    out = capsys.readouterr().out
    assert 'Amazing Grace' in out
    assert 'miss' in out


def test_verify_songs_checks_a_non_default_arrangement_on_demand(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The very same song is complete once every arrangement is considered.
    register_all_songs(
        mocked_responses,
        [
            make_song_json(
                42,
                'Amazing Grace',
                arrangements=[make_arrangement_json(name='Acoustic', is_default=False)],
            )
        ],
    )
    ChurchToolsSongVerification(churchtools_api).verify_songs(
        date=None,
        include_tags=[],
        exclude_tags=[],
        execute_checks=['CCLI'],
        all_arrangements=True,
    )
    assert 'No problems found.' in capsys.readouterr().out


def test_verify_songs_reports_nothing_to_complain_about(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    register_all_songs(mocked_responses, [make_song_json(42, 'Amazing Grace')])
    ChurchToolsSongVerification(churchtools_api).verify_songs(
        date=None,
        include_tags=[],
        exclude_tags=[],
        execute_checks=['CCLI'],
        all_arrangements=False,
    )
    assert 'No problems found.' in capsys.readouterr().out


def test_verify_songs_distinguishes_no_findings_from_no_songs(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Claiming there are no problems with songs that were never examined would be a
    # false all-clear from the command whose job is finding problems.
    register_all_songs(mocked_responses, [])
    ChurchToolsSongVerification(churchtools_api).verify_songs(
        date=None,
        include_tags=[],
        exclude_tags=[],
        execute_checks=['CCLI'],
        all_arrangements=False,
    )
    assert 'No songs to verify.' in capsys.readouterr().out


def test_verify_songs_downloads_sng_files_for_checks_that_need_them(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    register_all_songs(
        mocked_responses,
        [
            make_song_json(
                42,
                'Amazing Grace',
                arrangements=[make_arrangement_json(files=[SNG_FILE])],
            )
        ],
    )
    mocked_responses.get(SNG_FILE['fileUrl'], body='#Title=Amazing Grace')
    ChurchToolsSongVerification(churchtools_api).verify_songs(
        date=None,
        include_tags=[],
        exclude_tags=[],
        execute_checks=['BGImg'],
        all_arrangements=False,
    )
    # The .sng file was downloaded (an unfired registration fails the test) and
    # its missing background image is reported.
    assert 'miss' in capsys.readouterr().out


def test_verify_songs_strips_the_byte_order_mark_of_sng_files(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    register_all_songs(
        mocked_responses,
        [
            make_song_json(
                42,
                'Amazing Grace',
                arrangements=[make_arrangement_json(files=[SNG_FILE])],
            )
        ],
    )
    # SongBeamer writes .sng files with a BOM; without stripping it, the very
    # first line would not be recognized and would be reported as missing.
    mocked_responses.get(
        SNG_FILE['fileUrl'],
        body='\ufeff#BackgroundImage=bg.jpg\n#Title=Amazing Grace',
        content_type='text/plain; charset=utf-8',
    )
    ChurchToolsSongVerification(churchtools_api).verify_songs(
        date=None,
        include_tags=[],
        exclude_tags=[],
        execute_checks=['BGImg'],
        all_arrangements=False,
    )
    assert 'No problems found.' in capsys.readouterr().out


def test_verify_songs_skips_sng_download_for_checks_that_do_not_need_it(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
) -> None:
    # No download endpoint is registered: downloading the .sng file for a check
    # that never looks at its content would fail the test.
    register_all_songs(
        mocked_responses,
        [
            make_song_json(
                42,
                'Amazing Grace',
                arrangements=[make_arrangement_json(files=[SNG_FILE])],
            )
        ],
    )
    ChurchToolsSongVerification(churchtools_api).verify_songs(
        date=None,
        include_tags=[],
        exclude_tags=[],
        execute_checks=['CCLI'],
        all_arrangements=False,
    )


def test_verify_songs_warns_about_undownloadable_sng_files(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    register_all_songs(
        mocked_responses,
        [
            make_song_json(
                42,
                'Amazing Grace',
                arrangements=[make_arrangement_json(files=[SNG_FILE])],
            )
        ],
    )
    mocked_responses.get(SNG_FILE['fileUrl'], status=404)
    with caplog.at_level(logging.WARNING):
        ChurchToolsSongVerification(churchtools_api).verify_songs(
            date=None,
            include_tags=[],
            exclude_tags=[],
            execute_checks=['BGImg'],
            all_arrangements=False,
        )
    assert 'Failed to download arrangement' in caplog.text
    # A failed download must not turn into a false positive finding.
    assert 'No problems found.' in capsys.readouterr().out


def test_verify_songs_applies_include_and_exclude_tags(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    register_all_songs(
        mocked_responses,
        [
            make_song_json(42, 'Amazing Grace', ccli=None, tags=['German']),
            make_song_json(43, 'Be Thou My Vision', ccli=None, tags=['English']),
            make_song_json(44, 'Rock Of Ages', ccli=None, tags=['German', 'Archive']),
        ],
    )
    ChurchToolsSongVerification(churchtools_api).verify_songs(
        date=None,
        include_tags=['German'],
        exclude_tags=['Archive'],
        execute_checks=['CCLI'],
        all_arrangements=False,
    )
    out = capsys.readouterr().out
    assert 'Amazing Grace' in out
    assert 'Be Thou My Vision' not in out  # not included
    assert 'Rock Of Ages' not in out  # included, but also excluded


def test_verify_songs_reports_duplicate_ccli_numbers(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    register_all_songs(
        mocked_responses,
        [
            make_song_json(42, 'Amazing Grace'),
            make_song_json(43, 'Amazing Grace (Reprise)'),
            make_song_json(44, 'Be Thou My Vision', ccli='12345'),
        ],
    )
    ChurchToolsSongVerification(churchtools_api).verify_songs(
        date=None,
        include_tags=[],
        exclude_tags=[],
        execute_checks=['CCLI'],
        all_arrangements=False,
    )
    out = capsys.readouterr().out
    assert 'Duplicate songs:' in out
    assert 'CCLI 22025: #42, #43' in out
    assert '12345' not in out  # only used once, so not a duplicate


def test_verify_songs_checks_only_the_default_arrangement_by_default(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    register_all_songs(
        mocked_responses,
        [
            make_song_json(
                42,
                'Amazing Grace',
                arrangements=[
                    make_arrangement_json(),
                    make_arrangement_json(
                        arrangement_id=2,
                        name='Acoustic',
                        is_default=False,
                        duration=None,
                    ),
                ],
            )
        ],
    )
    ChurchToolsSongVerification(churchtools_api).verify_songs(
        date=None,
        include_tags=[],
        exclude_tags=[],
        execute_checks=['Dur.'],
        all_arrangements=False,
    )
    out = capsys.readouterr().out
    assert 'No problems found.' in out
    assert 'Acoustic' not in out


def test_verify_songs_checks_every_arrangement_on_demand(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    register_all_songs(
        mocked_responses,
        [
            make_song_json(
                42,
                'Amazing Grace',
                arrangements=[
                    make_arrangement_json(),
                    make_arrangement_json(
                        arrangement_id=2,
                        name='Acoustic',
                        is_default=False,
                        duration=None,
                    ),
                ],
            )
        ],
    )
    ChurchToolsSongVerification(churchtools_api).verify_songs(
        date=None,
        include_tags=[],
        exclude_tags=[],
        execute_checks=['Dur.'],
        all_arrangements=True,
    )
    out = capsys.readouterr().out
    assert 'Acoustic' in out
    assert 'miss' in out


def test_verify_songs_of_an_event_fetches_tags_separately(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The agenda songs endpoint does not support including tags, so they have
    # to be fetched per song - which the tag filtering then relies on.
    song = make_song_json(42, 'Amazing Grace', ccli=None)
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/events',
        json={
            'data': [
                {
                    'id': 7,
                    'name': 'Sunday Service',
                    'startDate': '2026-08-23T10:00:00Z',
                    'endDate': '2026-08-23T12:00:00Z',
                }
            ]
        },
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/events/7/agenda',
        json={'data': {'id': 1, 'items': []}},
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/events/7/agenda/songs',
        json={'data': [song], 'meta': {'count': 1}},
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/songs',
        json={
            'data': [make_song_json(42, 'Amazing Grace', tags=['German'])],
            'meta': {'count': 1},
        },
        match=[matchers.query_param_matcher({'ids[]': '42', 'include': 'tags'})],
    )
    ChurchToolsSongVerification(churchtools_api).verify_songs(
        date=datetime.datetime(2026, 8, 20, tzinfo=datetime.UTC),
        include_tags=['German'],
        exclude_tags=[],
        execute_checks=['CCLI'],
        all_arrangements=False,
    )
    assert 'Amazing Grace' in capsys.readouterr().out


def test_verify_songs_rejects_a_selection_without_any_valid_check(
    churchtools_api: ChurchToolsAPI,
) -> None:
    with pytest.raises(typer.BadParameter, match='No valid check'):
        ChurchToolsSongVerification(churchtools_api).verify_songs(
            date=None,
            include_tags=[],
            exclude_tags=[],
            execute_checks=['NoSuchCheck'],
            all_arrangements=False,
        )
