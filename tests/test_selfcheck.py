# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import logging
import typing
import urllib.parse
import warnings

import pytest
import typer.testing

from churchsong import __main__ as cli
from churchsong.churchtools import ChurchToolsAPI
from churchsong.configuration import Configuration
from churchsong.immich import ImmichAPI
from churchsong.selfcheck import Result, SelfCheck, Status
from churchsong.utils.http import Feature
from churchsong.utils.progress import Progress
from tests.conftest import (
    CHURCHTOOLS_BASE_URL,
    IMMICH_BASE_URL,
    OPENAPI_ENDPOINTS,
    endpoint_template,
    make_config,
    make_global_permissions,
    mock_churchtools_server,
    mock_immich_server,
)

if typing.TYPE_CHECKING:
    import responses

# Far enough ahead to stay the next event for as long as this test is around.
EVENT = {
    'id': 42,
    'name': 'Sunday Service',
    'startDate': '2099-08-23T10:00:00Z',
    'endDate': '2099-08-23T12:00:00Z',
    # As ChurchTools sends it, shortened: a domain object with a string identifier.
    'calendar': {
        'domainIdentifier': '1',
        'title': 'Services',
        'domainType': 'calendar',
    },
}
SONG = {
    'id': 7,
    'name': 'Amazing Grace',
    'author': 'John Newton',
    'ccli': '22025',
    'arrangements': [],
    'tags': [{'id': 1, 'name': 'Hymn'}],
}
APPOINTMENT = {
    'appointment': {
        'base': {
            'title': 'Church Picnic',
            'subtitle': None,
            'description': None,
            'image': None,
            'link': None,
            'isInternal': False,
            'startDate': '2099-09-06T10:00:00Z',
            'endDate': '2099-09-06T10:00:00Z',
            'allDay': False,
            'repeatId': 0,
            'repeatFrequency': None,
            'address': None,
        }
    }
}
TEMPLATES = {'PowerPoint': {'Appointments': {'template_pptx': 'appointments.pptx'}}}
IMMICH = {'upload_tags': ['Upload', 'New'], 'backgrounds_album': 'Backgrounds'}
IMMICH_PERMISSIONS = [
    'asset.upload',
    'tag.read',
    'tag.asset',
    'tag.create',
    'album.read',
    'asset.read',
    'asset.download',
]


def mock_churchtools(
    mocked_responses: responses.RequestsMock,
    permissions: dict[str, typing.Any] | None = None,
    *,
    person_answer: dict[str, typing.Any] | None = None,
    appointments: bool = True,
) -> None:
    """Register every read of an agenda run, for an event with one song and person."""
    mock_churchtools_server(mocked_responses, permissions)
    api = f'{CHURCHTOOLS_BASE_URL}/api'
    mocked_responses.get(f'{api}/events', json={'data': [EVENT]})
    mocked_responses.get(
        f'{api}/events/42',
        json={
            'data': EVENT
            | {
                'eventFiles': [],
                'eventServices': [
                    {'person': {'domainIdentifier': '5'}, 'name': None, 'serviceId': 1}
                ],
            }
        },
    )
    mocked_responses.get(
        f'{api}/events/42/agenda', json={'data': {'id': 1, 'items': []}}
    )
    mocked_responses.get(
        f'{api}/events/42/agenda/songs', json={'data': [SONG], 'meta': {'count': 1}}
    )
    mocked_responses.get(
        f'{api}/services', json={'data': [{'id': 1, 'name': 'Preaching'}]}
    )
    mocked_responses.get(
        f'{api}/persons/5',
        **person_answer
        or {
            'json': {'data': {'firstName': 'Jane', 'lastName': 'Doe', 'nickname': 'JD'}}
        },
    )
    mocked_responses.get(
        f'{api}/songs',
        json={
            'data': [SONG],
            'meta': {
                'count': 1,
                'pagination': {'total': 1, 'limit': 200, 'current': 1, 'lastPage': 1},
            },
        },
    )
    mocked_responses.get(f'{api}/songs/7', json={'data': SONG})
    if appointments:
        mocked_responses.get(
            f'{api}/calendars',
            json={'data': [{'id': 1, 'name': 'Services'}, {'id': 2, 'name': 'Youth'}]},
        )
        mocked_responses.get(
            f'{api}/calendars/appointments', json={'data': [APPOINTMENT]}
        )


