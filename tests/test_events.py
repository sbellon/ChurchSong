# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import datetime
import io
import logging
import typing

import pypdf
import reportlab.lib.pagesizes
import reportlab.pdfgen.canvas
import requests

import churchsong.churchtools.events
from churchsong.churchtools import ChurchToolsAPI, EventShort
from churchsong.churchtools.events import ChurchToolsEvent, ItemType, PdfSheet, Person
from churchsong.immich import ImmichAPI
from tests.conftest import (
    CHURCHTOOLS_BASE_URL,
    IMMICH_BASE_URL,
    make_config,
    make_global_permissions,
)

if typing.TYPE_CHECKING:
    import pathlib

    import pytest
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


def test_download_agenda_items_without_download_files_skips_immich_upload(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = make_config(output_dir=str(tmp_path), immich={})
    mocked_responses.get(
        f'{IMMICH_BASE_URL}/api/api-keys/me', json={'permissions': ['asset.upload']}
    )
    register_event_endpoints(
        mocked_responses,
        event_files=[
            {
                'title': 'Photo',
                'domainType': 'file',
                'domainIdentifier': 903,
                'frontendUrl': f'{CHURCHTOOLS_BASE_URL}/files/903',
            },
        ],
    )
    # The request is made even with `download_files=False`, as the filename of
    # the agenda item comes out of its `Content-Disposition` header; only the
    # body is left unread.
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/files/903',
        body=b'jpeg content',
        headers={'Content-Disposition': 'filename="IMG_1234.jpg"'},
    )

    event = make_churchtools_event(churchtools_api, config)
    with caplog.at_level(logging.ERROR):
        items = event.download_agenda_items(
            download_files=False,
            upload_songsheets=False,
            immich_upload=ImmichAPI(config),
        )

    photo = tmp_path / 'Files' / 'IMG_1234.jpg'
    assert [(item.type, item.filename) for item in items] == [
        (ItemType.FILE, str(photo))
    ]
    assert not photo.exists()
    # The file that was never written must not abort the event: Immich sees only
    # the permission check of its constructor, and the missing file is contained
    # by `upload_media_file` instead of escaping as a `FileNotFoundError`.
    assert [
        call.request.url
        for call in mocked_responses.calls
        if (call.request.url or '').startswith(IMMICH_BASE_URL)
    ] == [f'{IMMICH_BASE_URL}/api/api-keys/me']
    assert 'IMG_1234.jpg' in caplog.text


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
    # The "nobody" entry backs template placeholders for services that nobody is
    # assigned to; the exact `service_items` above show it is not a service itself.
    assert service_leads[str(None)] == {Person('Nobody', 'Nobody')}


SONG_ITEM: dict[str, object] = {
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
}


def register_song(
    mocked_responses: responses.RequestsMock, files: list[dict[str, str]]
) -> None:
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
                        'files': files,
                    }
                ],
            }
        },
    )


def extract_pdf_text(content: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(content))
    return '\n'.join(page.extract_text() for page in reader.pages)


def test_song_sheet_marks_a_missing_song_with_a_watermark() -> None:
    sheet = PdfSheet(
        'Song Sheets Chords',
        'Sunday Service - 2026-08-23',
        'Last update: {last_modified:%Y-%m-%d}',
        ('Title', 'CCLI No.', 'Arrangement'),
    )
    sheet.append('Amazing Grace', '22025', 'Standard', io.BytesIO(make_pdf('chords')))
    sheet.append('Be Thou My Vision', '12345', 'Standard', None)  # no PDF in the DB
    last_modified = datetime.datetime(2026, 8, 16, tzinfo=datetime.UTC)
    text = extract_pdf_text(sheet.finalize(last_modified=last_modified))
    # Title page with the table of contents, then one page per song.
    assert 'Song Sheets Chords' in text
    assert 'Last update: 2026-08-16' in text
    assert 'chords' in text
    assert 'MISSING' in text
    assert text.count('Be Thou My Vision') == 2  # table of contents and placeholder


