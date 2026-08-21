# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import typing

import pytest

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
    return ImmichAPI(make_config(with_immich=True))


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
        ImmichAPI(make_config(with_immich=True))


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
