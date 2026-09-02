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


def test_broken_configuration_file_is_logged_and_reraised(
    config_toml: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    config_toml.write_text('this is not = = toml', encoding='utf-8')
    with caplog.at_level(logging.CRITICAL), pytest.raises(tomllib.TOMLDecodeError):
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


def hide_pyproject_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Pretend to be an installed distribution instead of a working tree."""
    monkeypatch.setattr(
        churchsong.configuration, '__file__', str(tmp_path / 'churchsong' / 'x.py')
    )


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
