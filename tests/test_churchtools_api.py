# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import datetime
import logging
import typing

import pytest
import requests
import responses
from responses import matchers

from churchsong.churchtools import (
    MAX_SONGS_PAGE_SIZE,
    ChurchToolsAPI,
    EventFile,
    EventFull,
    EventShort,
)
from churchsong.utils import CliError
from tests.conftest import (
    CHURCHTOOLS_BASE_URL,
    FakeConfiguration,
    make_config,
    make_global_permissions,
)

if typing.TYPE_CHECKING:
    from churchsong.configuration import Configuration


def make_song_json(
    song_id: int, name: str, *, tags: list[dict[str, object]] | None = None
) -> dict[str, object]:
    return {
        'id': song_id,
        'name': name,
        'author': 'John Newton',
        'ccli': '22025',
        'arrangements': [],
        'tags': tags or [],
    }


def make_event_json(
    event_id: int, name: str, start: str, end: str
) -> dict[str, object]:
    return {'id': event_id, 'name': name, 'startDate': start, 'endDate': end}


def test_init_asserts_basic_permissions(churchtools_api: ChurchToolsAPI) -> None:
    assert churchtools_api.has_permissions(['churchservice:view agenda'])
    assert not churchtools_api.has_permissions(['churchservice:no such permission'])


def test_init_rejects_missing_basic_permissions(
    config: Configuration, mocked_responses: responses.RequestsMock
) -> None:
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/permissions/global',
        json=make_global_permissions(churchservice_view=False),
    )
    with pytest.raises(CliError, match='Missing required permissions'):
        ChurchToolsAPI(config)


def test_init_hints_at_wrong_token_on_401(
    config: Configuration, mocked_responses: responses.RequestsMock
) -> None:
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/api/permissions/global', status=401)
    with pytest.raises(CliError, match='API token'):
        ChurchToolsAPI(config)


def test_init_reports_a_non_json_answer_as_a_url_problem(
    config: Configuration, mocked_responses: responses.RequestsMock
) -> None:
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/permissions/global',
        body='<html><body>Please log in</body></html>',
        content_type='text/html',
    )
    with pytest.raises(CliError, match='Did you configure the URL') as excinfo:
        ChurchToolsAPI(config)
    assert CHURCHTOOLS_BASE_URL in str(excinfo.value)


def test_init_reports_an_off_shape_permissions_answer(
    config: Configuration, mocked_responses: responses.RequestsMock
) -> None:
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/permissions/global',
        json={'message': 'maintenance'},
    )
    with pytest.raises(CliError, match='Did you configure the URL') as excinfo:
        ChurchToolsAPI(config)
    assert CHURCHTOOLS_BASE_URL in str(excinfo.value)


# The three shapes an answer takes once it stops being the API we model: a renamed
# field, a JSON body that is not an object at all, and something that is not JSON.
OFF_SHAPE_ANSWERS = [
    pytest.param('{"items": []}', id='renamed-field'),
    pytest.param('[1, 2, 3]', id='json-array'),
    pytest.param('<html><body>Please log in</body></html>', id='not-json'),
]


@pytest.mark.parametrize('answer', OFF_SHAPE_ANSWERS)
def test_get_events_reports_an_off_shape_answer(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    answer: str,
) -> None:
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/api/events', body=answer)
    with pytest.raises(CliError, match='/api/events') as excinfo:
        list(churchtools_api.get_events(datetime.date(2026, 8, 23)))
    # `_fetch_permissions()` has proven the base URL good by now, so the message must
    # not send the user back to the configuration - the cause is on the server.
    assert 'Did you configure' not in str(excinfo.value)


def test_get_full_event_reports_an_off_shape_answer(
    churchtools_api: ChurchToolsAPI, mocked_responses: responses.RequestsMock
) -> None:
    event = EventShort.model_validate(
        make_event_json(42, 'Service', '2026-08-16T09:00:00Z', '2026-08-16T11:00:00Z')
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/events/42', json={'data': {'id': 42}}
    )
    with pytest.raises(CliError, match='/api/events/42') as excinfo:
        churchtools_api.get_full_event(event)
    assert 'Did you configure' not in str(excinfo.value)


def test_get_event_agenda_reports_an_off_shape_answer(
    churchtools_api: ChurchToolsAPI, mocked_responses: responses.RequestsMock
) -> None:
    event = EventShort.model_validate(
        make_event_json(42, 'Service', '2026-08-16T09:00:00Z', '2026-08-16T11:00:00Z')
    )
    # The shape of every ChurchTools rename this project has seen so far.
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/events/42/agenda',
        json={'data': {'id': 1, 'agendaItems': []}},
    )
    with pytest.raises(CliError, match='/api/events/42/agenda') as excinfo:
        churchtools_api.get_event_agenda(event)
    assert 'Did you configure' not in str(excinfo.value)


