# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import json
import logging
import pathlib
import typing

import pytest
import requests
import responses.matchers

from churchsong.immich import ImmichAPI
from churchsong.utils import CliError
from tests.conftest import IMMICH_BASE_URL, make_config, mock_immich_server

if typing.TYPE_CHECKING:
    from churchsong.configuration import Configuration

UPLOAD_PERMISSIONS = ['asset.upload', 'tag.read', 'tag.asset']


def connect_immich(config: Configuration) -> ImmichAPI:
    """An `ImmichAPI` connected to the (mocked) Immich instance of `config`."""
    api = ImmichAPI(config)
    api.connect()
    return api


@pytest.fixture
def immich_api(mocked_responses: responses.RequestsMock) -> ImmichAPI:
    """An Immich API that uploads media files, tagging them with tag `t1`."""
    mock_immich_server(mocked_responses, UPLOAD_PERMISSIONS)
    mocked_responses.get(
        f'{IMMICH_BASE_URL}/api/tags', json=[{'id': 't1', 'name': 'Upload'}]
    )
    return connect_immich(make_config(immich={'upload_tags': ['Upload']}))


def mock_upload(
    mocked_responses: responses.RequestsMock, media_file: pathlib.Path
) -> None:
    """Register the requests of a successful upload of a new media file."""
    mocked_responses.post(
        f'{IMMICH_BASE_URL}/api/assets/bulk-upload-check',
        json={'results': [{'action': 'accept', 'id': media_file.name}]},
    )
    mocked_responses.post(f'{IMMICH_BASE_URL}/api/assets', json={'id': 'asset-1'})
    mocked_responses.put(f'{IMMICH_BASE_URL}/api/tags/assets', json={'count': 1})


def test_init_without_immich_section_disables_upload_without_http() -> None:
    # No responses mock is active: any HTTP request would hit the network
    # and fail, so no thrown exception also proves that no request is made.
    api = ImmichAPI(make_config())
    api.upload_media_file('IMG_1234.jpg')


@pytest.mark.parametrize('missing', UPLOAD_PERMISSIONS)
def test_upload_is_skipped_without_permission(
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
    missing: str,
) -> None:
    mock_immich_server(
        mocked_responses, [perm for perm in UPLOAD_PERMISSIONS if perm != missing]
    )
    # Neither the tags are enumerated nor is anything uploaded: no such request is
    # registered, so it would fail the test.
    with caplog.at_level(logging.WARNING):
        api = connect_immich(make_config(immich={'upload_tags': ['Upload']}))
        api.upload_media_file(str(make_media_file(tmp_path)))
    assert f'Skipping media upload due to missing permissions: "{missing}"' in (
        caplog.text
    )