def test_download_agenda_items_survives_a_failing_file_download(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = make_config(output_dir=str(tmp_path))
    register_event_endpoints(
        mocked_responses,
        event_files=[
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
    )
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/files/901', status=500)
    mocked_responses.post(f'{CHURCHTOOLS_BASE_URL}/api/files/service/42', json={})
    event = make_churchtools_event(churchtools_api, config)
    with caplog.at_level(logging.WARNING):
        items = event.download_agenda_items(immich_upload=ImmichAPI(config))
    assert 'Failed to download event file for Notes' in caplog.text
    # The unusable file is dropped, everything else still makes it.
    assert [item.title for item in items] == ['Livestream']


def test_download_agenda_items_survives_a_failing_song_download(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = make_config(output_dir=str(tmp_path))
    register_event_endpoints(
        mocked_responses,
        agenda_items=[{'title': 'Welcome', 'type': 'header', 'meta': META}, SONG_ITEM],
    )
    register_song(
        mocked_responses,
        [
            {
                'name': 'amazing-grace.sng',
                'fileUrl': f'{CHURCHTOOLS_BASE_URL}/files/sng/7',
            }
        ],
    )
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/files/sng/7', status=500)
    mocked_responses.post(f'{CHURCHTOOLS_BASE_URL}/api/files/service/42', json={})
    event = make_churchtools_event(churchtools_api, config)
    with caplog.at_level(logging.WARNING):
        items = event.download_agenda_items(immich_upload=ImmichAPI(config))
    assert 'Failed to download agenda file for Amazing Grace' in caplog.text
    assert [item.title for item in items] == ['Welcome']


def test_download_file_falls_back_to_the_item_title(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
) -> None:
    config = make_config(output_dir=str(tmp_path))
    register_event_endpoints(
        mocked_responses,
        event_files=[
            {
                'title': 'Notes.pdf',
                'domainType': 'file',
                'domainIdentifier': 901,
                'frontendUrl': f'{CHURCHTOOLS_BASE_URL}/files/901',
            }
        ],
    )
    # Without a Content-Disposition header the event file title is used.
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/files/901', body=b'notes content')
    mocked_responses.post(f'{CHURCHTOOLS_BASE_URL}/api/files/service/42', json={})
    event = make_churchtools_event(churchtools_api, config)
    (item,) = event.download_agenda_items(immich_upload=ImmichAPI(config))
    assert item.filename == str(tmp_path / 'Files' / 'Notes.pdf')


def test_download_file_replaces_a_dangerous_filename(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
) -> None:
    config = make_config(output_dir=str(tmp_path))
    register_event_endpoints(
        mocked_responses,
        event_files=[
            {
                'title': 'Notes',
                'domainType': 'file',
                'domainIdentifier': 901,
                'frontendUrl': f'{CHURCHTOOLS_BASE_URL}/files/901',
            }
        ],
    )
    # A filename that would escape the output directory is not used as-is.
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/files/901',
        body=b'notes content',
        headers={'Content-Disposition': 'filename=".."'},
    )
    mocked_responses.post(f'{CHURCHTOOLS_BASE_URL}/api/files/service/42', json={})
    event = make_churchtools_event(churchtools_api, config)
    (item,) = event.download_agenda_items(immich_upload=ImmichAPI(config))
    assert item.filename == str(tmp_path / 'Files' / 'unnamed')


def test_disabled_songsheets_still_download_the_song(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
) -> None:
    config = make_config(output_dir=str(tmp_path))
    register_event_endpoints(mocked_responses, agenda_items=[SONG_ITEM])
    register_song(
        mocked_responses,
        [
            {
                'name': 'amazing-grace.sng',
                'fileUrl': f'{CHURCHTOOLS_BASE_URL}/files/sng/7',
            },
            {
                'name': 'amazing-grace-chords-sheet.pdf',
                'fileUrl': f'{CHURCHTOOLS_BASE_URL}/files/chords/7',
            },
        ],
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/files/sng/7', body=b'#Title=Amazing Grace'
    )
    # Neither the chords PDF is downloaded nor is a song sheet uploaded: no
    # endpoint is registered for either, so both would fail the test.
    event = make_churchtools_event(churchtools_api, config)
    (item,) = event.download_agenda_items(
        upload_songsheets=False, immich_upload=ImmichAPI(config)
    )
    assert item.filename == str(tmp_path / 'Songs' / 'Amazing Grace')


def test_get_service_info_merges_several_persons_of_one_service(
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
) -> None:
    config = make_config(output_dir=str(tmp_path))
    register_event_endpoints(
        mocked_responses,
        event_services=[
            {'personId': None, 'name': 'Jane Doe', 'serviceId': 1},
            {'personId': None, 'name': 'John Newton', 'serviceId': 1},
        ],
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/services',
        json={'data': [{'id': 1, 'name': 'Music'}]},
    )
    event = make_churchtools_event(churchtools_api, config)
    service_items, service_leads = event.get_service_info()
    assert [item.title for item in service_items] == ['Music: Jane Doe, John Newton']
    assert {person.shortname for person in service_leads['Music']} == {'Jane', 'John'}


def test_download_file_streams_the_body_instead_of_buffering_it(
    monkeypatch: pytest.MonkeyPatch,
    churchtools_api: ChurchToolsAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
) -> None:
    config = make_config(output_dir=str(tmp_path))
    register_event_endpoints(
        mocked_responses,
        event_files=[
            {
                'title': 'Video.mp4',
                'domainType': 'file',
                'domainIdentifier': 901,
                'frontendUrl': f'{CHURCHTOOLS_BASE_URL}/files/901',
            }
        ],
    )
    body = bytes(range(256)) * 8
    mocked_responses.get(f'{CHURCHTOOLS_BASE_URL}/files/901', body=body)
    mocked_responses.post(f'{CHURCHTOOLS_BASE_URL}/api/files/service/42', json={})

    # Event files are videos and photos, so they go to disk chunk by chunk instead
    # of through `Response.content`, which would hold the whole file in memory.
    # `Response.content` itself streams with `CONTENT_CHUNK_SIZE`, hence the URL.
    chunk_sizes: list[tuple[str, int]] = []
    original_iter_content = requests.Response.iter_content

    def spy_iter_content(
        self: requests.Response, chunk_size: int = 1, *, decode_unicode: bool = False
    ) -> typing.Iterator[str | bytes]:
        chunk_sizes.append((self.url, chunk_size))
        return original_iter_content(
            self, chunk_size=chunk_size, decode_unicode=decode_unicode
        )

    monkeypatch.setattr(requests.Response, 'iter_content', spy_iter_content)
    monkeypatch.setattr(churchsong.churchtools.events, 'DOWNLOAD_CHUNK_SIZE', 512)

    event = make_churchtools_event(churchtools_api, config)
    (item,) = event.download_agenda_items(immich_upload=ImmichAPI(config))

    assert item.filename == str(tmp_path / 'Files' / 'Video.mp4')
    # Reassembled from four chunks, byte for byte.
    assert (tmp_path / 'Files' / 'Video.mp4').read_bytes() == body
    assert [
        chunk_size
        for url, chunk_size in chunk_sizes
        if url == f'{CHURCHTOOLS_BASE_URL}/files/901'
    ] == [512]