@pytest.mark.usefixtures('churchtools_api')
def test_requests_carry_authorization_header(
    mocked_responses: responses.RequestsMock,
) -> None:
    request = mocked_responses.calls[0].request
    assert request.headers['Authorization'] == 'Login churchtools-test-token'
    assert request.headers['Accept'] == 'application/json'


def test_trailing_slash_in_base_url_does_not_double_the_path_separator(
    mocked_responses: responses.RequestsMock,
) -> None:
    config = FakeConfiguration(
        ChurchTools={
            'base_url': f'{CHURCHTOOLS_BASE_URL}/',
            'login_token': 'churchtools-test-token',
        },
        SongBeamer={'output_dir': 'output'},
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/permissions/global',
        json=make_global_permissions(),
    )
    ChurchToolsAPI(config)
    url = mocked_responses.calls[0].request.url
    assert url == f'{CHURCHTOOLS_BASE_URL}/api/permissions/global'


def test_get_songs_iterates_over_all_pages(
    churchtools_api: ChurchToolsAPI, mocked_responses: responses.RequestsMock
) -> None:
    tags: list[dict[str, object]] = [{'id': 1, 'name': 'German'}]
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/songs',
        json={
            'data': [
                make_song_json(1, 'Amazing Grace', tags=tags),
                make_song_json(2, 'How Great Thou Art', tags=tags),
            ],
            'meta': {
                'count': 2,
                'pagination': {'total': 3, 'limit': 2, 'current': 1, 'lastPage': 2},
            },
        },
        match=[
            matchers.query_param_matcher(
                {'page': '1', 'include': 'tags', 'limit': str(MAX_SONGS_PAGE_SIZE)}
            )
        ],
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/songs',
        json={
            'data': [make_song_json(3, 'Be Thou My Vision', tags=tags)],
            'meta': {
                'count': 1,
                'pagination': {'total': 3, 'limit': 2, 'current': 2, 'lastPage': 2},
            },
        },
        match=[
            matchers.query_param_matcher(
                {'page': '2', 'include': 'tags', 'limit': str(MAX_SONGS_PAGE_SIZE)}
            )
        ],
    )

    total, songs = churchtools_api.get_songs()
    names = [song.name for song in songs]
    assert total == 3
    assert names == ['Amazing Grace', 'How Great Thou Art', 'Be Thou My Vision']


def test_get_songs_survives_a_rate_limited_page(
    churchtools_api: ChurchToolsAPI, mocked_responses: responses.RequestsMock
) -> None:
    # Paging through the whole song database is what runs into the rate limit of
    # ChurchTools, and a 429 in the middle of it used to abort `songs verify`.
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/songs',
        json={
            'data': [make_song_json(1, 'Amazing Grace')],
            'meta': {
                'count': 1,
                'pagination': {'total': 2, 'limit': 1, 'current': 1, 'lastPage': 2},
            },
        },
        match=[
            matchers.query_param_matcher(
                {'page': '1', 'include': 'tags', 'limit': str(MAX_SONGS_PAGE_SIZE)}
            )
        ],
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/songs',
        status=429,
        match=[
            matchers.query_param_matcher(
                {'page': '2', 'include': 'tags', 'limit': str(MAX_SONGS_PAGE_SIZE)}
            )
        ],
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/songs',
        json={
            'data': [make_song_json(2, 'Be Thou My Vision')],
            'meta': {
                'count': 1,
                'pagination': {'total': 2, 'limit': 1, 'current': 2, 'lastPage': 2},
            },
        },
        match=[
            matchers.query_param_matcher(
                {'page': '2', 'include': 'tags', 'limit': str(MAX_SONGS_PAGE_SIZE)}
            )
        ],
    )

    _total, songs = churchtools_api.get_songs()
    assert [song.name for song in songs] == ['Amazing Grace', 'Be Thou My Vision']


