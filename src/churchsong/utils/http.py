# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import atexit
import http.cookiejar
import typing
import urllib.parse

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

    def __init__(self, *, persist_cookies: bool = True) -> None:
        # Reuse one connection for all requests of an API instead of paying for a
        # TCP and TLS handshake per request. The authentication headers are
        # deliberately *not* put onto the session: per-request `headers` are merged
        # into the session headers instead of replacing them, so a `headers=None`
        # (as used for downloads from a foreign host) could not drop them again.
        self._session = requests.Session()
        if not persist_cookies:
            # Services that authenticate per request via `self._headers` can pass
            # `persist_cookies=False` if carrying a server-issued cookie over into
            # the next request would change how that request is authenticated. An
            # empty `allowed_domains` blocks cookies from being stored *and* from
            # being sent; cookies within a single redirect chain are unaffected,
            # because requests resolves redirects through the prepared request's
            # own jar.
            self._session.cookies.set_policy(
                http.cookiejar.DefaultCookiePolicy(allowed_domains=[])
            )
        atexit.register(self._session.close)

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
        r = self._session.request(
            method,
            f'{self._base_url}{url}',
            params=params,
            data=data,
            json=json,
            headers=self._headers,
            files=files,
            stream=stream,
            timeout=30,
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


def is_same_host(url1: str, url2: str) -> bool:
    return urllib.parse.urlsplit(url1)[:2] == urllib.parse.urlsplit(url2)[:2]
