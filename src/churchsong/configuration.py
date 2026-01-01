# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import contextlib
import enum
import gettext
import importlib.metadata
import importlib.resources
import io
import locale
import logging
import logging.handlers
import pathlib
import tomllib
import typing

import packaging.version
import platformdirs
import polib
import pydantic
import requests

from churchsong.utils import CliError, recursive_expand_envvars


class CalendarSubtitleField(enum.StrEnum):
    SUBTITLE = 'subtitle'
    DESCRIPTION = 'description'
    LINK = 'link'
    ADDRESS = 'address'


class BaseModel(pydantic.BaseModel):
    # Configure config model to treat all fields as read-only.
    model_config = pydantic.ConfigDict(frozen=True)

    # Define a consistent package name. Reading from package metadata does not work
    # because it does not retain casing.
    package_name: typing.ClassVar[typing.Final[str]] = 'ChurchSong'

    # Platform-dependent data directory to use.
    data_dir: typing.ClassVar[typing.Final[pathlib.Path]] = platformdirs.user_data_path(
        package_name, appauthor=False
    )

    config_toml: typing.ClassVar[typing.Final[pathlib.Path]] = (
        platformdirs.user_config_path(package_name, appauthor=False) / 'config.toml'
    )

    # Define specific types DataDirPath and OptionalDataDirPath that both will be
    # made relative to the `data_dir` above in case they are specified relative in
    # the configuration file.
    @staticmethod
    def make_relative_to_data_dir[T: pathlib.Path | None](value: T) -> T:
        return BaseModel.data_dir / value if isinstance(value, pathlib.Path) else value

    type DataDirPath = typing.Annotated[
        pathlib.Path, pydantic.AfterValidator(make_relative_to_data_dir)
    ]
    type OptionalDataDirPath = typing.Annotated[
        pathlib.Path | None, pydantic.AfterValidator(make_relative_to_data_dir)
    ]


class GeneralInteractiveConfig(BaseModel):
    use_unicode_font: bool = False


class GeneralConfig(BaseModel):
    log_level: str = 'WARNING'
    log_file: BaseModel.OptionalDataDirPath = None
    interactive: GeneralInteractiveConfig = pydantic.Field(
        default=GeneralInteractiveConfig(), alias='Interactive'
    )


class ChurchToolsConfig(BaseModel):
    base_url: str
    login_token: str
    replacements: dict[str, str] = pydantic.Field(default={}, alias='Replacements')


class SongBeamerPowerPointServicesConfig(BaseModel):
    template_pptx: BaseModel.OptionalDataDirPath = None
    portraits_dir: BaseModel.DataDirPath = pathlib.Path()


class SongBeamerPowerPointAppointmentsTableConfig(BaseModel):
    regular_datetime_format: str = '%a. %d.%m. %H:%M'
    allday_datetime_format: str = '%a. %d.%m.'
    multiday_datetime_format: str = '%d.%m.'
    subtitle_priority: list[CalendarSubtitleField] = [
        CalendarSubtitleField.SUBTITLE,
        CalendarSubtitleField.DESCRIPTION,
        CalendarSubtitleField.LINK,
        CalendarSubtitleField.ADDRESS,
    ]


class SongBeamerPowerPointAppointmentsConfig(BaseModel):
    template_pptx: BaseModel.OptionalDataDirPath = None
    look_ahead_weeks: int = 13
    weekly: SongBeamerPowerPointAppointmentsTableConfig = pydantic.Field(
        default=SongBeamerPowerPointAppointmentsTableConfig(), alias='Weekly'
    )
    irregular: SongBeamerPowerPointAppointmentsTableConfig = pydantic.Field(
        default=SongBeamerPowerPointAppointmentsTableConfig(), alias='Irregular'
    )


class SongBeamerPowerPointConfig(BaseModel):
    services: SongBeamerPowerPointServicesConfig = pydantic.Field(
        default=SongBeamerPowerPointServicesConfig(), alias='Services'
    )
    appointments: SongBeamerPowerPointAppointmentsConfig = pydantic.Field(
        default=SongBeamerPowerPointAppointmentsConfig(), alias='Appointments'
    )


class SongBeamerSlidesStaticConfig(BaseModel):
    content: str = ''


