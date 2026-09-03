# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import atexit
import http.cookiejar
import typing
import urllib.parse

import requests
import requests.adapters
import urllib3.util

if typing.TYPE_CHECKING:
    import logging
    import types

    from churchsong.utils import JsonObject

# Seconds to wait for the server to send its response.
REQUEST_TIMEOUT = 30

# Bytes to read at a time from a streamed response body.
DOWNLOAD_CHUNK_SIZE = 64 * 1024


class LoggingRetry(urllib3.util.Retry):
    """A `Retry` child class that logs every wait."""

    def __init__(self, log: logging.Logger, **kwargs: typing.Any) -> None:  # noqa: ANN401 (`Retry.new()` passes its parameters through untyped)
        super().__init__(**kwargs)
        self._log = log

    @typing.override
    def new(self, **kw: typing.Any) -> typing.Self:
        # `Retry` hands out a new instance per attempt, so carry the logger along.
        return super().new(log=self._log, **kw)

    @typing.override
    def increment(
        self,
        method: str | None = None,
        url: str | None = None,
        response: urllib3.BaseHTTPResponse | None = None,
        error: Exception | None = None,
        _pool: typing.Any = None,
        _stacktrace: types.TracebackType | None = None,
    ) -> typing.Self:
        retry = super().increment(method, url, response, error, _pool, _stacktrace)
        # urllib3 calls this right before it goes to sleep, which makes it the only
        # place that can report a wait while it is still going on: an unannounced
        # pause of a minute is indistinguishable from a hanging program. Note that
        # an exhausted budget raises out of the call above instead - the caller then
        # sees the failure itself, so it needs no announcement from here.
        wait = retry.get_retry_after(response) if response else None
        if wait is None:  # `Retry.sleep()` prefers `Retry-After` over its backoff.
            wait = retry.get_backoff_time()
        self._log.warning(
            'Waiting %.0fs to retry %s %s after %s (%s attempt(s) left)',
            wait,
            method,
            url,
            f'status {response.status}' if response else error,
            retry.total,
        )
        return retry


def retry_policy(log: logging.Logger) -> LoggingRetry:
    """The retry policy every API of this tool uses.

    With `backoff_factor=2` the five retries are spread over about a minute.
    The `Retry-After` header of the server - if present - takes precedence.
    """
    return LoggingRetry(
        log,
        total=5,
        backoff_factor=2,
        status_forcelist=frozenset({429, 500, 502, 503, 504}),
        # Only retry read-only request and not modifying ones like (POST/PUT/DELETE).
        allowed_methods=frozenset({'GET', 'HEAD'}),
        # Hand the last response back instead of raising `RetryError`, so an
        # exhausted retry budget reaches the caller as the `HTTPError` of
        # `raise_for_status()` that it would have seen without any retrying at all.
        raise_on_status=False,
        respect_retry_after_header=True,
    )


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
    _base_url: str
    _headers: dict[str, str]

    def __init__(self, log: logging.Logger, *, persist_cookies: bool = True) -> None:
        self._log = log
        # Reuse one connection for all requests of an API instead of paying for a
        # TCP and TLS handshake per request. The authentication headers are
        # deliberately *not* put onto the session: per-request `headers` are merged
        # into the session headers instead of replacing them, so a `headers=None`
        # (as used for downloads from a foreign host) could not drop them again.
        self._session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(max_retries=retry_policy(log))
        self._session.mount('http://', adapter)
        self._session.mount('https://', adapter)
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
            timeout=REQUEST_TIMEOUT,
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
