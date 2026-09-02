# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import logging
import typing

import pytest

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
    _log = logging.getLogger('test')
    _base_url = 'https://host.test'
    _headers: dict[str, str] = {}  # noqa: RUF012 (only ever read, never mutated)


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
