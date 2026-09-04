# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import gettext
import importlib.metadata
import locale
import logging
import logging.handlers
import tomllib
import typing

import packaging.version
import pydantic
import pytest
import requests

import churchsong.configuration
from churchsong.configuration import BaseModel, Configuration
from churchsong.utils import CliError
from tests.conftest import FakeConfiguration, make_config

if typing.TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable

    import responses

    _: Callable[[str], str]

MINIMAL_TOML = """
[General]
log_level = "INFO"

[ChurchTools]
base_url = "https://churchtools.test"
login_token = "${CHURCHSONG_TEST_TOKEN}"

[SongBeamer]
output_dir = "output"

[SongBeamer.Color.Song]
color = "clGreen"
bgcolor = "clYellow"

[Immich]
base_url = "https://immich.test"
login_token = "immich-test-token"
"""

LOG_FILE_TOML = MINIMAL_TOML.replace(
    'log_level = "INFO"', 'log_level = "INFO"\nlog_file = "logs/custom.log"'
)

PYPI_URL = 'https://pypi.org/pypi/ChurchSong/json'

UNPARSABLE_VERSION_TOML = """
[project]
version = "one point two"
"""


def test_toml_sections_map_onto_snake_case_fields() -> None:
    config = FakeConfiguration(**tomllib.loads(MINIMAL_TOML))
    assert config.general.log_level == 'INFO'
    assert config.churchtools.base_url == 'https://churchtools.test'
    assert config.songbeamer.color.Song.color == 'clGreen'
    assert config.songbeamer.color.Song.bgcolor == 'clYellow'
    assert config.songbeamer.color.Header.color == 'clBlack'


def test_envvars_are_expanded_during_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('CHURCHSONG_TEST_TOKEN', 'secret-from-env')
    config = FakeConfiguration(**tomllib.loads(MINIMAL_TOML))
    assert config.churchtools.login_token == 'secret-from-env'


def test_unknown_envvars_stay_literal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('CHURCHSONG_TEST_TOKEN', raising=False)
    config = FakeConfiguration(**tomllib.loads(MINIMAL_TOML))
    assert config.churchtools.login_token == '${CHURCHSONG_TEST_TOKEN}'


def test_relative_output_dir_is_resolved_against_data_dir() -> None:
    config = make_config()
    assert config.songbeamer.output_dir == BaseModel.data_dir / 'output'


def test_absolute_output_dir_is_kept() -> None:
    absolute_dir = BaseModel.data_dir.parent / 'elsewhere'
    config = FakeConfiguration(
        ChurchTools={'base_url': 'https://churchtools.test', 'login_token': 'token'},
        SongBeamer={'output_dir': str(absolute_dir)},
    )
    assert config.songbeamer.output_dir == absolute_dir


def test_base_urls_are_stored_without_a_trailing_slash() -> None:
    config = FakeConfiguration(
        ChurchTools={
            'base_url': 'https://churchtools.test/',
            'login_token': 'token',
        },
        SongBeamer={'output_dir': 'output'},
        Immich={'base_url': 'https://immich.test///', 'login_token': 'token'},
    )
    assert config.churchtools.base_url == 'https://churchtools.test'
    assert config.immich is not None
    assert config.immich.base_url == 'https://immich.test'


def test_base_url_without_a_scheme_is_rejected() -> None:
    with pytest.raises(pydantic.ValidationError, match='base_url'):
        FakeConfiguration(
            ChurchTools={'base_url': 'churchtools.test', 'login_token': 'token'},
            SongBeamer={'output_dir': 'output'},
        )


def test_base_url_with_a_non_http_scheme_is_rejected() -> None:
    with pytest.raises(pydantic.ValidationError, match='base_url'):
        FakeConfiguration(
            ChurchTools={
                'base_url': 'ftp://churchtools.test',
                'login_token': 'token',
            },
            SongBeamer={'output_dir': 'output'},
        )


def test_immich_globbings_match_case_insensitively() -> None:
    config = FakeConfiguration(**tomllib.loads(MINIMAL_TOML))
    assert config.immich is not None
    includes = config.immich.include_globbings
    assert any(glob.match('IMG_1234.JPG') for glob in includes)
    assert any(glob.match('/some/dir/video.mov') for glob in includes)
    assert not any(glob.match('notes.txt') for glob in includes)