def mock_immich(mocked_responses: responses.RequestsMock) -> None:
    """Register the reads of an Immich whose upload tag "New" does not exist yet.

    No POST /api/tags is registered: creating the tag would fail the test.
    """
    mock_immich_server(mocked_responses, IMMICH_PERMISSIONS)
    mocked_responses.get(
        f'{IMMICH_BASE_URL}/api/tags', json=[{'id': 't1', 'name': 'Upload'}]
    )
    mocked_responses.get(
        f'{IMMICH_BASE_URL}/api/albums',
        json=[{'id': 'al1', 'albumName': 'Backgrounds'}],
    )
    mocked_responses.post(f'{IMMICH_BASE_URL}/api/search/random', json=[{'id': 'a1'}])


def run_check(config: Configuration) -> dict[tuple[str, str], Result]:
    return {(r.service, r.name): r for r in SelfCheck(config).run()}


def features_of(api: type) -> set[str]:
    return {f.name for f in vars(api).values() if isinstance(f, Feature)}


def test_check_reads_everything_a_run_reads(
    mocked_responses: responses.RequestsMock,
) -> None:
    mock_churchtools(mocked_responses)
    mock_immich(mocked_responses)
    results = run_check(make_config(songbeamer=TEMPLATES, immich=IMMICH))

    assert {key: r.status for key, r in results.items()} == {
        ('ChurchTools', 'connection'): Status.OK,
        ('ChurchTools', 'next event'): Status.OK,
        ('ChurchTools', 'service team'): Status.OK,
        ('ChurchTools', 'song database'): Status.OK,
        ('ChurchTools', 'song sheets'): Status.OK,
        ('ChurchTools', 'nickname lookup'): Status.OK,
        ('ChurchTools', 'appointment slides'): Status.OK,
        ('Immich', 'connection'): Status.OK,
        ('Immich', 'media upload'): Status.OK,
        ('Immich', 'tag creation'): Status.OK,
        ('Immich', 'background image download'): Status.OK,
    }
    assert results['Immich', 'tag creation'].details == [
        'the next agenda run creates the tags New'
    ]
    assert results['ChurchTools', 'appointment slides'].details == [
        (
            '1 appointment from the calendars Services, Youth in the 13 weeks '
            'after the event'
        )
    ]
    # Every optional feature of the clients has its row.
    names = {name for _service, name in results}
    assert features_of(ChurchToolsAPI) | features_of(ImmichAPI) <= names
    # And every endpoint `dev-scripts/check_openapi.py` checks is asked.
    asked = {
        endpoint_template(urllib.parse.urlsplit(call.request.url or '').path)
        for call in mocked_responses.calls
        if (call.request.url or '').startswith(CHURCHTOOLS_BASE_URL)
    }
    assert {endpoint_template(f'/api{path}') for path in OPENAPI_ENDPOINTS} <= asked


def test_check_fails_and_stops_on_a_wrong_token(
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/api/permissions/global', status=401)
    self_check = SelfCheck(make_config())
    results = self_check.run()
    assert [(r.service, r.name, r.status) for r in results] == [
        ('ChurchTools', 'connection', Status.FAIL),
        ('Immich', 'connection', Status.OFF),
    ]
    assert 'API token' in results[0].details[0]
    assert not self_check.report()


def test_check_warns_without_an_upcoming_event(
    mocked_responses: responses.RequestsMock,
) -> None:
    mock_churchtools_server(mocked_responses)
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/api/events', json={'data': []})
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/songs',
        json={'data': [], 'meta': {'count': 0}},
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/calendars',
        json={'data': [{'id': 1, 'name': 'Services'}]},
    )
    results = run_check(make_config(songbeamer=TEMPLATES))
    assert results['ChurchTools', 'next event'].status is Status.WARN
    assert ('ChurchTools', 'service team') not in results
    # Without an event, there is nothing to look ahead from, but the calendars are
    # still worth naming.
    assert results['ChurchTools', 'appointment slides'].details == [
        'from the calendars Services'
    ]


