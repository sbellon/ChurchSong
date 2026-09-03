# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import json
import logging
import typing

import pytest
import requests

from churchsong.immich import ImmichAPI
from churchsong.utils import CliError
from tests.conftest import IMMICH_BASE_URL, make_config

if typing.TYPE_CHECKING:
    import pathlib

    import responses


@pytest.fixture
def immich_api(mocked_responses: responses.RequestsMock) -> ImmichAPI:
    mocked_responses.get(
        f'{IMMICH_BASE_URL}/api/api-keys/me',
        json={'permissions': ['asset.upload']},
    )
    return ImmichAPI(make_config(immich={}))


def test_init_without_immich_section_disables_upload_without_http() -> None:
    # No responses mock is active: any HTTP request would hit the network
    # and fail, so no thrown exception also proves that no request is made.
    api = ImmichAPI(make_config())
    api.upload_media_file('IMG_1234.jpg')


def test_init_rejects_token_without_upload_permission(
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(
        f'{IMMICH_BASE_URL}/api/api-keys/me',
        json={'permissions': ['asset.read']},
    )
    with pytest.raises(CliError, match='Missing required permissions'):
        ImmichAPI(make_config(immich={}))


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
    media_file = tmp_path / 'IMG_1234.jpg'
    media_file.write_bytes(b'not really a jpeg')
    mocked_responses.post(
        f'{IMMICH_BASE_URL}/api/assets/bulk-upload-check',
        json={'results': [{'action': 'accept', 'id': media_file.name}]},
    )
    mocked_responses.post(
        f'{IMMICH_BASE_URL}/api/assets',
        json={'id': 'asset-1'},
    )
    immich_api.upload_media_file(str(media_file))
    upload_request = mocked_responses.calls[-1].request
    assert upload_request.headers['x-api-key'] == 'immich-test-token'
    body = upload_request.body
    assert body is not None
    assert b'IMG_1234.jpg' in bytes(typing.cast('bytes', body))


def make_immich_api(
    mocked_responses: responses.RequestsMock,
    permissions: list[str],
    *,
    tags: list[str] | None = None,
    known_tags: list[dict[str, str]] | None = None,
) -> ImmichAPI:
    mocked_responses.get(
        f'{IMMICH_BASE_URL}/api/api-keys/me', json={'permissions': permissions}
    )
    if known_tags is not None:
        mocked_responses.get(f'{IMMICH_BASE_URL}/api/tags', json=known_tags)
    return ImmichAPI(make_config(immich={'tags': tags or []}))


def make_media_file(tmp_path: pathlib.Path) -> pathlib.Path:
    media_file = tmp_path / 'IMG_1234.jpg'
    media_file.write_bytes(b'not really a jpeg')
    return media_file


def test_init_reports_an_unreachable_immich_instance(
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(
        f'{IMMICH_BASE_URL}/api/api-keys/me',
        body=requests.exceptions.ConnectionError('no route to host'),
    )
    with pytest.raises(CliError, match='configure the URL'):
        ImmichAPI(make_config(immich={}))


def test_init_reports_a_wrong_immich_token(
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(f'{IMMICH_BASE_URL}/api/api-keys/me', status=401)
    with pytest.raises(CliError, match='Immich API token'):
        ImmichAPI(make_config(immich={}))


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


def test_tag_creation_is_skipped_without_permission(
    mocked_responses: responses.RequestsMock,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # No POST /api/tags is registered: creating the unknown tag would fail.
    with caplog.at_level(logging.WARNING):
        api = make_immich_api(
            mocked_responses,
            ['asset.upload', 'tag.read', 'tag.asset'],
            tags=['New'],
            known_tags=[],
        )
    assert 'tag creation' in caplog.text
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
    assert json.loads(typing.cast('bytes', body))['tagIds'] == []


def test_tag_enumeration_is_skipped_without_permission(
    mocked_responses: responses.RequestsMock, caplog: pytest.LogCaptureFixture
) -> None:
    # No GET /api/tags is registered: enumerating the tags would fail.
    with caplog.at_level(logging.WARNING):
        make_immich_api(mocked_responses, ['asset.upload'], tags=['Service'])
    assert 'tag enumeration' in caplog.text


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
    mocked_responses.get(
        f'{IMMICH_BASE_URL}/api/api-keys/me', json={'permissions': ['asset.upload']}
    )
    api = ImmichAPI(make_config(immich={'exclude_globbings': ['*_edited.jpg']}))
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
