# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import logging
import typing

import pytest
import requests

from churchsong.utils import (
    JsonObject,
    expand_envvars,
    flattened_split,
    recursive_expand_envvars,
)
from churchsong.utils.http import BaseAPI, is_same_host

if typing.TYPE_CHECKING:
    import responses


def test_expand_envvars_replaces_known_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('VARIABLE', 'value')
    assert expand_envvars('pre ${VARIABLE} post') == 'pre value post'


def test_expand_envvars_keeps_unknown_variable_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('VARIABLE', raising=False)
    assert expand_envvars('${VARIABLE}') == '${VARIABLE}'


def test_recursive_expand_envvars_walks_nested_structures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('VARIABLE', 'value')
    data: JsonObject = {
        'plain': '${VARIABLE}',
        'nested': {'list': ['${VARIABLE}', 42, None, True]},
    }
    assert recursive_expand_envvars(data) == {
        'plain': 'value',
        'nested': {'list': ['value', 42, None, True]},
    }


def test_flattened_split() -> None:
    assert flattened_split(['a,b', 'c', 'd,e']) == ['a', 'b', 'c', 'd', 'e']


def test_is_same_host() -> None:
    assert is_same_host('https://host.test/a/b', 'https://host.test/c')
    assert not is_same_host('https://host.test/a', 'https://other.test/a')
    assert not is_same_host('http://host.test/a', 'https://host.test/a')


class FakeAPI(BaseAPI):
    _base_url = 'https://host.test'
    _headers: dict[str, str] = {}  # noqa: RUF012 (only ever read, never mutated)

    def __init__(self, *, persist_cookies: bool = True) -> None:
        super().__init__(logging.getLogger('test'), persist_cookies=persist_cookies)


@pytest.mark.parametrize('persist_cookies', [True, False])
def test_persist_cookies_controls_cookie_reuse(
    mocked_responses: responses.RequestsMock,
    persist_cookies: bool,
) -> None:
    mocked_responses.get(
        'https://host.test/first',
        json={},
        headers={'Set-Cookie': 'SESSION=secret; path=/'},
    )
    mocked_responses.post('https://host.test/second', json={})

    api = FakeAPI(persist_cookies=persist_cookies)
    api._get('/first')  # noqa: SLF001 # pyright: ignore[reportPrivateUsage]
    api._post('/second')  # noqa: SLF001 # pyright: ignore[reportPrivateUsage]

    sent_cookie = 'Cookie' in mocked_responses.calls[1].request.headers
    assert bool(len(api._session.cookies)) is persist_cookies  # noqa: SLF001 # pyright: ignore[reportPrivateUsage]
    assert sent_cookie is persist_cookies


def test_persist_cookies_defaults_to_standard_behaviour(
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(
        'https://host.test/first',
        json={},
        headers={'Set-Cookie': 'SESSION=secret; path=/'},
    )
    api = FakeAPI()
    api._get('/first')  # noqa: SLF001 # pyright: ignore[reportPrivateUsage]

    assert len(api._session.cookies) == 1  # noqa: SLF001 # pyright: ignore[reportPrivateUsage]


def test_get_is_retried_after_a_rate_limit_response(
    mocked_responses: responses.RequestsMock, caplog: pytest.LogCaptureFixture
) -> None:
    # ChurchTools throttles the paging through its song database with 429.
    mocked_responses.get(
        'https://host.test/songs', status=429, headers={'Retry-After': '7'}
    )
    mocked_responses.get('https://host.test/songs', json={'data': []})

    api = FakeAPI()
    with caplog.at_level(logging.WARNING):
        r = api._get('/songs')  # noqa: SLF001 # pyright: ignore[reportPrivateUsage]

    assert r.json() == {'data': []}
    assert len(mocked_responses.calls) == 2
    # The wait is announced before it is sat out, and follows the `Retry-After`
    # of the server rather than the backoff, so a pause is never a silent one.
    assert 'Waiting 7s to retry GET' in caplog.text
    assert 'after status 429 (4 attempt(s) left)' in caplog.text


def test_exhausted_retries_raise_the_plain_http_error(
    mocked_responses: responses.RequestsMock, caplog: pytest.LogCaptureFixture
) -> None:
    # `raise_on_status=False` keeps the error a caller has to handle the same as it
    # was before there were any retries - a `RetryError` would slip through every
    # `except requests.exceptions.HTTPError`.
    mocked_responses.get('https://host.test/songs', status=429)

    api = FakeAPI()
    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(requests.exceptions.HTTPError) as excinfo,
    ):
        api._get('/songs')  # noqa: SLF001 # pyright: ignore[reportPrivateUsage]

    assert excinfo.value.response is not None
    assert excinfo.value.response.status_code == 429
    assert len(mocked_responses.calls) == 6  # the request plus its five retries
    # Every single wait is logged, which also proves that `Retry.new()` carries
    # the logger over into the retry object of the next attempt.
    assert caplog.text.count('Waiting') == 5


def test_post_is_not_retried(mocked_responses: responses.RequestsMock) -> None:
    # Repeating an upload could duplicate data, so only GET may be retried.
    mocked_responses.post('https://host.test/files', status=429)

    api = FakeAPI()
    with pytest.raises(requests.exceptions.HTTPError):
        api._post('/files')  # noqa: SLF001 # pyright: ignore[reportPrivateUsage]

    assert len(mocked_responses.calls) == 1
