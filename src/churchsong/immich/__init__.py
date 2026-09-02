# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import datetime
import enum
import hashlib
import mimetypes
import pathlib
import sys
import typing

import pydantic
import requests
import requests.exceptions

from churchsong.utils import CliError, JsonObject, JsonValue
from churchsong.utils.http import BaseAPI

if typing.TYPE_CHECKING:
    from churchsong.configuration import Configuration


class BaseModel(pydantic.BaseModel):
    pass


class Permissions(BaseModel):
    permissions: list[str]


class AssetUploadAction(enum.StrEnum):
    ACCEPT = 'accept'
    REJECT = 'reject'


class AssetRejectReason(enum.StrEnum):
    DUPLICATE = 'duplicate'
    UNSUPPORTED_FORMAT = 'unsupported-format'


class TagResponse(BaseModel):
    id: str
    name: str


class TagResponseResults(pydantic.RootModel[list[TagResponse]]):
    pass


class AssetMediaResponse(BaseModel):
    id: str


class AssetBulkUploadCheckResult(BaseModel):
    action: AssetUploadAction
    asset_id: str | None = pydantic.Field(default=None, alias='assetId')
    id: str
    is_trashed: bool = pydantic.Field(default=False, alias='isTrashed')
    reason: AssetRejectReason | None = None


class AssetBulkUploadCheckResults(BaseModel):
    results: list[AssetBulkUploadCheckResult]


class ImmichAPI(BaseAPI):
    def __init__(self, config: Configuration) -> None:
        super().__init__(config.log)
        if config.immich:
            self._enable_immich = True
            self._base_url = config.immich.base_url
            self._headers = {
                'accept': 'application/json',
                'x-api-key': config.immich.login_token,
            }
            self._include_globbings = config.immich.include_globbings
            self._exclude_globbings = config.immich.exclude_globbings

            self._permissions = self._fetch_permissions()
            # Assert permissions that are required for basic functionality of the app.
            # Additional permissions are queried on-demand and other functionality
            # may be disabled if permissions are missing (like nicknames or appointment
            # slides).
            self._assert_permissions('asset.upload')

            self._tag_ids = self._get_tag_ids(config.immich.tags)
        else:
            self._enable_immich = False

    def _fetch_permissions(self) -> Permissions:
        try:
            r = self._get('/api/api-keys/me')
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.MissingSchema,
        ) as e:
            self._log.error(e)
            msg = f'{e}\n\nDid you configure the URL of your Immich instance correctly?'
            raise CliError(msg) from None
        except requests.exceptions.HTTPError as e:
            self._log.error(e)
            msg = f'{e}'
            if e.response is not None and e.response.status_code in (
                requests.codes['forbidden'],
                requests.codes['unauthorized'],
            ):
                msg += '\n\nDid you configure your Immich API token correctly?'
            raise CliError(msg) from None
        return Permissions(**r.json())

    def _get_missing_permissions(self, *required_perms: str) -> list[str]:
        return [
            perm for perm in required_perms if perm not in self._permissions.permissions
        ]

    def _assert_permissions(self, *required_perms: str) -> None:
        if missing_perms := self._get_missing_permissions(*required_perms):
            msg = 'Missing required permissions for Immich token user: {}'.format(
                ', '.join(f'"{perm}"' for perm in missing_perms)
            )
            self._log.error(msg)
            raise CliError(msg) from None

    def has_permissions(self, required_perms: list[str], log_reason: str = '') -> bool:
        missing_perms = self._get_missing_permissions(*required_perms)
        if missing_perms and log_reason:
            self._log.warning(
                f'Skipping {log_reason} due to missing permissions: {{}}'.format(
                    ', '.join(f'"{perm}"' for perm in missing_perms)
                )
            )
        return not missing_perms

    def _create_tag(self, tagname: str) -> str | None:
        if not self.has_permissions(['tag.create'], 'tag creation'):
            return None
        r = self._post('/api/tags', json={'name': tagname})
        return TagResponse(**r.json()).id

    def _get_tag_ids(self, tagnames: list[str]) -> list[JsonValue]:
        if not self.has_permissions(['tag.read'], 'tag enumeration'):
            return []
        r = self._get('/api/tags')
        tag2id = {
            tag.name: tag.id for tag in TagResponseResults.model_validate(r.json()).root
        }
        return [
            tag_id
            for tagname in tagnames
            if (
                (tag_id := tag2id.get(tagname)) is not None
                or (tag_id := self._create_tag(tagname)) is not None
            )
        ]

    def _tag_asset(self, asset_id: str) -> None:
        if not self.has_permissions(['tag.asset'], 'asset tagging'):
            return
        payload: JsonObject = {
            'assetIds': [asset_id],
            'tagIds': self._tag_ids,
        }
        self._put('/api/tags/assets', json=payload)

    def _get_sha1_checksum(self, filename: pathlib.Path) -> str:
        sha1 = hashlib.sha1(usedforsecurity=False)
        with filename.open('rb') as fd:
            while chunk := fd.read(65536):
                sha1.update(chunk)
        return sha1.hexdigest()

    def _media_file_exists_or_rejected(self, filename: pathlib.Path) -> bool:
        payload: JsonObject = {
            'assets': [
                {
                    'id': filename.name,
                    'checksum': self._get_sha1_checksum(filename),
                }
            ],
        }
        r = self._post('/api/assets/bulk-upload-check', json=payload)
        result = AssetBulkUploadCheckResults(**r.json())
        if result.results[0].action == AssetUploadAction.REJECT:
            fn = filename.name
            match result.results[0].reason:
                case AssetRejectReason.DUPLICATE:
                    self._log.info(f'Skipping upload of existing file "{fn}" to Immich')
                case AssetRejectReason.UNSUPPORTED_FORMAT:
                    self._log.info(
                        f'Skipping upload of unsupported file "{fn}" to Immich'
                    )
                case _:
                    self._log.info(f'Skipping upload of file "{fn}" to Immich')
            return True
        return False

    def _upload_media_file(self, filename: pathlib.Path) -> str | None:
        mime_type, _ = mimetypes.guess_file_type(filename)
        stat = filename.stat()
        data = {
            'fileCreatedAt': datetime.datetime.fromtimestamp(
                stat.st_birthtime if sys.platform == 'win32' else stat.st_ctime,
                datetime.UTC,
            ).isoformat(),
            'fileModifiedAt': datetime.datetime.fromtimestamp(
                stat.st_mtime,
                datetime.UTC,
            ).isoformat(),
        }
        with filename.open('rb') as fd:
            files = {'assetData': (filename.name, fd, mime_type or 'image/jpeg')}
            r = self._post('/api/assets', data=data, files=files)
            return AssetMediaResponse(**r.json()).id

    def upload_media_file(self, filename: str) -> None:
        if (
            self._enable_immich
            and any(incl.match(filename) for incl in self._include_globbings)
            and not any(excl.match(filename) for excl in self._exclude_globbings)
        ):
            try:
                fn = pathlib.Path(filename)
                if not self._media_file_exists_or_rejected(fn):
                    self._log.info(f'Uploading new media file "{fn.name}" to Immich')
                    if asset_id := self._upload_media_file(fn):
                        self._tag_asset(asset_id)
            except (
                requests.RequestException,
                pydantic.ValidationError,
                IndexError,
            ) as e:
                # Keep flying as the Immich upload should not crash an event.
                self._log.error(e)
