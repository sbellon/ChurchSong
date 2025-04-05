from __future__ import annotations

import gettext
import importlib.metadata
import importlib.resources
import io
import locale
import logging
import logging.handlers
import pathlib
import sys
import tomllib
import typing

import platformdirs
import polib
import pydantic
import requests

from churchsong import utils

T = typing.TypeVar('T', str, dict[str, typing.Any], list[typing.Any])


def recursive_expand_vars(data: T) -> T:
    match data:
        case str():
            return utils.expand_envvars(data)
        case dict():
            return {k: recursive_expand_vars(v) for k, v in data.items()}
        case list():
            return [recursive_expand_vars(item) for item in data]
    return data


class GeneralConfig(pydantic.BaseModel):
    log_level: str = 'WARNING'
    log_file: pathlib.Path = pathlib.Path('./Logs/ChurchSong.log')


class ChurchToolsSettingsConfig(pydantic.BaseModel):
    base_url: str
    login_token: str


class ChurchToolsConfig(pydantic.BaseModel):
    Settings: ChurchToolsSettingsConfig
    Replacements: dict[str, str] = {str(None): 'Nobody'}


class SongBeamerSettingsConfig(pydantic.BaseModel):
    template_pptx: pathlib.Path
    portraits_dir: pathlib.Path
    temp_dir: pathlib.Path
    already_running_notice: str = ''


class SongBeamerSlidesStaticConfig(pydantic.BaseModel):
    content: str = ''


class SongBeamerSlidesDynamicConfig(pydantic.BaseModel):
    keywords: list[str] = []
    content: str = ''


class SongBeamerSlidesConfig(pydantic.BaseModel):
    event_datetime_format: str = '%Y-%m-%d %H:%M'
    Opening: SongBeamerSlidesStaticConfig = SongBeamerSlidesStaticConfig()
    Closing: SongBeamerSlidesStaticConfig = SongBeamerSlidesStaticConfig()
    Insert: list[SongBeamerSlidesDynamicConfig] = []


class SongBeamerColorItemConfig(pydantic.BaseModel):
    color: str = 'clBlack'
    bgcolor: str | None = None


class SongBeamerColorConfig(pydantic.BaseModel):
    Service: SongBeamerColorItemConfig = SongBeamerColorItemConfig()
    Header: SongBeamerColorItemConfig = SongBeamerColorItemConfig()
    Normal: SongBeamerColorItemConfig = SongBeamerColorItemConfig()
    Song: SongBeamerColorItemConfig = SongBeamerColorItemConfig()
    Link: SongBeamerColorItemConfig = SongBeamerColorItemConfig()
    File: SongBeamerColorItemConfig = SongBeamerColorItemConfig()


class SongBeamerConfig(pydantic.BaseModel):
    Settings: SongBeamerSettingsConfig
    Slides: SongBeamerSlidesConfig = SongBeamerSlidesConfig()
    Color: SongBeamerColorConfig = SongBeamerColorConfig()


class TomlConfig(pydantic.BaseModel):
    General: GeneralConfig = GeneralConfig()
    ChurchTools: ChurchToolsConfig
    SongBeamer: SongBeamerConfig

    @pydantic.model_validator(mode='before')
    @classmethod
    def apply_recursive_string_processing(
        cls, values: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        return recursive_expand_vars(values)


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

        try:
            cc = loc[0:2] if (loc := locale.getlocale()[0]) else 'en'
            with importlib.resources.open_text('churchsong', f'locales/{cc}.po') as fd:
                translations = gettext.GNUTranslations(
                    io.BytesIO(polib.pofile(fd.read()).to_binary())
                )
        except FileNotFoundError:
            translations = gettext.NullTranslations()
        translations.install()

    @property
    def package_name(self) -> str:
        return 'ChurchSong'

    @property
    def version(self) -> str:
        try:
            return importlib.metadata.version(self.package_name)
        except (importlib.metadata.PackageNotFoundError, AssertionError):
            return 'unknown'

    @property
    def latest_version(self) -> str | None:
        class PyPI(pydantic.BaseModel):
            version: str

        class PyPIInfo(pydantic.BaseModel):
            info: PyPI

        try:
            r = requests.get(f'https://pypi.org/pypi/{self.package_name}/json')
            result = PyPIInfo(**r.json())
        except (requests.RequestException, pydantic.ValidationError):
            return None
        else:
            return result.info.version

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
        return self._config.SongBeamer.Slides.event_datetime_format

    @property
    def opening_slides(self) -> str:
        return self._config.SongBeamer.Slides.Opening.content

    @property
    def closing_slides(self) -> str:
        return self._config.SongBeamer.Slides.Closing.content

    @property
    def insert_slides(self) -> list[SongBeamerSlidesDynamicConfig]:
        return self._config.SongBeamer.Slides.Insert

    @property
    def colors(self) -> SongBeamerColorConfig:
        return self._config.SongBeamer.Color
