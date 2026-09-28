# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import datetime
import enum
import hashlib
import logging
import mimetypes
import pathlib
import sys
import typing

import pydantic
import requests

from churchsong.utils.file import atomic_replace
from churchsong.utils.http import BaseAPI

if typing.TYPE_CHECKING:
    from churchsong.configuration import Configuration
    from churchsong.utils import JsonObject


logger = logging.getLogger(__name__)


class BaseModel(pydantic.BaseModel):
    pass


class Permissions(BaseModel):
    permissions: list[str]

    def get_permission(self, perm: str) -> bool:
        return perm in self.permissions


# Immich identifies its objects (assets, tags, albums, ...) by UUIDs in string form.
type UUID = str


class AssetUploadAction(enum.StrEnum):
    ACCEPT = 'accept'
    REJECT = 'reject'


class AssetRejectReason(enum.StrEnum):
    DUPLICATE = 'duplicate'
    UNSUPPORTED_FORMAT = 'unsupported-format'


class TagResponse(BaseModel):
    id: UUID
    name: str


class TagResponseResults(pydantic.RootModel[list[TagResponse]]):
    pass


class AlbumResponse(BaseModel):
    id: UUID
    album_name: str = pydantic.Field(alias='albumName')


class AlbumResponseResults(pydantic.RootModel[list[AlbumResponse]]):
    pass


class AssetResponse(BaseModel):
    id: UUID


class AssetResponseResults(pydantic.RootModel[list[AssetResponse]]):
    pass


class ServerVersionResponse(BaseModel):
    major: int
    minor: int
    patch: int

    def get_version(self) -> str:
        return f'{self.major}.{self.minor}.{self.patch}'


class AssetMediaResponse(BaseModel):
    id: UUID


class AssetBulkUploadCheckResult(BaseModel):
    action: AssetUploadAction
    asset_id: UUID | None = pydantic.Field(default=None, alias='assetId')
    id: str  # not a UUID: the ID the request gave the file, i.e. its name
    is_trashed: bool = pydantic.Field(default=False, alias='isTrashed')
    reason: AssetRejectReason | None = None


class AssetBulkUploadCheckResults(BaseModel):
    results: list[AssetBulkUploadCheckResult]