def test_immich_section_is_optional() -> None:
    config = make_config()
    assert config.immich is None


@pytest.fixture
def config_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> typing.Iterator[pathlib.Path]:
    """Let the real Configuration.__init__ run against a throw-away directory.

    Both the config file location and the data directory are class variables,
    and the constructor has global side effects (log handlers, the installed
    gettext translation) that have to be undone afterwards.
    """
    monkeypatch.setattr(BaseModel, 'config_toml', tmp_path / 'config.toml')
    monkeypatch.setattr(BaseModel, 'data_dir', tmp_path / 'data')
    log = Configuration.log
    known_handlers = log.handlers[:]
    log_level = log.level
    yield tmp_path / 'config.toml'
    for handler in log.handlers[:]:
        if handler not in known_handlers:
            log.removeHandler(handler)
            handler.close()  # the rotating file handler keeps the log file open
    log.setLevel(log_level)
    gettext.NullTranslations().install()


def test_configuration_reads_the_toml_file(config_toml: pathlib.Path) -> None:
    config_toml.write_text(MINIMAL_TOML, encoding='utf-8')
    config = Configuration()
    assert config.general.log_level == 'INFO'
    assert config.churchtools.base_url == 'https://churchtools.test'
    assert config.songbeamer.output_dir == BaseModel.data_dir / 'output'
    # The output directory is created upfront so that later steps can rely on it.
    assert config.songbeamer.output_dir.is_dir()


def test_configuration_switches_over_to_file_logging(config_toml: pathlib.Path) -> None:
    config_toml.write_text(MINIMAL_TOML, encoding='utf-8')
    config = Configuration()
    assert (BaseModel.data_dir / 'Logs' / 'ChurchSong.log').is_file()
    assert config.log.level == logging.INFO
    handlers = config.log.handlers
    assert any(isinstance(h, logging.handlers.RotatingFileHandler) for h in handlers)
    # The initial stderr handler is removed once the log file name is known.
    assert not any(type(h) is logging.StreamHandler for h in handlers)


def test_configuration_honors_a_configured_log_file(config_toml: pathlib.Path) -> None:
    config_toml.write_text(LOG_FILE_TOML, encoding='utf-8')
    Configuration()
    assert (BaseModel.data_dir / 'logs' / 'custom.log').is_file()


def test_missing_configuration_file_is_reported(config_toml: pathlib.Path) -> None:
    assert not config_toml.exists()
    with pytest.raises(CliError, match='not found'):
        Configuration()


def test_configuration_file_with_invalid_encoding_is_reported(
    config_toml: pathlib.Path,
) -> None:
    config_toml.write_bytes(b'[ChurchTools]\nbase_url = "\xff\xfe"\n')
    with pytest.raises(CliError, match='is invalid'):
        Configuration()


def test_malformed_toml_is_reported(config_toml: pathlib.Path) -> None:
    config_toml.write_text('this is not = = toml', encoding='utf-8')
    with pytest.raises(CliError, match='not valid TOML'):
        Configuration()


def test_invalid_configuration_reports_the_offending_section_and_field(
    config_toml: pathlib.Path,
) -> None:
    config_toml.write_text(
        '[ChurchTools]\nbase_url = "https://churchtools.test"\n', encoding='utf-8'
    )
    with pytest.raises(CliError) as exc_info:
        Configuration()
    message = exc_info.value.format_message()
    assert 'ChurchTools.login_token' in message
    assert 'SongBeamer' in message


