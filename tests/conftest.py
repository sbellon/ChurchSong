# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import gettext
import typing

import pytest
import responses

from churchsong.churchtools import ChurchToolsAPI
from churchsong.configuration import Configuration, TomlConfig

CHURCHTOOLS_BASE_URL = 'https://churchtools.test'
IMMICH_BASE_URL = 'https://immich.test'


class FakeConfiguration(Configuration):
    """A Configuration built from a plain dict instead of the on-disk config.toml.

    Bypasses Configuration.__init__ (config file lookup, logging and gettext
    setup) while still validating through the very same pydantic model tree,
    so tests exercise the real aliases, validators and envvar expansion.
    """

    def __init__(self, **data: typing.Any) -> None:  # noqa: ANN401
        TomlConfig.__init__(self, **data)


def make_config(
    *,
    output_dir: str = 'output',
    replacements: dict[str, str] | None = None,
    songbeamer: dict[str, typing.Any] | None = None,
    immich: dict[str, typing.Any] | None = None,
) -> Configuration:
    data: dict[str, typing.Any] = {
        'ChurchTools': {
            'base_url': CHURCHTOOLS_BASE_URL,
            'login_token': 'churchtools-test-token',
            'Replacements': replacements or {},
        },
        'SongBeamer': {'output_dir': output_dir, **(songbeamer or {})},
    }
    if immich is not None:
        data['Immich'] = {
            'base_url': IMMICH_BASE_URL,
            'login_token': 'immich-test-token',
            **immich,
        }
    return FakeConfiguration(**data)


def make_global_permissions(
    *,
    churchservice_view: bool = True,
    edit_events: bool = True,
    view_alldata: bool = True,
) -> dict[str, typing.Any]:
    """JSON as returned by GET /api/permissions/global."""
    return {
        'data': {
            'churchdb': {
                'view': True,
                'view alldata': [1] if view_alldata else [],
                'security level person': [1],
            },
            'churchcal': {
                'view': True,
                'view category': [1],
            },
            'churchservice': {
                'edit events': [1] if edit_events else [],
                'view': churchservice_view,
                'view servicegroup': [1],
                'view history': True,
                'view events': [1],
                'view agenda': [1],
                'view songcategory': [1],
            },
        }
    }


@pytest.fixture(scope='session', autouse=True)
def install_null_translations() -> None:
    # Configuration.__init__ normally installs _() into builtins; the
    # FakeConfiguration used in tests bypasses it, so install the identity
    # translation for code that calls _() at runtime (e.g. SongSheets).
    gettext.NullTranslations().install()


@pytest.fixture
def config() -> Configuration:
    return make_config()


@pytest.fixture
def mocked_responses() -> typing.Iterator[responses.RequestsMock]:
    with responses.RequestsMock() as rsps:
        yield rsps


@pytest.fixture
def churchtools_api(
    config: Configuration, mocked_responses: responses.RequestsMock
) -> ChurchToolsAPI:
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/permissions/global',
        json=make_global_permissions(),
    )
    return ChurchToolsAPI(config)