def test_get_next_event_skips_already_finished_events(
    churchtools_api: ChurchToolsAPI, mocked_responses: responses.RequestsMock
) -> None:
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/events',
        json={
            'data': [
                make_event_json(
                    1, 'Past', '2026-08-16T10:00:00Z', '2026-08-16T12:00:00Z'
                ),
                make_event_json(
                    2, 'Next', '2026-08-23T10:00:00Z', '2026-08-23T12:00:00Z'
                ),
            ]
        },
    )
    # Now query for exactly the `end_date` of the 'Past' event:
    from_date = datetime.datetime(2026, 8, 16, 12, 0, 0, tzinfo=datetime.UTC)
    event = churchtools_api.get_next_event(from_date)
    assert event.id == 2
    assert event.name == 'Next'


def test_get_next_event_without_any_event_raises_cli_error(
    churchtools_api: ChurchToolsAPI, mocked_responses: responses.RequestsMock
) -> None:
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/api/events', json={'data': []})
    from_date = datetime.datetime(2026, 8, 20, tzinfo=datetime.UTC)
    with pytest.raises(CliError, match='No events present'):
        churchtools_api.get_next_event(from_date)


def test_get_next_event_requiring_agenda_raises_cli_error_on_404(
    churchtools_api: ChurchToolsAPI, mocked_responses: responses.RequestsMock
) -> None:
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/events',
        json={
            'data': [
                make_event_json(
                    2, 'Next', '2026-08-23T10:00:00Z', '2026-08-23T12:00:00Z'
                )
            ]
        },
    )
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/api/events/2/agenda', status=404)
    from_date = datetime.datetime(2026, 8, 20, tzinfo=datetime.UTC)
    with pytest.raises(CliError, match='No event agenda present'):
        churchtools_api.get_next_event(from_date, agenda_required=True)


def test_download_url_keeps_auth_header_for_own_host(
    churchtools_api: ChurchToolsAPI, mocked_responses: responses.RequestsMock
) -> None:
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/files/1/song.sng', body='sng data')
    churchtools_api.download_url(f'{CHURCHTOOLS_BASE_URL}/files/1/song.sng')
    request = mocked_responses.calls[-1].request
    assert request.headers['Authorization'] == 'Login churchtools-test-token'


def test_download_url_drops_auth_header_for_foreign_host(
    churchtools_api: ChurchToolsAPI, mocked_responses: responses.RequestsMock
) -> None:
    mocked_responses.get('https://elsewhere.test/file.bin', body='data')
    churchtools_api.download_url('https://elsewhere.test/file.bin')
    request = mocked_responses.calls[-1].request
    assert 'Authorization' not in request.headers


def make_event_full() -> EventFull:
    return EventFull.model_validate(
        {
            'id': 2,
            'name': 'Next',
            'startDate': '2026-08-23T10:00:00Z',
            'endDate': '2026-08-23T12:00:00Z',
            'eventFiles': [],
            'eventServices': [],
        }
    )


def test_upload_event_file_is_skipped_without_edit_permission(
    mocked_responses: responses.RequestsMock,
) -> None:
    # No POST endpoint is registered: if the missing permission did not
    # short-circuit the upload, the HTTP call would fail the test.
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/permissions/global',
        json=make_global_permissions(edit_events=False),
    )
    api = ChurchToolsAPI(make_config())
    api.upload_event_file(make_event_full(), 'songsheet.pdf', b'%PDF-1.7')


def test_upload_event_file_posts_multipart_file(
    churchtools_api: ChurchToolsAPI, mocked_responses: responses.RequestsMock
) -> None:
    mocked_responses.post(
        f'{CHURCHTOOLS_BASE_URL}/api/files/service/2', json={'data': []}
    )
    churchtools_api.upload_event_file(make_event_full(), 'songsheet.pdf', b'%PDF-1.7')
    body = mocked_responses.calls[-1].request.body
    assert body is not None
    assert b'songsheet.pdf' in typing.cast('bytes', body)


def make_person_json(nickname: str | None) -> dict[str, object]:
    return {'data': {'firstName': 'John', 'lastName': 'Newton', 'nickname': nickname}}


def make_appointment_json(
    title: str, start: str, *, is_internal: bool = False
) -> dict[str, object]:
    return {
        'appointment': {
            'base': {
                'title': title,
                'subtitle': None,
                'description': None,
                'image': None,
                'link': None,
                'isInternal': is_internal,
                'startDate': start,
                'endDate': start,
                'allDay': False,
                'repeatId': 0,
                'repeatFrequency': None,
                'address': None,
            }
        }
    }


def test_init_reports_an_unreachable_churchtools_instance(
    config: Configuration, mocked_responses: responses.RequestsMock
) -> None:
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/permissions/global',
        body=requests.exceptions.ConnectionError('no route to host'),
    )
    with pytest.raises(CliError, match='configure the URL'):
        ChurchToolsAPI(config)


