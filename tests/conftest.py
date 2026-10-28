# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import gettext
import importlib.util
import pathlib
import re
import typing
import urllib.parse

import pytest
import responses

from churchsong.churchtools import ChurchToolsAPI
from churchsong.configuration import Configuration, TomlConfig
from churchsong.utils.http import BaseAPI

if typing.TYPE_CHECKING:
    import types

    import pydantic
    import requests

CHURCHTOOLS_BASE_URL = 'https://churchtools.test'
IMMICH_BASE_URL = 'https://immich.test'


def load_check_openapi() -> types.ModuleType:
    # A dev script, not a module of the package, so it is loaded by its path.
    path = pathlib.Path(__file__).parents[1] / 'dev-scripts' / 'check_openapi.py'
    spec = importlib.util.spec_from_file_location('check_openapi', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The endpoints `dev-scripts/check_openapi.py` checks, as the spec spells them.
OPENAPI_ENDPOINTS = typing.cast(
    'dict[str, type[pydantic.BaseModel]]', load_check_openapi().ENDPOINTS
)


def endpoint_template(path: str) -> str:
    """Spell an endpoint so that a spec placeholder and a concrete id compare equal.

    `/events/{eventId}/agenda` and `/events/4711/agenda` both become
    `/events/{}/agenda`.
    """
    return '/'.join(
        '{}' if re.fullmatch(r'\{\w*\}|\d+', segment) else segment
        for segment in path.split('/')
    )


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
    base_url: str = CHURCHTOOLS_BASE_URL,
    output_dir: str = 'output',
    replacements: dict[str, str] | None = None,
    songbeamer: dict[str, typing.Any] | None = None,
    immich: dict[str, typing.Any] | None = None,
) -> Configuration:
    data: dict[str, typing.Any] = {
        'ChurchTools': {
            'base_url': base_url,
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


def mock_churchtools_server(
    mocked_responses: responses.RequestsMock,
    permissions: dict[str, typing.Any] | None = None,
    *,
    version: str = '3.136.2',
) -> None:
    """Register what the ChurchToolsAPI constructor asks for: permissions, version."""
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/permissions/global',
        json=make_global_permissions() if permissions is None else permissions,
    )
    mocked_responses.get(
        f'{CHURCHTOOLS_BASE_URL}/api/info', json={'version': version, 'build': '1'}
    )


def mock_immich_server(
    mocked_responses: responses.RequestsMock,
    permissions: list[str],
    *,
    version: tuple[int, int, int] | None = (3, 2, 0),
) -> None:
    """Register what the ImmichAPI constructor asks for: permissions and version.

    With `version=None`, the version endpoint is left to the caller.
    """
    mocked_responses.get(
        f'{IMMICH_BASE_URL}/api/api-keys/me', json={'permissions': permissions}
    )
    if version is not None:
        major, minor, patch = version
        mocked_responses.get(
            f'{IMMICH_BASE_URL}/api/server/version',
            json={'major': major, 'minor': minor, 'patch': patch},
        )


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


@pytest.fixture(autouse=True)
def churchtools_answers_are_checked_against_openapi(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.Iterator[None]:
    """Fail a test in which ChurchTools answers an endpoint, or with a model, that
    `dev-scripts/check_openapi.py` does not list, so the script cannot fall behind.

    Every JSON answer goes through `BaseAPI._validate()`, which knows both the model
    and, from the response, the endpoint that was really asked.
    """
    listed = {
        (endpoint_template(path), model) for path, model in OPENAPI_ENDPOINTS.items()
    }
    answered: set[tuple[str, type]] = set()
    validate = BaseAPI._validate  # noqa: SLF001 # pyright: ignore[reportPrivateUsage]

    def recording_validate(
        self: BaseAPI, model: type[typing.Any], r: requests.Response
    ) -> typing.Any:  # noqa: ANN401 (whatever the model validates to)
        if isinstance(self, ChurchToolsAPI):
            path = urllib.parse.urlsplit(r.request.url or '').path
            answered.add((endpoint_template(path.removeprefix('/api')), model))
        return validate(self, model, r)

    monkeypatch.setattr(BaseAPI, '_validate', recording_validate)
    yield
    if unlisted := answered - listed:
        pytest.fail(
            'ENDPOINTS in dev-scripts/check_openapi.py lacks '
            + ', '.join(f'{path} -> {model.__name__}' for path, model in unlisted)
        )


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
    mock_churchtools_server(mocked_responses)
    return ChurchToolsAPI(config)