class ImmichAPI(BaseAPI):
    # First server version with the structured `filter` of the search endpoints. Older
    # servers silently drop fields they do not know, and would thus answer a filtered
    # search with random assets of the whole library.
    SEARCH_FILTER_VERSION = '3.2'

    def __init__(self, config: Configuration) -> None:
        """Set up the connector without contacting Immich yet, so this cannot fail.

        Both features start switched off, which is a valid state to use the instance
        in: `connect()` switches on what is configured and usable.
        """
        super().__init__(logger, 'Immich')
        if config.immich:
            self._base_url = config.immich.base_url
            self._headers = {
                'accept': 'application/json',
                'x-api-key': config.immich.login_token,
            }
            self._include_globbings = config.immich.include_globbings
            self._exclude_globbings = config.immich.exclude_globbings
            self._upload_tags = config.immich.upload_tags
            self._backgrounds_album = config.immich.backgrounds_album
        else:
            self._base_url = ''
            self._headers = {}
            self._include_globbings = []
            self._exclude_globbings = []
            self._upload_tags = []
            self._backgrounds_album = None

        # Media upload and background download are independent optional features,
        # switched on by `connect()` with the IDs they need.
        self._upload_tag_ids: list[UUID] = []
        self._backgrounds_album_ids: list[UUID] = []

        # Candidates for background images, fetched on first demand.
        self._background_candidates: list[UUID] | None = None
        self._background_index = 0

    def connect(self) -> None:
        """Contact the configured Immich instance and set up the usable features.

        Raises a `CliError` if URL or token are wrong, leaving both features off. A
        feature that is not configured or not permitted stays off, and a failure
        while setting one up only switches off that one.
        """
        if not self._base_url:
            return
        self._permissions = self._fetch_required(Permissions, '/api/api-keys/me')
        self._version = self._fetch_version(
            ServerVersionResponse, '/api/server/version'
        )
        if self._upload_tags and self.has_permissions(
            ['asset.upload', 'tag.read', 'tag.asset'], 'media upload'
        ):
            self._upload_tag_ids = self._get_tag_ids(self._upload_tags)
        if (
            self._backgrounds_album
            and self.has_permissions(
                ['album.read', 'asset.read', 'asset.download'],
                'background image download',
            )
            and self.has_version(
                self.SEARCH_FILTER_VERSION, 'background image download'
            )
        ):
            self._backgrounds_album_ids = self._get_album_ids(self._backgrounds_album)

    @property
    def upload_enabled(self) -> bool:
        """Whether media files are uploaded: only with a usable upload tag."""
        return bool(self._upload_tag_ids)

    @property
    def backgrounds_enabled(self) -> bool:
        """Whether background images can come from a usable backgrounds album."""
        return bool(self._backgrounds_album_ids)

    def _create_tag(self, tagname: str) -> UUID | None:
        if not self.has_permissions(['tag.create'], 'tag creation'):
            return None
        try:
            r = self._post('/api/tags', json={'name': tagname})
            # Not `_parse()`: a tag that cannot be created is left out, as is one
            # without the permission to create it.
            return self._validate(TagResponse, r).id
        except (requests.RequestException, pydantic.ValidationError) as e:
            logger.warning('Failed to create tag "%s" in Immich: %s', tagname, e)
            return None

    def _get_tag_ids(self, tagnames: list[str]) -> list[UUID]:
        try:
            r = self._get('/api/tags')
            # Not `_parse()`: a failure only costs the media upload, not the connector.
            tags = self._validate(TagResponseResults, r).root
        except (requests.RequestException, pydantic.ValidationError) as e:
            logger.warning(
                'Skipping media upload, cannot look up the upload tags in Immich: %s', e
            )
            return []
        tag2id = {tag.name: tag.id for tag in tags}
        tag_ids = [
            tag_id
            for tagname in tagnames
            if (
                (tag_id := tag2id.get(tagname)) is not None
                or (tag_id := self._create_tag(tagname)) is not None
            )
        ]
        if not tag_ids:
            logger.warning(
                'Skipping media upload, none of the upload tags exists in Immich'
            )
        return tag_ids

    def _get_album_ids(self, album_name: str) -> list[UUID]:
        # Match the name here instead of passing it as a query parameter, which a
        # server not knowing it would silently drop and answer with all albums. All
        # albums of that name count, e.g. an own and a shared one.
        try:
            r = self._get('/api/albums')
            # Not `_parse()`: a failure only costs the backgrounds, not the connector.
            albums = self._validate(AlbumResponseResults, r).root
        except (requests.RequestException, pydantic.ValidationError) as e:
            logger.warning(
                'Skipping background image download, cannot look up the albums in '
                'Immich: %s',
                e,
            )
            return []
        album_ids = [album.id for album in albums if album.album_name == album_name]
        if not album_ids:
            logger.warning('Album "%s" not found in Immich', album_name)
        return album_ids

    def _tag_asset(self, asset_id: UUID) -> None:
        payload: JsonObject = {
            'assetIds': [asset_id],
            'tagIds': [*self._upload_tag_ids],
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
        # Not `_parse()`: `upload_media_file()` catches the error to skip one file.
        r = self._post('/api/assets/bulk-upload-check', json=payload)
        result = self._validate(AssetBulkUploadCheckResults, r)
        if result.results[0].action == AssetUploadAction.REJECT:
            fn = filename.name
            match result.results[0].reason:
                case AssetRejectReason.DUPLICATE:
                    logger.info('Skipping upload of existing file "%s" to Immich', fn)
                case AssetRejectReason.UNSUPPORTED_FORMAT:
                    logger.info(
                        'Skipping upload of unsupported file "%s" to Immich', fn
                    )
                case _:
                    logger.info('Skipping upload of file "%s" to Immich', fn)
            return True
        return False

    def _upload_media_file(self, filename: pathlib.Path) -> UUID | None:
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
            # Not `_parse()`, see `_media_file_exists_or_rejected()`.
            r = self._post('/api/assets', data=data, files=files)
            return self._validate(AssetMediaResponse, r).id

    def upload_media_file(self, filename: str) -> None:
        if (
            self.upload_enabled
            and any(incl.match(filename) for incl in self._include_globbings)
            and not any(excl.match(filename) for excl in self._exclude_globbings)
        ):
            try:
                fn = pathlib.Path(filename)
                if not self._media_file_exists_or_rejected(fn):
                    logger.info('Uploading new media file "%s" to Immich', fn.name)
                    if asset_id := self._upload_media_file(fn):
                        self._tag_asset(asset_id)
            except (
                requests.RequestException,
                pydantic.ValidationError,
                IndexError,
                OSError,
            ) as e:
                # Keep flying as the Immich upload should not crash an event.
                logger.error('Failed to upload "%s" to Immich: %s', filename, e)

    def _fetch_background_candidates(self) -> list[UUID]:
        # Use the Immich 3.2 API default `size` of 250 random image ids being returned.
        payload: JsonObject = {
            'filter': {
                'type': {'eq': 'IMAGE'},
                'albumIds': {'any': [*self._backgrounds_album_ids]},
                # Unlike the deprecated flat fields, the filter includes the trash.
                'trashedAt': {'eq': None},
                'isOffline': {'eq': False},
                'or': [
                    {'originalFileName': {'endsWith': '.jpg'}},
                    {'originalFileName': {'endsWith': '.jpeg'}},
                    {'originalFileName': {'endsWith': '.png'}},
                ],
            },
        }
        r = self._post('/api/search/random', json=payload)
        candidates = [
            asset.id for asset in self._validate(AssetResponseResults, r).root
        ]
        if not candidates:
            logger.warning('No JPEG or PNG images in the backgrounds album in Immich')
        return candidates

    def _next_background_candidate(self) -> UUID | None:
        # The server returns the candidates in random order already. Handing them out
        # in that order gives the songs of one event distinct backgrounds as long as
        # there are enough; once all are used, a new random batch is fetched. A batch
        # without candidates is not refetched for every further song.
        if self._background_candidates is None or (
            self._background_candidates
            and self._background_index >= len(self._background_candidates)
        ):
            # Settle for no candidates first: if the search fails, the next song must
            # not ask a failing server again.
            self._background_candidates = []
            self._background_index = 0
            self._background_candidates = self._fetch_background_candidates()
        if not self._background_candidates:
            return None
        candidate = self._background_candidates[self._background_index]
        self._background_index += 1
        return candidate

    def _download_original(
        self, asset_id: UUID, output_dir: pathlib.Path
    ) -> pathlib.Path:
        r = self._get(f'/api/assets/{asset_id}/original')
        mime_type = r.headers.get('Content-Type', '').partition(';')[0].strip()
        suffix = mimetypes.guess_extension(mime_type) if mime_type else None
        filename = output_dir / f'{asset_id}{suffix or ".jpg"}'
        with atomic_replace(filename) as tmp_file:
            tmp_file.write_bytes(r.content)
        return filename

    def download_random_background(
        self, output_dir: pathlib.Path
    ) -> pathlib.Path | None:
        """Download a random JPEG or PNG image of the backgrounds album.

        Returns `None` if the backgrounds album is not usable, holds no image or the
        download fails - a missing background must not cost an event its schedule.
        """
        if not self.backgrounds_enabled:
            return None
        try:
            if (asset_id := self._next_background_candidate()) is None:
                return None
            logger.info('Downloading background image "%s" from Immich', asset_id)
            return self._download_original(asset_id, output_dir)
        except (requests.RequestException, pydantic.ValidationError, OSError) as e:
            logger.error('Failed to download background image from Immich: %s', e)
            return None