def test_get_songs_reports_an_inaccessible_song_database(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # An empty result would be a false all-clear for `songs verify`, whose whole job
    # is to find problems in the songs it did not manage to look at here.
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/api/songs', status=500)
    with caplog.at_level(logging.ERROR), pytest.raises(CliError, match='Failed to get'):
        churchtools_api.get_songs()
    assert '500' in caplog.text


def test_get_songs_reports_a_failing_page_in_the_middle(
    churchtools_api: ChurchToolsAPI, mocked_responses: responses.RequestsMock
) -> None:
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/songs',
        json={
            'data': [make_song_json(1, 'Amazing Grace')],
            'meta': {
                'count': 1,
                'pagination': {'total': 2, 'limit': 1, 'current': 1, 'lastPage': 2},
            },
        },
        match=[
            matchers.query_param_matcher(
                {'page': '1', 'include': 'tags', 'limit': str(MAX_SONGS_PAGE_SIZE)}
            )
        ],
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/songs',
        status=500,
        match=[
            matchers.query_param_matcher(
                {'page': '2', 'include': 'tags', 'limit': str(MAX_SONGS_PAGE_SIZE)}
            )
        ],
    )
    _total, songs = churchtools_api.get_songs()
    with pytest.raises(CliError, match='Failed to get'):
        list(songs)


def test_get_songs_reports_a_missing_page_of_an_existing_agenda(
    churchtools_api: ChurchToolsAPI, mocked_responses: responses.RequestsMock
) -> None:
    # The first page proved the agenda exists, so a 404 on the second one is not an
    # event without an agenda but a failure that must not silently cut the songs short.
    event = EventShort.model_validate(
        make_event_json(42, 'Service', '2026-08-16T09:00:00Z', '2026-08-16T11:00:00Z')
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/events/42/agenda/songs',
        json={
            'data': [make_song_json(1, 'Amazing Grace')],
            'meta': {
                'count': 1,
                'pagination': {'total': 2, 'limit': 1, 'current': 1, 'lastPage': 2},
            },
        },
        match=[matchers.query_param_matcher({'page': '1'})],
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/events/42/agenda/songs',
        status=404,
        match=[matchers.query_param_matcher({'page': '2'})],
    )
    total, songs = churchtools_api.get_songs(event, require_tags=False)
    assert total == 2
    with pytest.raises(CliError, match='Failed to get'):
        list(songs)


def test_get_songs_treats_an_event_without_agenda_as_songless(
    churchtools_api: ChurchToolsAPI, mocked_responses: responses.RequestsMock
) -> None:
    # Walking a year range of events for the song statistics hits events that never
    # had an agenda, which is not a failure worth aborting the whole run for.
    event = EventShort.model_validate(
        make_event_json(42, 'Service', '2026-08-16T09:00:00Z', '2026-08-16T11:00:00Z')
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/events/42/agenda/songs', status=404
    )
    total, songs = churchtools_api.get_songs(event)
    assert total == 0
    assert list(songs) == []


def test_get_person_returns_none_without_the_required_permission(
    mocked_responses: responses.RequestsMock, caplog: pytest.LogCaptureFixture
) -> None:
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/permissions/global',
        json=make_global_permissions(view_alldata=False),
    )
    api = ChurchToolsAPI(make_config())
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/api/persons/1', status=403)
    with caplog.at_level(logging.WARNING):
        assert api.get_person(1) is None
    assert 'nickname lookup' in caplog.text


@pytest.mark.parametrize(
    ('person_response', 'reason'),
    [
        # `churchdb:view alldata` is a list of ids, so a token holding it for some
        # people still gets a 403 for the others.
        pytest.param({'status': 403}, '403 Client Error', id='forbidden'),
        # The person was deleted or merged after the event had been planned.
        pytest.param({'status': 404}, '404 Client Error', id='not-found'),
        pytest.param(
            {'json': {'data': {'firstName': 'John', 'nickname': None}}},
            'Field required',
            id='unparsable',
        ),
    ],
)
def test_get_person_returns_none_for_a_person_it_cannot_read(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    caplog: pytest.LogCaptureFixture,
    person_response: dict[str, typing.Any],
    reason: str,
) -> None:
    # The permission is there, but holding it does not mean seeing every person:
    # the caller falls back to the name of the event service instead of losing
    # the whole service team information.
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/api/persons/1', **person_response)
    with caplog.at_level(logging.WARNING):
        assert churchtools_api.get_person(1) is None
    assert 'person #1' in caplog.text
    assert reason in caplog.text