def test_unexpected_configuration_errors_are_logged_and_reraised(
    config_toml: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_toml.write_text(MINIMAL_TOML, encoding='utf-8')

    def raise_boom(*_args: object, **_kwargs: object) -> None:
        msg = 'disk on fire'
        raise OSError(msg)

    monkeypatch.setattr(tomllib, 'load', raise_boom)
    with (
        caplog.at_level(logging.CRITICAL),
        pytest.raises(OSError, match='disk on fire'),
    ):
        Configuration()
    assert any(record.levelno == logging.CRITICAL for record in caplog.records)


def test_translations_are_installed_for_the_locale(
    config_toml: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def any_locale(_category: int, _locale: object = None) -> str:
        return ''

    def german_locale(*_args: object) -> tuple[str, str]:
        return ('de_DE', 'UTF-8')

    # Do not depend on the German locale being installed on the test machine.
    monkeypatch.setattr(locale, 'setlocale', any_locale)
    monkeypatch.setattr(locale, 'getlocale', german_locale)
    config_toml.write_text(MINIMAL_TOML, encoding='utf-8')
    Configuration()
    assert _('Nobody') == 'Niemand'


def test_unknown_locale_falls_back_to_untranslated_strings(
    config_toml: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unsupported_locale(_category: int, _locale: object = None) -> str:
        raise locale.Error

    # Without a usable locale the code falls back to 'en', for which there is
    # no catalog at all.
    monkeypatch.setattr(locale, 'setlocale', unsupported_locale)
    config_toml.write_text(MINIMAL_TOML, encoding='utf-8')
    Configuration()
    assert _('Nobody') == 'Nobody'


def test_later_version_available_reports_a_newer_release(
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(PYPI_URL, json={'info': {'version': '99.0.0'}})
    assert make_config().later_version_available == packaging.version.Version('99.0.0')


def test_later_version_available_ignores_an_older_release(
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(PYPI_URL, json={'info': {'version': '0.0.1'}})
    assert make_config().later_version_available is None


def test_later_version_available_survives_an_unreachable_pypi(
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(PYPI_URL, body=requests.exceptions.ConnectionError())
    assert make_config().later_version_available is None


def test_later_version_available_ignores_a_malformed_answer(
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(PYPI_URL, json={'unexpected': 'payload'})
    assert make_config().later_version_available is None


def test_later_version_available_ignores_an_unparsable_version(
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(PYPI_URL, json={'info': {'version': 'one point two'}})
    assert make_config().later_version_available is None


def test_later_version_available_ignores_an_error_response(
    mocked_responses: responses.RequestsMock,
) -> None:
    # The payload is a perfectly fine answer - only the status code says it is none.
    mocked_responses.get(PYPI_URL, json={'info': {'version': '99.0.0'}}, status=503)
    assert make_config().later_version_available is None


def hide_pyproject_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Pretend to be an installed distribution instead of a working tree."""
    monkeypatch.setattr(
        churchsong.configuration, '__file__', str(tmp_path / 'churchsong' / 'x.py')
    )


def fake_pyproject_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, content: str
) -> None:
    """Pretend to be a working tree whose pyproject.toml holds `content`."""
    monkeypatch.setattr(
        churchsong.configuration,
        '__file__',
        str(tmp_path / 'src' / 'churchsong' / 'configuration.py'),
    )
    (tmp_path / 'pyproject.toml').write_text(content, encoding='utf-8')


def test_version_falls_back_to_the_installed_distribution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    hide_pyproject_toml(monkeypatch, tmp_path)
    installed = importlib.metadata.version(Configuration.package_name)
    assert make_config().version == packaging.version.Version(installed)


def test_version_without_any_version_information_is_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    def not_installed(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    hide_pyproject_toml(monkeypatch, tmp_path)
    monkeypatch.setattr(importlib.metadata, 'version', not_installed)
    assert make_config().version == packaging.version.Version('0')


def test_version_survives_a_broken_pyproject(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    fake_pyproject_toml(monkeypatch, tmp_path, 'this is not [valid toml')
    installed = importlib.metadata.version(Configuration.package_name)
    assert make_config().version == packaging.version.Version(installed)


def test_version_survives_an_unparsable_version_in_pyproject(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    def not_installed(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    fake_pyproject_toml(monkeypatch, tmp_path, UNPARSABLE_VERSION_TOML)
    monkeypatch.setattr(importlib.metadata, 'version', not_installed)
    assert make_config().version == packaging.version.Version('0')


def test_version_survives_an_unparsable_installed_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    def broken_version(_name: str) -> str:
        return 'one point two'

    hide_pyproject_toml(monkeypatch, tmp_path)
    monkeypatch.setattr(importlib.metadata, 'version', broken_version)
    assert make_config().version == packaging.version.Version('0')
