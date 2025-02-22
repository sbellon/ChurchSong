from __future__ import annotations

import logging
import logging.handlers
import pathlib
import sys
import tomllib
import typing

import platformdirs
import pydantic

from churchsong import utils

T = typing.TypeVar('T', str, dict, list)


def recursive_expand_vars(data: T) -> T:
    if isinstance(data, str):
        return utils.expand_envvars(data)
    if isinstance(data, dict):
        return {k: recursive_expand_vars(v) for k, v in data.items()}
    if isinstance(data, list):
        return [recursive_expand_vars(item) for item in data]
    return data


class TomlConfig(pydantic.BaseModel):
    General: GeneralConfig
    ChurchTools: ChurchToolsConfig
    SongBeamer: SongBeamerConfig

    @pydantic.root_validator(pre=True)
    def apply_recursive_string_processing(
        cls, values: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        return recursive_expand_vars(values)


class GeneralConfig(pydantic.BaseModel):
    log_level: str
    log_file: str


class ChurchToolsConfig(pydantic.BaseModel):
    Settings: ChurchToolsSettingsConfig
    Replacements: dict[str, str]


class ChurchToolsSettingsConfig(pydantic.BaseModel):
    base_url: str
    login_token: str


class SongBeamerConfig(pydantic.BaseModel):
    Settings: SongBeamerSettingsConfig
    Slides: SongBeamerSlidesConfig | None = None
    Color: SongBeamerColorConfig | None = None


class SongBeamerSettingsConfig(pydantic.BaseModel):
    template_pptx: str
    portraits_dir: str
    temp_dir: str
    already_running_notice: str = ''


class SongBeamerSlidesConfig(pydantic.BaseModel):
    event_datetime_format: str | None = None
    Opening: SongBeamerSlidesStaticConfig | None = None
    Closing: SongBeamerSlidesStaticConfig | None = None
    Insert: list[SongBeamerSlidesDynamicConfig] | None = None


class SongBeamerSlidesStaticConfig(pydantic.BaseModel):
    content: str


class SongBeamerSlidesDynamicConfig(pydantic.BaseModel):
    keywords: list[str]
    content: str


class SongBeamerColorConfig(pydantic.BaseModel):
    Service: SongBeamerColorServiceConfig | None = None
    Replacements: list[SongBeamerColorReplacementsConfig] | None = None


class SongBeamerColorServiceConfig(pydantic.BaseModel):
    color: str
    bgcolor: str | None = None


class SongBeamerColorReplacementsConfig(pydantic.BaseModel):
    match_color: str
    color: str | None = None
    bgcolor: str | None = None


class Configuration:
    def __init__(self) -> None:
        self._log = logging.getLogger(__name__)
        self._log.setLevel(logging.INFO)
        log_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)-8s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
        )

        # Log to stderr before we have the log_file name from the .ini file.
        log_to_stderr = logging.StreamHandler(sys.stderr)
        log_to_stderr.setFormatter(log_formatter)
        self._log.addHandler(log_to_stderr)

        # Read the configuration .toml file.
        self._data_dir = pathlib.Path(
            platformdirs.user_data_dir(self.package_name, appauthor=False)
        )
        self._data_dir.mkdir(parents=True, exist_ok=True)
        config_dir = pathlib.Path(
            platformdirs.user_config_dir(self.package_name, appauthor=False)
        )
        config_dir.mkdir(parents=True, exist_ok=True)
        self._config_toml = config_dir / 'config.toml'
        try:
            with self._config_toml.open('rb') as fd:
                self._config = TomlConfig(**tomllib.load(fd))
        except FileNotFoundError:
            sys.stderr.write(
                f'Error: Configuration file "{self._config_toml}" not found\n'
            )
            sys.exit(1)
        except UnicodeDecodeError as e:
            sys.stderr.write(
                f'Error: Configuration file "{self._config_toml}" in invalid: {e}'
            )
            sys.exit(1)
        except Exception as e:
            self._log.fatal(e, exc_info=True)
            raise

        # Switch to configured logging.
        self._log.setLevel(self.log_level)
        log_to_file = logging.handlers.RotatingFileHandler(
            self.log_file, maxBytes=5 * 1024 * 1024, backupCount=7
        )
        log_to_file.setFormatter(log_formatter)
        self._log.addHandler(log_to_file)
        self._log.removeHandler(log_to_stderr)

    @property
    def package_name(self) -> str:
        return 'ChurchSong'

    @property
    def config_toml(self) -> pathlib.Path:
        return self._config_toml

    @property
    def data_dir(self) -> pathlib.Path:
        return self._data_dir

    @property
    def log(self) -> logging.Logger:
        return self._log

    @property
    def log_level(self) -> str:
        return self._config.General.log_level

    @property
    def log_file(self) -> pathlib.Path:
        filename = self.data_dir / self._config.General.log_file
        filename.parent.mkdir(parents=True, exist_ok=True)
        return filename

    @property
    def base_url(self) -> str:
        return self._config.ChurchTools.Settings.base_url

    @property
    def login_token(self) -> str:
        return self._config.ChurchTools.Settings.login_token

    @property
    def person_dict(self) -> dict[str, str]:
        return self._config.ChurchTools.Replacements

    @property
    def template_pptx(self) -> pathlib.Path:
        return self.data_dir / self._config.SongBeamer.Settings.template_pptx

    @property
    def portraits_dir(self) -> pathlib.Path:
        return self.data_dir / self._config.SongBeamer.Settings.portraits_dir

    @property
    def temp_dir(self) -> pathlib.Path:
        directory = self.data_dir / self._config.SongBeamer.Settings.temp_dir
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @property
    def already_running_notice(self) -> str:
        return self._config.SongBeamer.Settings.already_running_notice

    @property
    def event_datetime_format(self) -> str:
        return (
            self._config.SongBeamer.Slides.event_datetime_format
            if self._config.SongBeamer.Slides
            and self._config.SongBeamer.Slides.event_datetime_format
            else '%Y-%m-%d %H:%M'
        )

    @property
    def opening_slides(self) -> str:
        return (
            self._config.SongBeamer.Slides.Opening.content
            if self._config.SongBeamer.Slides and self._config.SongBeamer.Slides.Opening
            else ''
        )

    @property
    def closing_slides(self) -> str:
        return (
            self._config.SongBeamer.Slides.Closing.content
            if self._config.SongBeamer.Slides and self._config.SongBeamer.Slides.Closing
            else ''
        )

    @property
    def insert_slides(self) -> list[SongBeamerSlidesDynamicConfig]:
        return (
            self._config.SongBeamer.Slides.Insert
            if self._config.SongBeamer.Slides and self._config.SongBeamer.Slides.Insert
            else []
        )

    @property
    def color_service(self) -> SongBeamerColorServiceConfig:
        return (
            self._config.SongBeamer.Color.Service
            if self._config.SongBeamer.Color and self._config.SongBeamer.Color.Service
            else SongBeamerColorServiceConfig(color='clBlack')
        )

    @property
    def color_replacements(self) -> list[SongBeamerColorReplacementsConfig]:
        return (
            self._config.SongBeamer.Color.Replacements
            if self._config.SongBeamer.Color
            and self._config.SongBeamer.Color.Replacements
            else []
        )