@pytest.mark.parametrize(
    'failing_person_request',
    [
        pytest.param({'status': 500}, id='server-error'),
        pytest.param(
            {'body': requests.exceptions.ConnectionError('connection reset')},
            id='dropped-connection',
        ),
    ],
)
def test_get_person_reraises_unexpected_errors(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    failing_person_request: dict[str, typing.Any],
) -> None:
    # A broken server is not "this person is not there" and still has to reach
    # the guard in the caller.
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/persons/1', **failing_person_request
    )
    with pytest.raises(requests.exceptions.RequestException):
        churchtools_api.get_person(1)


def test_get_person_warns_about_a_missing_nickname(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/persons/1', json=make_person_json(None)
    )
    with caplog.at_level(logging.WARNING):
        person = churchtools_api.get_person(1)
    assert person is not None
    assert person.firstname == 'John'
    assert 'security level person' in caplog.text


def test_get_appointments_asks_all_calendars_and_filters_the_event_itself(
    churchtools_api: ChurchToolsAPI, mocked_responses: responses.RequestsMock
) -> None:
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/calendars',
        json={'data': [{'id': 1, 'name': 'Services'}, {'id': 2, 'name': 'Youth'}]},
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/calendars/appointments',
        json={
            'data': [
                # The event the agenda is created for is not an appointment.
                make_appointment_json('Next', '2026-08-23T10:00:00Z'),
                make_appointment_json(
                    'Staff Meeting', '2026-08-30T10:00:00Z', is_internal=True
                ),
                make_appointment_json('Church Picnic', '2026-09-06T10:00:00Z'),
            ]
        },
    )
    event = EventShort.model_validate(
        make_event_json(2, 'Next', '2026-08-23T10:00:00Z', '2026-08-23T12:00:00Z')
    )
    appointments = list(churchtools_api.get_appointments(event))
    assert [appointment.title for appointment in appointments] == ['Church Picnic']
    url = mocked_responses.calls[-1].request.url
    assert url is not None
    assert 'calendar_ids%5B%5D=1' in url
    assert 'calendar_ids%5B%5D=2' in url
    assert 'from=2026-08-23' in url
    assert 'to=2026-11-22' in url  # the configured 13 weeks look ahead


def test_get_next_event_reraises_unexpected_agenda_errors(
    churchtools_api: ChurchToolsAPI, mocked_responses: responses.RequestsMock
) -> None:
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/events',
        json={
            'data': [
                make_event_json(
                    2, 'Next', '2026-08-23T10:00:00Z', '2026-08-23T12:00:00Z'
                )
            ]
        },
    )
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/api/events/2/agenda', status=500)
    from_date = datetime.datetime(2026, 8, 20, tzinfo=datetime.UTC)
    with pytest.raises(requests.exceptions.HTTPError):
        churchtools_api.get_next_event(from_date, agenda_required=True)


def test_delete_event_file_is_skipped_without_edit_permission(
    mocked_responses: responses.RequestsMock, caplog: pytest.LogCaptureFixture
) -> None:
    # No DELETE endpoint is registered: without the short-circuit the HTTP
    # call would fail the test.
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/permissions/global',
        json=make_global_permissions(edit_events=False),
    )
    api = ChurchToolsAPI(make_config())
    event_file = EventFile.model_validate(
        {
            'title': 'Song Sheets Chords.pdf',
            'domainType': 'file',
            'domainIdentifier': 900,
            'frontendUrl': f'{CHURCHTOOLS_BASE_URL}/files/900',
        }
    )
    with caplog.at_level(logging.WARNING):
        api.delete_event_file(make_event_full(), event_file)
    assert 'song sheet deletion' in caplog.text


def test_does_not_send_back_session_cookie(
    config: Configuration, mocked_responses: responses.RequestsMock
) -> None:
    """ChurchTools authenticates by session as soon as it sees its own cookie again
    and then rejects writes without a CSRF token, so the login token has to stay the
    only means of authentication."""
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/permissions/global',
        json=make_global_permissions(),
        headers={'Set-Cookie': 'ChurchToolsV2_ct_test=secret; path=/'},
    )
    mocked_responses.post(
        f'{CHURCHTOOLS_BASE_URL}/api/files/service/2', json={'data': []}
    )

    api = ChurchToolsAPI(config)
    api.upload_event_file(make_event_full(), 'songsheet.pdf', b'%PDF-1.7')

    upload = mocked_responses.calls[-1].request
    assert 'Cookie' not in upload.headers
    assert upload.headers['Authorization'] == 'Login churchtools-test-token'