def test_check_reports_what_a_degrading_call_logs(
    mocked_responses: responses.RequestsMock,
) -> None:
    # `get_person()` swallows the 403 and falls back, so only its log tells.
    mock_churchtools(
        mocked_responses,
        make_global_permissions(view_alldata=False),
        person_answer={'status': 403},
        appointments=False,
    )
    results = run_check(make_config())
    service_team = results['ChurchTools', 'service team']
    assert service_team.status is Status.WARN
    assert any('Skipping person #5' in detail for detail in service_team.details)
    # The skipped feature is reported by its own row, not once more by the step.
    assert not any('nickname lookup' in detail for detail in service_team.details)
    assert results['ChurchTools', 'nickname lookup'].details == [
        'requires permission "churchdb:view alldata"'
    ]


def test_check_names_the_missing_permissions(
    mocked_responses: responses.RequestsMock,
) -> None:
    mock_churchtools(
        mocked_responses, make_global_permissions(edit_events=False), appointments=False
    )
    results = run_check(make_config())
    assert results['ChurchTools', 'song sheets'].status is Status.WARN
    assert results['ChurchTools', 'song sheets'].details == [
        'requires permission "churchservice:edit events"'
    ]
    assert results['ChurchTools', 'appointment slides'].status is Status.OFF


