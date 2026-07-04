# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import typing

import requests

if typing.TYPE_CHECKING:
    import logging

    from churchsong.utils import JsonObject

type DataType = typing.Mapping[str, typing.Any]

type ParamsType = typing.Mapping[
    str, str | int | float | bool | list[str] | list[int] | None
]

type FilesType = typing.Mapping[
    str,
    typing.IO[bytes]
    | tuple[str, typing.IO[bytes]]
    | tuple[str, typing.IO[bytes], str]
    | tuple[str, typing.IO[bytes], str, typing.Mapping[str, str]],
]


class BaseAPI:
    _log: logging.Logger
    _base_url: str
    _headers: dict[str, str]

    def _request(  # noqa: PLR0913
        self,
        method: str,
        url: str,
        params: ParamsType | None = None,
        *,
        data: DataType | None = None,
        json: JsonObject | None = None,
        files: FilesType | None = None,
        stream: bool = False,
    ) -> requests.Response:
        self._log.debug(
            'Request %s %s%s with params=%s', method, self._base_url, url, params
        )
        r = requests.request(
            method,
            f'{self._base_url}{url}',
            params=params,
            data=data,
            json=json,
            headers=self._headers,
            files=files,
            stream=stream,
        )
        self._log.debug('Response is %s %s', r.status_code, r.reason)
        r.raise_for_status()
        return r

    def _get(  # noqa: PLR0913
        self,
        url: str,
        params: ParamsType | None = None,
        *,
        data: DataType | None = None,
        json: JsonObject | None = None,
        files: FilesType | None = None,
        stream: bool = False,
    ) -> requests.Response:
        return self._request(
            'GET', url, params, data=data, json=json, files=files, stream=stream
        )

    def _put(  # noqa: PLR0913
        self,
        url: str,
        params: ParamsType | None = None,
        *,
        data: DataType | None = None,
        json: JsonObject | None = None,
        files: FilesType | None = None,
        stream: bool = False,
    ) -> requests.Response:
        return self._request(
            'PUT', url, params, data=data, json=json, files=files, stream=stream
        )

    def _post(  # noqa: PLR0913
        self,
        url: str,
        params: ParamsType | None = None,
        *,
        data: DataType | None = None,
        json: JsonObject | None = None,
        files: FilesType | None = None,
        stream: bool = False,
    ) -> requests.Response:
        return self._request(
            'POST', url, params, data=data, json=json, files=files, stream=stream
        )

    def _delete(  # noqa: PLR0913
        self,
        url: str,
        params: ParamsType | None = None,
        *,
        data: DataType | None = None,
        json: JsonObject | None = None,
        files: FilesType | None = None,
        stream: bool = False,
    ) -> requests.Response:
        return self._request(
            'DELETE', url, params, data=data, json=json, files=files, stream=stream
        )
