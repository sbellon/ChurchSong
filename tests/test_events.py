# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import io
import typing

import reportlab.lib.pagesizes
import reportlab.pdfgen.canvas

from churchsong.churchtools import ChurchToolsAPI, EventShort
from churchsong.churchtools.events import ChurchToolsEvent, ItemType
from churchsong.immich import ImmichAPI
from tests.conftest import (
    CHURCHTOOLS_BASE_URL,
    make_config,
    make_global_permissions,
)

if typing.TYPE_CHECKING:
    import pathlib

    import responses

    from churchsong.configuration import Configuration


def make_pdf(text: str) -> bytes:
    data = io.BytesIO()
    canvas = reportlab.pdfgen.canvas.Canvas(data, pagesize=reportlab.lib.pagesizes.A4)
    canvas.drawString(72, 720, text)
    canvas.save()
    return data.getvalue()


def make_event_short() -> EventShort:
    return EventShort.model_validate(
        {
            'id': 42,
            'name': 'Sunday Service',
            'startDate': '2026-08-23T10:00:00Z',
            'endDate': '2026-08-23T12:00:00Z',
        }
    )


def register_event_endpoints(
    mocked_responses: responses.RequestsMock,
    *,
    event_files: list[dict[str, object]] | None = None,
    event_services: list[dict[str, object]] | None = None,
    agenda_items: list[dict[str, object]] | None = None,
) -> None:
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/events/42',
        json={
            'data': {
                'id': 42,
                'name': 'Sunday Service',
                'startDate': '2026-08-23T10:00:00Z',
                'endDate': '2026-08-23T12:00:00Z',
                'eventFiles': event_files or [],
                'eventServices': event_services or [],
            }
        },
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/events/42/agenda',
        json={'data': {'id': 1, 'items': agenda_items or []}},
    )


def make_churchtools_event(
    churchtools_api: ChurchToolsAPI, config: Configuration
) -> ChurchToolsEvent:
    return ChurchToolsEvent(churchtools_api, make_event_short(), config)


META = {'modifiedDate': '2026-08-16T10:00:00Z'}


def test_download_agenda_items_full_pipeline(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
) -> None:
    config = make_config(output_dir=str(tmp_path))
    register_event_endpoints(
        mocked_responses,
        event_files=[
            {
                # Stale song sheet from a previous run: deleted, not downloaded.
                'title': 'Song Sheets Chords.pdf',
                'domainType': 'file',
                'domainIdentifier': 900,
                'frontendUrl': f'{CHURCHTOOLS_BASE_URL}/files/900',
            },
            {
                'title': 'Notes',
                'domainType': 'file',
                'domainIdentifier': 901,
                'frontendUrl': f'{CHURCHTOOLS_BASE_URL}/files/901',
            },
            {
                'title': 'Livestream',
                'domainType': 'link',
                'domainIdentifier': 902,
                'frontendUrl': 'https://stream.test/live',
            },
        ],
        agenda_items=[
            {'title': 'Welcome', 'type': 'header', 'meta': META},
            {'title': 'Announcements', 'type': 'text', 'meta': META},
            {
                'title': 'Song 1',
                'type': 'song',
                'meta': META,
                'song': {
                    'songId': 7,
                    'arrangementId': 70,
                    'title': 'Amazing Grace',
                    'arrangement': 'Standard',
                    'key': 'G',
                    'isDefault': True,
                },
            },
            # Song item without song data is skipped with a warning.
            {'title': 'Broken Song', 'type': 'song', 'meta': META, 'song': None},
        ],
    )
    mocked_responses.delete(f'{CHURCHTOOLS_BASE_URL}/api/files/900', json={})
    # ChurchTools sends UTF-8 filenames declared as latin-1; _download_file
    # must decode them back.
    mangled_filename = 'Grüße.pdf'.encode().decode('latin1')
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/files/901',
        body=b'notes content',
        headers={'Content-Disposition': f'filename="{mangled_filename}"'},
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/songs/7',
        json={
            'data': {
                'id': 7,
                'name': 'Amazing Grace',
                'author': 'John Newton',
                'ccli': '22025',
                'arrangements': [
                    {
                        'id': 70,
                        'name': 'Standard',
                        'isDefault': True,
                        'source': None,
                        'sourceReference': None,
                        'key': 'G',
                        'beat': None,
                        'tempo': None,
                        'duration': 180,
                        'files': [
                            {
                                'name': 'amazing-grace.sng',
                                'fileUrl': f'{CHURCHTOOLS_BASE_URL}/files/sng/7',
                            },
                            {
                                'name': 'amazing-grace-chords-sheet.pdf',
                                'fileUrl': f'{CHURCHTOOLS_BASE_URL}/files/chords/7',
                            },
                            {
                                # The `-lead-` part is important!
                                'name': 'amazing-grace-lead-sheet.pdf',
                                'fileUrl': f'{CHURCHTOOLS_BASE_URL}/files/leads/7',
                            },
                        ],
                    }
                ],
            }
        },
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/files/sng/7',
        body=b'#Title=Amazing Grace',
        headers={'Content-Disposition': 'filename="amazing-grace.sng"'},
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/files/chords/7', body=make_pdf('chords')
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/files/leads/7', body=make_pdf('leads')
    )
    mocked_responses.post(f'{CHURCHTOOLS_BASE_URL}/api/files/service/42', json={})

    event = make_churchtools_event(churchtools_api, config)
    items = event.download_agenda_items(immich_upload=ImmichAPI(config))

    assert [(item.type, item.title) for item in items] == [
        (ItemType.FILE, 'Notes'),
        (ItemType.LINK, 'Livestream'),
        (ItemType.HEADER, 'Welcome'),
        (ItemType.NORMAL, 'Announcements'),
        (ItemType.SONG, 'Amazing Grace'),
        # song title taken from song, not agenda (would be 'Song 1' otherwise)
    ]
    assert items[1].filename == 'https://stream.test/live'

    notes_file = tmp_path / 'Files' / 'Grüße.pdf'
    assert items[0].filename == str(notes_file)
    assert notes_file.read_bytes() == b'notes content'
    sng_file = tmp_path / 'Songs' / 'amazing-grace.sng'
    assert items[4].filename == str(sng_file)
    assert sng_file.read_bytes() == b'#Title=Amazing Grace'

    uploads = [
        call.request
        for call in mocked_responses.calls
        if call.request.method == 'POST'
        and (call.request.url or '').endswith('/api/files/service/42')
    ]
    assert len(uploads) == 2
    for upload, name in zip(
        uploads, [b'Song Sheets Chords.pdf', b'Song Sheets Leads.pdf'], strict=True
    ):
        body = typing.cast('bytes', upload.body)
        assert name in body
        assert b'%PDF' in body