def test_check_names_the_calendar_edit_events_does_not_cover(
    mocked_responses: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `edit events` holds calendar 1 only, so the permission alone looks fine.
    monkeypatch.setitem(EVENT, 'calendar', {'domainIdentifier': '7', 'title': 'Youth'})
    mock_churchtools(mocked_responses, appointments=False)
    results = run_check(make_config())
    assert results['ChurchTools', 'next event'].details[0].startswith('2099-08-23')
    assert '(Youth)' in results['ChurchTools', 'next event'].details[0]
    assert results['ChurchTools', 'song sheets'].status is Status.WARN
    assert results['ChurchTools', 'song sheets'].details == [
        (
            '"churchservice:edit events" covers the calendars 1, but not the '
            'calendar "Youth" (7) of the event'
        )
    ]


def test_check_names_the_calendar_view_agenda_does_not_cover(
    mocked_responses: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(EVENT, 'calendar', {'domainIdentifier': '7', 'title': 'Youth'})
    # Listing the event takes `view events` for its calendar, so only `view agenda`
    # does not cover it.
    permissions = make_global_permissions()
    permissions['data']['churchservice']['view events'] = [1, 7]
    mock_churchtools_server(mocked_responses, permissions)
    api = f'{CHURCHTOOLS_BASE_URL}/api'
    mocked_responses.get(f'{api}/events', json={'data': [EVENT]})
    mocked_responses.get(f'{api}/events/42/agenda', status=403)
    mocked_responses.get(f'{api}/songs', json={'data': [], 'meta': {'count': 0}})
    next_event = run_check(make_config())['ChurchTools', 'next event']
    assert next_event.status is Status.FAIL
    assert next_event.details[0] == (
        '"churchservice:view agenda" covers the calendars 1, but not the calendar '
        '"Youth" (7) of the event'
    )
    assert '403 Client Error' in next_event.details[1]


def test_check_leaves_deprecated_fields_to_the_openapi_check(
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/permissions/global',
        json=make_global_permissions(),
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/info',
        json={'version': '3.136.2', 'build': '1', '@deprecated': {'version': None}},
    )
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/api/events', json={'data': []})
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/songs', json={'data': [], 'meta': {'count': 0}}
    )
    # A user cannot act on them, and some fields are read on purpose despite it.
    with pytest.warns(DeprecationWarning, match="deprecated field 'version'"):
        connection = run_check(make_config())['ChurchTools', 'connection']
    assert connection.status is Status.OK


def test_verbose_check_notes_each_deprecated_field_once(
    mocked_responses: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every song carries the mark, from three endpoints in two steps.
    monkeypatch.setitem(SONG, '@deprecated', {'arrangements': None})
    mock_churchtools(mocked_responses, appointments=False)
    results = SelfCheck(make_config(), deprecations=True).run()
    notes = [(r.name, note) for r in results for note in r.notes]
    assert notes == [
        (
            'next event',
            (
                "Model 'Song' defines deprecated field 'arrangements', "
                'which has no replacement.'
            ),
        )
    ]
    # A note is no problem of the setup.
    assert all(r.status is not Status.WARN for r in results)


def test_check_sees_warnings_despite_a_stricter_log_level(
    mocked_responses: responses.RequestsMock,
) -> None:
    mock_churchtools(
        mocked_responses,
        make_global_permissions(view_alldata=False),
        person_answer={'status': 403},
        appointments=False,
    )
    level = Configuration.log.level
    Configuration.log.setLevel(logging.ERROR)
    try:
        results = run_check(make_config())
        assert Configuration.log.level == logging.ERROR
    finally:
        Configuration.log.setLevel(level)
    assert results['ChurchTools', 'service team'].status is Status.WARN


def test_self_check_command_exits_with_1_on_a_failure(
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/api/permissions/global', status=401)
    result = typer.testing.CliRunner().invoke(
        cli.app, ['self', 'check'], obj=make_config(), env={'COLUMNS': '200'}
    )
    assert result.exit_code == 1
    assert 'FAIL' in result.output
    assert 'not configured' in result.output


def test_self_check_command_lists_deprecations_only_when_verbose(
    mocked_responses: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(SONG, '@deprecated', {'arrangements': None})
    runner = typer.testing.CliRunner()
    for args, listed in ((['self', 'check'], False), (['self', 'check', '-v'], True)):
        mock_churchtools(mocked_responses, appointments=False)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            result = runner.invoke(
                cli.app, args, obj=make_config(), env={'COLUMNS': '200'}
            )
        assert result.exit_code == 0
        assert ("deprecated field 'arrangements'" in result.output) is listed
        mocked_responses.reset()


def test_check_shows_each_step_in_the_progress_bar(
    mocked_responses: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('TTY_COMPATIBLE', '1')
    descriptions: list[str | None] = []
    do_progress = Progress.do_progress

    def record[T](
        self: Progress, item: T, description: str | None = None
    ) -> typing.ContextManager[T]:
        descriptions.append(description)
        return do_progress(self, item, description)

    monkeypatch.setattr(Progress, 'do_progress', record)
    mock_churchtools(mocked_responses)
    mock_immich(mocked_responses)
    results = SelfCheck(make_config(songbeamer=TEMPLATES, immich=IMMICH)).run()
    assert descriptions == [f'{r.service}: {r.name}' for r in results]


def record_progress_end(monkeypatch: pytest.MonkeyPatch) -> list[tuple[float, float]]:
    """Record the completed steps and the total of every progress bar at its end."""
    ends: list[tuple[float, float]] = []
    exit_ = Progress.__exit__

    def record(self: Progress, *args: typing.Any) -> None:  # noqa: ANN401 (passed on)
        (task,) = self.tasks
        ends.append((task.completed, task.total or 0))
        exit_(self, *args)

    monkeypatch.setattr(Progress, '__exit__', record)
    return ends


def test_every_step_of_a_full_run_adds_its_row(
    mocked_responses: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ends = record_progress_end(monkeypatch)
    mock_churchtools(mocked_responses)
    mock_immich(mocked_responses)
    results = SelfCheck(make_config(songbeamer=TEMPLATES, immich=IMMICH)).run()
    assert ends == [(len(results), len(results))]


@pytest.mark.parametrize(
    ('upload_tags', 'permissions', 'tags_answer', 'expected'),
    [
        pytest.param(
            [],
            IMMICH_PERMISSIONS,
            None,
            {
                'media upload': (Status.OFF, 'no upload tags configured'),
                'tag creation': (Status.OFF, 'no upload tags configured'),
            },
            id='not configured',
        ),
        pytest.param(
            ['Upload', 'New'],
            IMMICH_PERMISSIONS,
            {'json': [{'id': 't1', 'name': 'Upload'}, {'id': 't2', 'name': 'New'}]},
            {
                'media upload': (Status.OK, 'tags Upload, New'),
                'tag creation': (Status.OK, 'permitted, all upload tags exist'),
            },
            id='all tags exist',
        ),
        pytest.param(
            ['Upload', 'New'],
            [p for p in IMMICH_PERMISSIONS if p != 'tag.create'],
            {'json': [{'id': 't1', 'name': 'Upload'}, {'id': 't2', 'name': 'New'}]},
            {
                'media upload': (Status.OK, 'tags Upload, New'),
                'tag creation': (Status.WARN, 'requires permission "tag.create"'),
            },
            id='all tags exist, creation not permitted',
        ),
        pytest.param(
            ['Upload', 'New'],
            [p for p in IMMICH_PERMISSIONS if p != 'tag.create'],
            {'json': [{'id': 't1', 'name': 'Upload'}]},
            {
                'media upload': (Status.OK, 'tags Upload'),
                'tag creation': (
                    Status.WARN,
                    (
                        'cannot create the missing tags New, '
                        'it requires permission "tag.create"'
                    ),
                ),
            },
            id='tag missing, creation not permitted',
        ),
        pytest.param(
            ['Upload', 'New'],
            IMMICH_PERMISSIONS,
            {'status': 500},
            {
                'media upload': (
                    Status.WARN,
                    'the upload tags could not be looked up',
                ),
                'tag creation': (Status.OK, 'permitted'),
            },
            id='lookup fails',
        ),
        pytest.param(
            ['Upload', 'New'],
            [p for p in IMMICH_PERMISSIONS if p != 'tag.read'],
            None,
            {
                'media upload': (Status.WARN, 'requires permission "tag.read"'),
                'tag creation': (Status.OK, 'permitted'),
            },
            id='upload not permitted',
        ),
    ],
)
def test_tag_creation_checks_the_permission_whether_needed_or_not(
    mocked_responses: responses.RequestsMock,
    upload_tags: list[str],
    permissions: list[str],
    tags_answer: dict[str, typing.Any] | None,
    expected: dict[str, tuple[Status, str]],
) -> None:
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/api/permissions/global', status=401)
    mock_immich_server(mocked_responses, permissions)
    if tags_answer is not None:
        mocked_responses.get(f'{IMMICH_BASE_URL}/api/tags', **tags_answer)
    results = run_check(make_config(immich={'upload_tags': upload_tags}))
    assert {
        name: (results['Immich', name].status, *results['Immich', name].details)
        for name in expected
    } == expected


def test_progress_reaches_its_total_when_steps_are_skipped(
    mocked_responses: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ends = record_progress_end(monkeypatch)
    # No ChurchTools connection, and Immich does not know the token either.
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/api/permissions/global', status=401)
    mocked_responses.get(f'{IMMICH_BASE_URL}/api/api-keys/me', status=401)
    results = SelfCheck(make_config(immich=IMMICH)).run()
    assert len(results) == 2
    ((completed, total),) = ends
    assert completed == total


def test_progress_counts_the_steps_left_out_without_an_event(
    mocked_responses: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ends = record_progress_end(monkeypatch)
    mock_churchtools_server(mocked_responses)
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/api/events', json={'data': []})
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/songs', json={'data': [], 'meta': {'count': 0}}
    )
    results = run_check(make_config())
    assert ('ChurchTools', 'service team') not in results
    ((completed, total),) = ends
    assert completed == total
