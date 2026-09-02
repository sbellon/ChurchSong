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


@pytest.mark.usefixtures('churchtools_api')
def test_requests_carry_authorization_header(
    mocked_responses: responses.RequestsMock,
) -> None:
    request = mocked_responses.calls[0].request
    assert request.headers['Authorization'] == 'Login churchtools-test-token'
    assert request.headers['Accept'] == 'application/json'


def test_get_songs_iterates_over_all_pages(
    churchtools_api: ChurchToolsAPI, mocked_responses: responses.RequestsMock
) -> None:
    tags: list[dict[str, object]] = [{'id': 1, 'name': 'German'}]
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/songs',
        json={
            'data': [make_song_json(1, 'Amazing Grace', tags=tags)],
            'meta': {
                'count': 1,
                'pagination': {'total': 3, 'limit': 1, 'current': 1, 'lastPage': 3},
            },
        },
        match=[matchers.query_param_matcher({'page': '1', 'limit': '1'})],
    )
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
        match=[matchers.query_param_matcher({'page': '1', 'limit': '1'})],
    )
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


def test_get_songs_returns_nothing_when_the_song_database_is_inaccessible(
    churchtools_api: ChurchToolsAPI, mocked_responses: responses.RequestsMock
) -> None:
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/api/songs', status=403)
    total, songs = churchtools_api.get_songs()
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


def test_get_person_reraises_unexpected_errors(
    churchtools_api: ChurchToolsAPI, mocked_responses: responses.RequestsMock
) -> None:
    # The permission is there, so a 403 is not the missing permission and has
    # to be reported instead of being swallowed.
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/api/persons/1', status=403)
    with pytest.raises(requests.exceptions.HTTPError):
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