class SongBeamerSlidesDynamicConfig(BaseModel):
    keywords: list[str] = []
    content: str = ''


class SongBeamerSlidesConfig(BaseModel):
    datetime_format: str = '%a. %d.%m.%Y %H:%M'
    opening: SongBeamerSlidesStaticConfig = pydantic.Field(
        default=SongBeamerSlidesStaticConfig(), alias='Opening'
    )
    closing: SongBeamerSlidesStaticConfig = pydantic.Field(
        default=SongBeamerSlidesStaticConfig(), alias='Closing'
    )
    insert: list[SongBeamerSlidesDynamicConfig] = pydantic.Field(
        default=[], alias='Insert'
    )


class SongBeamerColorItemConfig(BaseModel):
    color: str = 'clBlack'
    bgcolor: str | None = None


class SongBeamerColorConfig(BaseModel):
    # Items are deliberately capitalized here, as they have to match ItemType from
    # churchsong.churchtools.events which is capitalized for consistency.
    Service: SongBeamerColorItemConfig = SongBeamerColorItemConfig()
    Header: SongBeamerColorItemConfig = SongBeamerColorItemConfig()
    Normal: SongBeamerColorItemConfig = SongBeamerColorItemConfig()
    Song: SongBeamerColorItemConfig = SongBeamerColorItemConfig()
    Link: SongBeamerColorItemConfig = SongBeamerColorItemConfig()
    File: SongBeamerColorItemConfig = SongBeamerColorItemConfig()


class SongBeamerConfig(BaseModel):
    output_dir: BaseModel.DataDirPath
    powerpoint: SongBeamerPowerPointConfig = pydantic.Field(
        default=SongBeamerPowerPointConfig(), alias='PowerPoint'
    )
    slides: SongBeamerSlidesConfig = pydantic.Field(
        default=SongBeamerSlidesConfig(), alias='Slides'
    )
    color: SongBeamerColorConfig = pydantic.Field(
        default=SongBeamerColorConfig(), alias='Color'
    )


class TomlConfig(BaseModel):
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
    log: typing.ClassVar[typing.Final[logging.Logger]] = logging.getLogger(__name__)

    def __init__(self) -> None:
        self.log.setLevel(logging.INFO)
        log_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)-8s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
        )

        # Log to stderr before we have the log_file name from the .ini file.
        log_to_stderr = logging.StreamHandler()
        log_to_stderr.setFormatter(log_formatter)
        self.log.addHandler(log_to_stderr)

        # Read the configuration .toml file.
        try:
            with self.config_toml.open('rb') as fd:
                super().__init__(**tomllib.load(fd))
        except FileNotFoundError:
            msg = f'Configuration file "{self.config_toml}" not found.'
            raise CliError(msg) from None
        except UnicodeDecodeError as e:
            msg = f'Configuration file "{self.config_toml}" is invalid: {e}'
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
        self.songbeamer.output_dir.mkdir(parents=True, exist_ok=True)

        # Setup locale specific settings and translations.
        locale.setlocale(locale.LC_TIME, (locale.getlocale()[0], 'utf-8'))
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
        # If we have access to the pyproject.toml, we are in development mode.
        with (
            contextlib.suppress(FileNotFoundError, KeyError),
            (pathlib.Path(__file__).parent.parent.parent / 'pyproject.toml').open(
                'rb'
            ) as f,
        ):
            return packaging.version.Version(tomllib.load(f)['project']['version'])
        # Otherwise we are in Distribution Package mode.
        with contextlib.suppress(
            importlib.metadata.PackageNotFoundError, AssertionError
        ):
            return packaging.version.Version(
                importlib.metadata.version(self.package_name)
            )
        return packaging.version.Version('0')

    @property
    def later_version_available(self) -> packaging.version.Version | None:
        class PyPI(pydantic.BaseModel):
            version: str

        class PyPIInfo(pydantic.BaseModel):
            info: PyPI

        try:
            r = requests.get(
                f'https://pypi.org/pypi/{self.package_name}/json', timeout=30
            )
            later = packaging.version.Version(PyPIInfo(**r.json()).info.version)
        except (requests.RequestException, pydantic.ValidationError):
            return None
        else:
            return later if later > self.version else None