def test_upload_is_skipped_without_upload_tags(
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_immich_server(mocked_responses, UPLOAD_PERMISSIONS)
    # Nothing is uploaded that could not be tagged: no tag enumeration, no upload,
    # and - as an unconfigured feature - no warning either.
    with caplog.at_level(logging.WARNING):
        api = connect_immich(make_config(immich={}))
        api.upload_media_file(str(make_media_file(tmp_path)))
    assert not caplog.records
    assert not api.upload_enabled


def test_enabled_predicates_follow_the_usable_tags_and_album(
    immich_api: ImmichAPI, mocked_responses: responses.RequestsMock
) -> None:
    # The fixture has a usable upload tag but no backgrounds album ...
    assert immich_api.upload_enabled
    assert not immich_api.backgrounds_enabled
    # ... and a read-only token the other way round.
    api = make_background_api(mocked_responses, BACKGROUND_PERMISSIONS)
    assert not api.upload_enabled
    assert api.backgrounds_enabled


def test_nothing_is_enabled_without_immich_section() -> None:
    api = ImmichAPI(make_config())
    api.connect()
    assert not api.upload_enabled
    assert not api.backgrounds_enabled


def test_init_does_not_contact_immich(mocked_responses: responses.RequestsMock) -> None:
    # No endpoint is registered: a request from the constructor would fail the test.
    api = ImmichAPI(
        make_config(immich={'upload_tags': ['Upload'], 'backgrounds_album': 'Bg'})
    )
    # Before `connect()`, both features are off, which is a valid state to use.
    assert not api.upload_enabled
    assert not api.backgrounds_enabled
    assert not mocked_responses.calls


def test_failed_connect_leaves_a_usable_instance(
    mocked_responses: responses.RequestsMock, tmp_path: pathlib.Path
) -> None:
    mocked_responses.get(f'{IMMICH_BASE_URL}/api/api-keys/me', status=401)
    api = ImmichAPI(
        make_config(immich={'upload_tags': ['Upload'], 'backgrounds_album': 'Bg'})
    )
    with pytest.raises(CliError, match='Immich API token'):
        api.connect()
    assert not api.upload_enabled
    assert not api.backgrounds_enabled
    # Neither feature makes a request: none is registered beyond the failed one.
    api.upload_media_file(str(make_media_file(tmp_path)))
    assert api.download_random_background(tmp_path) is None
    assert len(mocked_responses.calls) == 1


def test_log_records_name_the_immich_component(
    immich_api: ImmichAPI, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        assert not immich_api.has_permissions(['tag.create'], 'tagging')
    # The log file has to be able to tell an Immich warning from a ChurchTools one.
    assert [record.name for record in caplog.records] == ['churchsong.immich']


def test_upload_skips_files_not_matching_include_globbings(
    immich_api: ImmichAPI,
) -> None:
    # Not a media file: neither the duplicate check nor the upload endpoint
    # is registered, so an HTTP request would fail the test.
    immich_api.upload_media_file('notes.txt')


def test_upload_skips_duplicate_files(
    immich_api: ImmichAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
) -> None:
    media_file = tmp_path / 'IMG_1234.jpg'
    media_file.write_bytes(b'not really a jpeg')
    mocked_responses.post(
        f'{IMMICH_BASE_URL}/api/assets/bulk-upload-check',
        json={
            'results': [
                {'action': 'reject', 'id': media_file.name, 'reason': 'duplicate'}
            ]
        },
    )
    # Only the duplicate check is registered; an upload attempt would fail.
    immich_api.upload_media_file(str(media_file))


def test_upload_posts_new_media_file(
    immich_api: ImmichAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
) -> None:
    media_file = make_media_file(tmp_path)
    mock_upload(mocked_responses, media_file)
    immich_api.upload_media_file(str(media_file))
    upload_request = next(
        call.request
        for call in mocked_responses.calls
        if call.request.url == f'{IMMICH_BASE_URL}/api/assets'
    )
    assert upload_request.headers['x-api-key'] == 'immich-test-token'
    body = upload_request.body
    assert body is not None
    assert b'IMG_1234.jpg' in bytes(typing.cast('bytes', body))


def make_immich_api(
    mocked_responses: responses.RequestsMock,
    permissions: list[str] = UPLOAD_PERMISSIONS,
    *,
    tags: list[str] | None = None,
    known_tags: list[dict[str, str]] | None = None,
) -> ImmichAPI:
    mock_immich_server(mocked_responses, permissions)
    if known_tags is not None:
        mocked_responses.get(f'{IMMICH_BASE_URL}/api/tags', json=known_tags)
    return connect_immich(make_config(immich={'upload_tags': tags or []}))


def make_media_file(tmp_path: pathlib.Path) -> pathlib.Path:
    media_file = tmp_path / 'IMG_1234.jpg'
    media_file.write_bytes(b'not really a jpeg')
    return media_file


def test_connect_reports_an_unreachable_immich_instance(
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(
        f'{IMMICH_BASE_URL}/api/api-keys/me',
        body=requests.exceptions.ConnectionError('no route to host'),
    )
    with pytest.raises(CliError, match='configure the URL'):
        connect_immich(make_config(immich={}))


def test_connect_reports_a_wrong_immich_token(
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(f'{IMMICH_BASE_URL}/api/api-keys/me', status=401)
    with pytest.raises(CliError, match='Immich API token'):
        connect_immich(make_config(immich={}))


def test_connect_reports_a_non_json_answer_as_a_url_problem(
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(
        f'{IMMICH_BASE_URL}/api/api-keys/me',
        body='<html><body>Please log in</body></html>',
        content_type='text/html',
    )
    with pytest.raises(CliError, match='configure the URL') as excinfo:
        connect_immich(make_config(immich={}))
    assert IMMICH_BASE_URL in str(excinfo.value)


def test_connect_reports_an_off_shape_permissions_answer(
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(
        f'{IMMICH_BASE_URL}/api/api-keys/me', json={'message': 'maintenance'}
    )
    with pytest.raises(CliError, match='configure the URL') as excinfo:
        connect_immich(make_config(immich={}))
    assert IMMICH_BASE_URL in str(excinfo.value)


def test_upload_tags_the_new_asset_with_the_configured_tags(
    mocked_responses: responses.RequestsMock, tmp_path: pathlib.Path
) -> None:
    # 'Service' already exists in Immich, 'New' has to be created first.
    mocked_responses.post(
        f'{IMMICH_BASE_URL}/api/tags', json={'id': 't2', 'name': 'New'}
    )
    api = make_immich_api(
        mocked_responses,
        ['asset.upload', 'tag.read', 'tag.create', 'tag.asset'],
        tags=['Service', 'New'],
        known_tags=[{'id': 't1', 'name': 'Service'}],
    )
    media_file = make_media_file(tmp_path)
    mocked_responses.post(
        f'{IMMICH_BASE_URL}/api/assets/bulk-upload-check',
        json={'results': [{'action': 'accept', 'id': media_file.name}]},
    )
    mocked_responses.post(f'{IMMICH_BASE_URL}/api/assets', json={'id': 'asset-1'})
    mocked_responses.put(f'{IMMICH_BASE_URL}/api/tags/assets', json={'count': 1})
    api.upload_media_file(str(media_file))
    body = mocked_responses.calls[-1].request.body
    assert body is not None
    assert json.loads(typing.cast('bytes', body)) == {
        'assetIds': ['asset-1'],
        'tagIds': ['t1', 't2'],
    }


def test_upload_is_skipped_without_any_usable_tag(
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # No POST /api/tags is registered: creating the unknown tag would fail.
    with caplog.at_level(logging.WARNING):
        api = make_immich_api(mocked_responses, tags=['New'], known_tags=[])
        # Neither is anything of the upload registered: an untagged file is not
        # uploaded at all.
        api.upload_media_file(str(make_media_file(tmp_path)))
    assert 'Skipping tag creation' in caplog.text
    assert 'none of the upload tags exists' in caplog.text


def test_upload_uses_the_tags_that_are_usable(
    mocked_responses: responses.RequestsMock, tmp_path: pathlib.Path
) -> None:
    # 'New' cannot be created without `tag.create`, but 'Service' exists.
    api = make_immich_api(
        mocked_responses,
        tags=['Service', 'New'],
        known_tags=[{'id': 't1', 'name': 'Service'}],
    )
    media_file = make_media_file(tmp_path)
    mock_upload(mocked_responses, media_file)
    api.upload_media_file(str(media_file))
    body = mocked_responses.calls[-1].request.body
    assert body is not None
    assert json.loads(typing.cast('bytes', body))['tagIds'] == ['t1']


def test_upload_skips_unsupported_files(
    immich_api: ImmichAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    media_file = make_media_file(tmp_path)
    mocked_responses.post(
        f'{IMMICH_BASE_URL}/api/assets/bulk-upload-check',
        json={
            'results': [
                {
                    'action': 'reject',
                    'id': media_file.name,
                    'reason': 'unsupported-format',
                }
            ]
        },
    )
    with caplog.at_level(logging.INFO):
        immich_api.upload_media_file(str(media_file))
    assert 'unsupported file' in caplog.text


def test_upload_skips_files_rejected_without_a_reason(
    immich_api: ImmichAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    media_file = make_media_file(tmp_path)
    mocked_responses.post(
        f'{IMMICH_BASE_URL}/api/assets/bulk-upload-check',
        json={'results': [{'action': 'reject', 'id': media_file.name}]},
    )
    with caplog.at_level(logging.INFO):
        immich_api.upload_media_file(str(media_file))
    assert 'Skipping upload of file' in caplog.text


def test_upload_skips_excluded_files(
    mocked_responses: responses.RequestsMock, tmp_path: pathlib.Path
) -> None:
    mock_immich_server(mocked_responses, UPLOAD_PERMISSIONS)
    mocked_responses.get(
        f'{IMMICH_BASE_URL}/api/tags', json=[{'id': 't1', 'name': 'Upload'}]
    )
    api = connect_immich(
        make_config(
            immich={'upload_tags': ['Upload'], 'exclude_globbings': ['*_edited.jpg']}
        )
    )
    # The file matches the include globbings, but is excluded again: neither
    # the duplicate check nor the upload endpoint is registered.
    api.upload_media_file(str(tmp_path / 'IMG_1234_edited.jpg'))


def test_upload_survives_a_failing_immich_request(
    immich_api: ImmichAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    media_file = make_media_file(tmp_path)
    mocked_responses.post(
        f'{IMMICH_BASE_URL}/api/assets/bulk-upload-check',
        body=requests.exceptions.ConnectionError('immich is down'),
    )
    # An unreachable Immich must not abort the agenda of an event.
    with caplog.at_level(logging.ERROR):
        immich_api.upload_media_file(str(media_file))
    assert 'immich is down' in caplog.text


def test_upload_survives_a_malformed_immich_answer(
    immich_api: ImmichAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    media_file = make_media_file(tmp_path)
    mocked_responses.post(
        f'{IMMICH_BASE_URL}/api/assets/bulk-upload-check', json={'results': []}
    )
    with caplog.at_level(logging.ERROR):
        immich_api.upload_media_file(str(media_file))
    assert caplog.records


def test_upload_survives_a_missing_file(
    immich_api: ImmichAPI,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A file the caller decided not to download: the checksum of the duplicate
    # check runs before any request, so neither endpoint is registered here and
    # an HTTP request would fail the test.
    with caplog.at_level(logging.ERROR):
        immich_api.upload_media_file(str(tmp_path / 'IMG_1234.jpg'))
    assert 'IMG_1234.jpg' in caplog.text


BACKGROUND_PERMISSIONS = ['album.read', 'asset.read', 'asset.download']

ALBUMS = [
    {'id': 'al1', 'albumName': 'Backgrounds'},
    {'id': 'al2', 'albumName': 'Holidays'},
]


def make_background_api(
    mocked_responses: responses.RequestsMock,
    permissions: list[str] | None = None,
    *,
    albums: list[dict[str, str]] = ALBUMS,
    server_version: tuple[int, int, int] | None = (3, 2, 0),
) -> ImmichAPI:
    if permissions is None:
        permissions = ['asset.upload', *BACKGROUND_PERMISSIONS]
    mock_immich_server(mocked_responses, permissions, version=server_version)
    # The albums are only listed if the background download can use them.
    if set(BACKGROUND_PERMISSIONS) <= set(permissions) and (
        server_version is not None and server_version >= (3, 2, 0)
    ):
        mocked_responses.get(f'{IMMICH_BASE_URL}/api/albums', json=albums)
    return connect_immich(make_config(immich={'backgrounds_album': 'Backgrounds'}))


def mock_random_search(
    mocked_responses: responses.RequestsMock,
    album_ids: list[str],
    asset_ids: list[str],
) -> None:
    mocked_responses.post(
        f'{IMMICH_BASE_URL}/api/search/random',
        json=[{'id': asset_id} for asset_id in asset_ids],
        match=[
            responses.matchers.json_params_matcher(
                {
                    'filter': {
                        'type': {'eq': 'IMAGE'},
                        'albumIds': {'any': album_ids},
                        'trashedAt': {'eq': None},
                        'isOffline': {'eq': False},
                        'or': [
                            {'originalFileName': {'endsWith': '.jpg'}},
                            {'originalFileName': {'endsWith': '.jpeg'}},
                            {'originalFileName': {'endsWith': '.png'}},
                        ],
                    },
                }
            )
        ],
    )


def mock_original(
    mocked_responses: responses.RequestsMock,
    asset_id: str,
    content_type: str = 'image/jpeg',
) -> None:
    mocked_responses.get(
        f'{IMMICH_BASE_URL}/api/assets/{asset_id}/original',
        body=f'original of {asset_id}'.encode(),
        content_type=content_type,
    )


def assert_no_background(
    api: ImmichAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
) -> None:
    assert api.download_random_background(tmp_path) is None
    # No search is registered, but an unexpected request would still end up as
    # `None` via the error handling, so check that none was even attempted.
    assert not any(
        '/search/' in (call.request.url or '') for call in mocked_responses.calls
    )


def test_backgrounds_are_disabled_without_immich_section() -> None:
    # No responses mock is active, so any request would fail the test.
    api = ImmichAPI(make_config())
    assert api.download_random_background(pathlib.Path('unused')) is None


def test_backgrounds_are_disabled_without_backgrounds_album(
    immich_api: ImmichAPI,
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
) -> None:
    assert_no_background(immich_api, mocked_responses, tmp_path)


@pytest.mark.parametrize('missing', ['album.read', 'asset.read', 'asset.download'])
def test_backgrounds_are_skipped_without_permission(
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
    missing: str,
) -> None:
    # The albums are not registered: without permission they are not asked for.
    permissions = [
        'asset.upload',
        *(perm for perm in BACKGROUND_PERMISSIONS if perm != missing),
    ]
    with caplog.at_level(logging.WARNING):
        api = make_background_api(mocked_responses, permissions)
    assert_no_background(api, mocked_responses, tmp_path)
    assert f'background image download due to missing permissions: "{missing}"' in (
        caplog.text
    )


@pytest.mark.parametrize(('major', 'minor'), [(3, 1), (2, 9)])
def test_backgrounds_are_skipped_on_servers_without_search_filter(
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
    major: int,
    minor: int,
) -> None:
    # An older server would drop the unknown filter and search the whole library.
    with caplog.at_level(logging.WARNING):
        api = make_background_api(mocked_responses, server_version=(major, minor, 0))
    assert_no_background(api, mocked_responses, tmp_path)
    assert f'requires Immich 3.2 or later, but the server is {major}.{minor}.0' in (
        caplog.text
    )


def test_backgrounds_are_skipped_without_server_version(
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mocked_responses.get(f'{IMMICH_BASE_URL}/api/server/version', status=500)
    with caplog.at_level(logging.WARNING):
        api = make_background_api(mocked_responses, server_version=None)
    # An unknown version does not abort the connector, it only skips what needs one.
    assert_no_background(api, mocked_responses, tmp_path)
    assert 'Cannot determine the Immich version: 500 Server Error' in caplog.text
    assert 'Skipping background image download, the Immich version is unknown' in (
        caplog.text
    )


def test_immich_version_is_logged(
    mocked_responses: responses.RequestsMock, caplog: pytest.LogCaptureFixture
) -> None:
    mock_immich_server(mocked_responses, [], version=(3, 2, 1))
    with caplog.at_level(logging.INFO):
        connect_immich(make_config(immich={}))
    assert f'Immich at {IMMICH_BASE_URL} is version 3.2.1' in caplog.text


def test_immich_version_is_fetched_once(
    mocked_responses: responses.RequestsMock, tmp_path: pathlib.Path
) -> None:
    # A later server passes the version check as well.
    api = make_background_api(mocked_responses, server_version=(4, 0, 1))
    mock_random_search(mocked_responses, ['al1'], ['a1'])
    mock_original(mocked_responses, 'a1')
    assert api.download_random_background(tmp_path) == tmp_path / 'a1.jpg'
    versions = [
        call
        for call in mocked_responses.calls
        if (call.request.url or '').endswith('/api/server/version')
    ]
    assert len(versions) == 1


def test_backgrounds_are_skipped_without_the_album(
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # An album differing only in case does not count: names are compared exactly.
    with caplog.at_level(logging.WARNING):
        api = make_background_api(
            mocked_responses, albums=[{'id': 'al1', 'albumName': 'backgrounds'}]
        )
    assert_no_background(api, mocked_responses, tmp_path)
    assert 'Album "Backgrounds" not found' in caplog.text


def test_random_background_searches_the_album_and_downloads_originals(
    mocked_responses: responses.RequestsMock, tmp_path: pathlib.Path
) -> None:
    api = make_background_api(mocked_responses)
    # Registered twice, the responses are answered in order: the second search
    # stands for the new random batch once the first one is used up.
    mock_random_search(mocked_responses, ['al1'], ['a1', 'a2'])
    mock_random_search(mocked_responses, ['al1'], ['a3'])
    for asset_id in ('a1', 'a2', 'a3'):
        mock_original(mocked_responses, asset_id)
    images = [api.download_random_background(tmp_path) for _ in range(3)]
    # The server's random order is kept, and a batch is used up before the next.
    assert images == [tmp_path / 'a1.jpg', tmp_path / 'a2.jpg', tmp_path / 'a3.jpg']
    assert (tmp_path / 'a1.jpg').read_bytes() == b'original of a1'
    searches = [
        call
        for call in mocked_responses.calls
        if '/search/' in (call.request.url or '')
    ]
    assert len(searches) == 2  # once per batch, not per song
    assert all(
        call.request.headers['x-api-key'] == 'immich-test-token'
        for call in mocked_responses.calls
    )


def test_random_background_works_without_upload_permission(
    mocked_responses: responses.RequestsMock, tmp_path: pathlib.Path
) -> None:
    # A token that may only read is enough for the background download.
    api = make_background_api(mocked_responses, BACKGROUND_PERMISSIONS)
    mock_random_search(mocked_responses, ['al1'], ['a1'])
    mock_original(mocked_responses, 'a1')
    assert api.download_random_background(tmp_path) == tmp_path / 'a1.jpg'


def test_random_background_searches_all_albums_of_that_name(
    mocked_responses: responses.RequestsMock, tmp_path: pathlib.Path
) -> None:
    # E.g. an own album and one shared by another user under the same name.
    api = make_background_api(
        mocked_responses,
        albums=[*ALBUMS, {'id': 'al3', 'albumName': 'Backgrounds'}],
    )
    mock_random_search(mocked_responses, ['al1', 'al3'], ['a1'])
    mock_original(mocked_responses, 'a1')
    assert api.download_random_background(tmp_path) == tmp_path / 'a1.jpg'


def test_random_background_takes_the_extension_from_the_content_type(
    mocked_responses: responses.RequestsMock, tmp_path: pathlib.Path
) -> None:
    api = make_background_api(mocked_responses)
    mock_random_search(mocked_responses, ['al1'], ['a1'])
    mock_original(mocked_responses, 'a1', content_type='image/png')
    image = api.download_random_background(tmp_path / 'Backgrounds')
    assert image == tmp_path / 'Backgrounds' / 'a1.png'
    assert image is not None
    assert image.exists()


def test_random_background_from_an_album_without_images(
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = make_background_api(mocked_responses)
    mock_random_search(mocked_responses, ['al1'], [])
    with caplog.at_level(logging.WARNING):
        assert api.download_random_background(tmp_path) is None
        # Not searched again: the registered response is used up.
        assert api.download_random_background(tmp_path) is None
    assert 'No JPEG or PNG images in the backgrounds album' in caplog.text


def test_random_background_survives_a_failing_search(
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = make_background_api(mocked_responses)
    mocked_responses.post(f'{IMMICH_BASE_URL}/api/search/random', status=500)
    with caplog.at_level(logging.ERROR):
        assert api.download_random_background(tmp_path) is None
        # A failing server is not asked again for every further song.
        assert api.download_random_background(tmp_path) is None
    assert '500 Server Error' in caplog.text


def test_random_background_survives_a_failing_refetch(
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = make_background_api(mocked_responses)
    mock_random_search(mocked_responses, ['al1'], ['a1'])
    mocked_responses.post(f'{IMMICH_BASE_URL}/api/search/random', status=500)
    mock_original(mocked_responses, 'a1')
    with caplog.at_level(logging.ERROR):
        assert api.download_random_background(tmp_path) == tmp_path / 'a1.jpg'
        assert api.download_random_background(tmp_path) is None
        # The failing server is not asked again for every further song.
        assert api.download_random_background(tmp_path) is None
    assert '500 Server Error' in caplog.text
    searches = [
        call
        for call in mocked_responses.calls
        if '/search/' in (call.request.url or '')
    ]
    assert len(searches) == 2


def test_random_background_survives_a_failing_download(
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = make_background_api(mocked_responses)
    mock_random_search(mocked_responses, ['al1'], ['a1'])
    mocked_responses.get(f'{IMMICH_BASE_URL}/api/assets/a1/original', status=404)
    with caplog.at_level(logging.ERROR):
        assert api.download_random_background(tmp_path) is None
    assert '404' in caplog.text
    assert not list(tmp_path.iterdir())


FAILING_ANSWERS = [
    pytest.param({'status': 500}, id='server-error'),
    pytest.param(
        {'body': requests.exceptions.ConnectionError('connection reset')},
        id='connection-error',
    ),
    pytest.param({'json': [{'id': 't1'}]}, id='off-shape'),  # an entry without name
]


def make_api_with_both_features(
    mocked_responses: responses.RequestsMock,
    *,
    tags_answer: dict[str, typing.Any],
    albums_answer: dict[str, typing.Any],
) -> ImmichAPI:
    mock_immich_server(mocked_responses, [*UPLOAD_PERMISSIONS, *BACKGROUND_PERMISSIONS])
    mocked_responses.get(f'{IMMICH_BASE_URL}/api/tags', **tags_answer)
    mocked_responses.get(f'{IMMICH_BASE_URL}/api/albums', **albums_answer)
    return connect_immich(
        make_config(
            immich={'upload_tags': ['Upload'], 'backgrounds_album': 'Backgrounds'}
        )
    )


@pytest.mark.parametrize('answer', FAILING_ANSWERS)
def test_a_failing_tag_lookup_only_skips_the_media_upload(
    mocked_responses: responses.RequestsMock,
    caplog: pytest.LogCaptureFixture,
    answer: dict[str, typing.Any],
) -> None:
    with caplog.at_level(logging.WARNING):
        api = make_api_with_both_features(
            mocked_responses, tags_answer=answer, albums_answer={'json': ALBUMS}
        )
    assert not api.upload_enabled
    assert api.backgrounds_enabled
    assert 'Skipping media upload, cannot look up the upload tags' in caplog.text


@pytest.mark.parametrize('answer', FAILING_ANSWERS)
def test_a_failing_album_lookup_only_skips_the_backgrounds(
    mocked_responses: responses.RequestsMock,
    caplog: pytest.LogCaptureFixture,
    answer: dict[str, typing.Any],
) -> None:
    with caplog.at_level(logging.WARNING):
        api = make_api_with_both_features(
            mocked_responses,
            tags_answer={'json': [{'id': 't1', 'name': 'Upload'}]},
            albums_answer=answer,
        )
    assert api.upload_enabled
    assert not api.backgrounds_enabled
    assert 'Skipping background image download, cannot look up the albums' in (
        caplog.text
    )


@pytest.mark.parametrize('answer', FAILING_ANSWERS)
def test_a_failing_tag_creation_leaves_out_only_that_tag(
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
    answer: dict[str, typing.Any],
) -> None:
    mocked_responses.post(f'{IMMICH_BASE_URL}/api/tags', **answer)
    with caplog.at_level(logging.WARNING):
        api = make_immich_api(
            mocked_responses,
            [*UPLOAD_PERMISSIONS, 'tag.create'],
            tags=['Service', 'New'],
            known_tags=[{'id': 't1', 'name': 'Service'}],
        )
    assert 'Failed to create tag "New" in Immich' in caplog.text
    media_file = make_media_file(tmp_path)
    mock_upload(mocked_responses, media_file)
    api.upload_media_file(str(media_file))
    body = mocked_responses.calls[-1].request.body
    assert body is not None
    assert json.loads(typing.cast('bytes', body))['tagIds'] == ['t1']
