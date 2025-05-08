# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

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

import packaging.version
import platformdirs
import polib
import pydantic
import requests

from churchsong.utils import CliError, recursive_expand_envvars

T = typing.TypeVar('T', pathlib.Path, pathlib.Path | None)


def make_relative_to_data_dir(value: T) -> T:
    return Configuration.data_dir / value if isinstance(value, pathlib.Path) else value


DataDirPath = typing.Annotated[
    pathlib.Path, pydantic.AfterValidator(make_relative_to_data_dir)
]
OptionalDataDirPath = typing.Annotated[
    pathlib.Path | None, pydantic.AfterValidator(make_relative_to_data_dir)
]


class FrozenModel(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)


class GeneralInteractiveConfig(FrozenModel):
    use_unicode_font: bool = False


class GeneralConfig(FrozenModel):
    log_level: str = 'WARNING'
    log_file: OptionalDataDirPath = None
    Interactive: GeneralInteractiveConfig = GeneralInteractiveConfig()


class ChurchToolsSettingsConfig(FrozenModel):
    base_url: str
    login_token: str


class ChurchToolsConfig(FrozenModel):
    Settings: ChurchToolsSettingsConfig
    Replacements: dict[str, str] = {str(None): 'Nobody'}


class SongBeamerSettingsConfig(FrozenModel):
    output_dir: DataDirPath
    date_format: str = '%Y-%m-%d'
    time_format: str = '%H:%M'


class SongBeamerPowerPointServicesConfig(FrozenModel):
    template_pptx: OptionalDataDirPath = None
    portraits_dir: DataDirPath = pathlib.Path()


class SongBeamerPowerPointAppointmentsConfig(FrozenModel):
    template_pptx: OptionalDataDirPath = None


class SongBeamerPowerPointConfig(FrozenModel):
    services: SongBeamerPowerPointServicesConfig = pydantic.Field(
        default=SongBeamerPowerPointServicesConfig(), alias='Services'
    )
    appointments: SongBeamerPowerPointAppointmentsConfig = pydantic.Field(
        default=SongBeamerPowerPointAppointmentsConfig(), alias='Appointments'
    )


class SongBeamerSlidesStaticConfig(FrozenModel):
    content: str = ''


class SongBeamerSlidesDynamicConfig(FrozenModel):
    keywords: list[str] = []
    content: str = ''


class SongBeamerSlidesConfig(FrozenModel):
    opening: SongBeamerSlidesStaticConfig = pydantic.Field(
        default=SongBeamerSlidesStaticConfig(), alias='Opening'
    )
    closing: SongBeamerSlidesStaticConfig = pydantic.Field(
        default=SongBeamerSlidesStaticConfig(), alias='Closing'
    )
    insert: list[SongBeamerSlidesDynamicConfig] = pydantic.Field(
        default=[], alias='Insert'
    )


class SongBeamerColorItemConfig(FrozenModel):
    color: str = 'clBlack'
    bgcolor: str | None = None


class SongBeamerColorConfig(FrozenModel):
    # Items are deliberately capitalized here, as they have to match ItemType from
    # churchsong.churchtools.events which is capitalized for consistency.
    Service: SongBeamerColorItemConfig = SongBeamerColorItemConfig()
    Header: SongBeamerColorItemConfig = SongBeamerColorItemConfig()
    Normal: SongBeamerColorItemConfig = SongBeamerColorItemConfig()
    Song: SongBeamerColorItemConfig = SongBeamerColorItemConfig()
    Link: SongBeamerColorItemConfig = SongBeamerColorItemConfig()
    File: SongBeamerColorItemConfig = SongBeamerColorItemConfig()


class SongBeamerConfig(FrozenModel):
    settings: SongBeamerSettingsConfig = pydantic.Field(alias='Settings')
    powerpoint: SongBeamerPowerPointConfig = pydantic.Field(
        default=SongBeamerPowerPointConfig(), alias='PowerPoint'
    )
    slides: SongBeamerSlidesConfig = pydantic.Field(
        default=SongBeamerSlidesConfig(), alias='Slides'
    )
    color: SongBeamerColorConfig = pydantic.Field(
        default=SongBeamerColorConfig(), alias='Color'
    )


