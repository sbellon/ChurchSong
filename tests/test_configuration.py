# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import tomllib
import typing

from churchsong.configuration import BaseModel
from tests.conftest import FakeConfiguration, make_config

if typing.TYPE_CHECKING:
    import pytest

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
