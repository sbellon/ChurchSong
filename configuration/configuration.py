from __future__ import annotations

import logging
import logging.handlers
import os
import pathlib
import re
import sys
import tomllib
import typing

import pydantic


def recursive_expand_vars(data: typing.Any) -> typing.Any:  # noqa: ANN401
    if isinstance(data, str):
        return re.sub(
            r'\${([^${]+)}',
            lambda x: os.environ.get(x.group(1), f'${{{x.group(1)}}}'),
            data,
        )
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
    Slides: SongBeamerSlidesConfig
    Color: SongBeamerColorConfig


class SongBeamerSettingsConfig(pydantic.BaseModel):
    template_pptx: str
    portraits_dir: str
    temp_dir: str


class SongBeamerSlidesConfig(pydantic.BaseModel):
    Opening: SongBeamerSlidesStaticConfig
    Closing: SongBeamerSlidesStaticConfig
    Insert: list[SongBeamerSlidesDynamicConfig]


class SongBeamerSlidesStaticConfig(pydantic.BaseModel):
    content: str


class SongBeamerSlidesDynamicConfig(pydantic.BaseModel):
    keywords: list[str]
    content: str


class SongBeamerColorConfig(pydantic.BaseModel):
    Service: SongBeamerColorServiceConfig
    Replacements: list[SongBeamerColorReplacementsConfig]


class SongBeamerColorServiceConfig(pydantic.BaseModel):
    color: str
    bgcolor: str


class SongBeamerColorReplacementsConfig(pydantic.BaseModel):
    match_color: str
    color: str
    bgcolor: str


class Configuration:
    def __init__(self, config_file: pathlib.Path) -> None:
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
        try:
            with config_file.open('rb') as fd:
                self._config = TomlConfig(**tomllib.load(fd))
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
    def log(self) -> logging.Logger:
        return self._log

    @property
    def log_level(self) -> str:
        return self._config.General.log_level

    @property
    def log_file(self) -> pathlib.Path:
        filename = pathlib.Path(self._config.General.log_file)
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
        return pathlib.Path(self._config.SongBeamer.Settings.template_pptx)

    @property
    def portraits_dir(self) -> pathlib.Path:
        return pathlib.Path(self._config.SongBeamer.Settings.portraits_dir)

    @property
    def temp_dir(self) -> pathlib.Path:
        directory = pathlib.Path(self._config.SongBeamer.Settings.temp_dir)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

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
    def color_service(self) -> SongBeamerColorServiceConfig:
        return self._config.SongBeamer.Color.Service

    @property
    def color_replacements(self) -> list[SongBeamerColorReplacementsConfig]:
        return self._config.SongBeamer.Color.Replacements