def test_download_agenda_items_with_disabled_songsheets_skips_stale_sheets(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
) -> None:
    config = make_config(output_dir=str(tmp_path))
    register_event_endpoints(
        mocked_responses,
        event_files=[
            {
                # Neither downloaded nor deleted: no matching mock is registered,
                # so any HTTP request for it would fail the test.
                'title': 'Song Sheets Leads.pdf',
                'domainType': 'file',
                'domainIdentifier': 900,
                'frontendUrl': f'{CHURCHTOOLS_BASE_URL}/files/900',
            },
        ],
    )
    event = make_churchtools_event(churchtools_api, config)
    items = event.download_agenda_items(
        upload_songsheets=False, immich_upload=ImmichAPI(config)
    )
    assert items == []


def test_download_agenda_items_without_edit_permission_skips_songsheets(
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
) -> None:
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/permissions/global',
        json=make_global_permissions(edit_events=False),
    )
    config = make_config(output_dir=str(tmp_path))
    api = ChurchToolsAPI(config)
    register_event_endpoints(mocked_responses)
    event = make_churchtools_event(api, config)
    # No DELETE/POST mocks registered: uploads would fail the test.
    items = event.download_agenda_items(immich_upload=ImmichAPI(config))
    assert items == []


def test_get_service_info_resolves_persons_nicknames_and_replacements(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
) -> None:
    config = make_config(
        output_dir=str(tmp_path), replacements={'Volunteer Name': 'Vol N.'}
    )
    register_event_endpoints(
        mocked_responses,
        event_services=[
            {'personId': 5, 'name': None, 'serviceId': 1},
            {'personId': None, 'name': 'Volunteer Name', 'serviceId': 2},
            {'personId': None, 'name': None, 'serviceId': 3},
        ],
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/services',
        json={
            'data': [
                {'id': 1, 'name': 'Preaching'},
                {'id': 2, 'name': 'Music'},
                {'id': 3, 'name': 'Welcome'},
            ]
        },
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/persons/5',
        json={'data': {'firstName': 'Jane', 'lastName': 'Doe', 'nickname': 'JD'}},
    )

    event = make_churchtools_event(churchtools_api, config)
    service_items, service_leads = event.get_service_info()

    assert [(item.type, item.title) for item in service_items] == [
        (ItemType.SERVICE, 'Music: Vol N.'),
        (ItemType.SERVICE, 'Preaching: Jane Doe'),
        (ItemType.SERVICE, 'Welcome: Nobody'),
    ]
    (preacher,) = service_leads['Preaching']
    assert preacher.fullname == 'Jane Doe'
    assert preacher.shortname == 'JD'
    (musician,) = service_leads['Music']
    assert musician.shortname == 'Vol'