class TomlConfig(FrozenModel):
    general: GeneralConfig = pydantic.Field(default=GeneralConfig(), alias='General')
    churchtools: ChurchToolsConfig = pydantic.Field(alias='ChurchTools')
    songbeamer: SongBeamerConfig = pydantic.Field(alias='SongBeamer')

    @pydantic.model_validator(mode='before')
    @classmethod
    def apply_recursive_string_processing(
        cls, values: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        return recursive_expand_envvars(values)


class Configuration(TomlConfig):
    package_name: typing.ClassVar[typing.Final[str]] = importlib.metadata.distribution(
        'churchsong'
    ).name
    log: typing.ClassVar[typing.Final[logging.Logger]] = logging.getLogger(__name__)
    data_dir: typing.ClassVar[typing.Final[pathlib.Path]] = platformdirs.user_data_path(
        package_name, appauthor=False
    )
    config_dir: typing.ClassVar[typing.Final[pathlib.Path]] = (
        platformdirs.user_config_path(package_name, appauthor=False)
    )

    def __init__(self) -> None:
        self.log.setLevel(logging.INFO)
        log_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)-8s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
        )

        # Log to stderr before we have the log_file name from the .ini file.
        log_to_stderr = logging.StreamHandler(sys.stderr)
        log_to_stderr.setFormatter(log_formatter)
        self.log.addHandler(log_to_stderr)

        # Read the configuration .toml file.
        config_toml = self.config_dir / 'config.toml'
        try:
            with config_toml.open('rb') as fd:
                super().__init__(**tomllib.load(fd))
        except FileNotFoundError:
            msg = f'Configuration file "{config_toml}" not found.'
            raise CliError(msg) from None
        except UnicodeDecodeError as e:
            msg = f'Configuration file "{config_toml}" is invalid: {e}'
            raise CliError(msg) from None
        except Exception as e:
            self.log.fatal(e, exc_info=True)
            raise

        # Switch to configured logging.
        self.log.setLevel(self.general.log_level)
        log_file = (
            self.general.log_file
            if self.general.log_file
            else self.data_dir / pathlib.Path(f'./Logs/{self.package_name}.log')
        )
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_to_file = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=7
        )
        log_to_file.setFormatter(log_formatter)
        self.log.addHandler(log_to_file)
        self.log.removeHandler(log_to_stderr)

        # Ensure the configured output directory exists from now on.
        self.songbeamer.settings.output_dir.mkdir(parents=True, exist_ok=True)

        # Setup locale specific settings and translations.
        locale.setlocale(locale.LC_TIME, locale.getlocale()[0])
        try:
            cc = loc[0:2] if (loc := locale.getlocale()[0]) else 'en'
            with importlib.resources.open_text(
                self.package_name.lower(), f'locales/{cc}.po'
            ) as fd:
                translations = gettext.GNUTranslations(
                    io.BytesIO(polib.pofile(fd.read()).to_binary())
                )
        except FileNotFoundError:
            translations = gettext.NullTranslations()
        translations.install()

    @property
    def version(self) -> packaging.version.Version:
        try:
            return packaging.version.Version(
                importlib.metadata.version(self.package_name)
            )
        except (importlib.metadata.PackageNotFoundError, AssertionError):
            return packaging.version.Version('0')

    @property
    def later_version_available(self) -> packaging.version.Version | None:
        class PyPI(pydantic.BaseModel):
            version: str

        class PyPIInfo(pydantic.BaseModel):
            info: PyPI

        try:
            r = requests.get(f'https://pypi.org/pypi/{self.package_name}/json')
            later = packaging.version.Version(PyPIInfo(**r.json()).info.version)
        except (requests.RequestException, pydantic.ValidationError):
            return None
        else:
            return later if later > self.version else None
