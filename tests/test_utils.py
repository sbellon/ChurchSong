# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import typing

from churchsong.utils import (
    JsonObject,
    expand_envvars,
    flattened_split,
    recursive_expand_envvars,
)
from churchsong.utils.http import is_same_host

if typing.TYPE_CHECKING:
    import pytest


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
