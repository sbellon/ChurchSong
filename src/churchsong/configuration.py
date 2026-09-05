# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import contextlib
import datetime
import enum
import fnmatch
import gettext
import importlib.metadata
import importlib.resources
import io
import locale
import logging
import logging.handlers
import pathlib
import re
import tomllib
import typing
import urllib.parse

import packaging.version
import platformdirs
import polib
import pydantic
import requests

from churchsong.utils import CliError, JsonValue, recursive_expand_envvars

logger = logging.getLogger(__name__)


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
    @typing.overload
    def make_relative_to_data_dir(val: pathlib.Path) -> pathlib.Path: ...

    @staticmethod
    @typing.overload
    def make_relative_to_data_dir(val: None) -> None: ...

    @staticmethod
    def make_relative_to_data_dir(
        val: pathlib.Path | None,
    ) -> pathlib.Path | None:
        return (BaseModel.data_dir / val) if isinstance(val, pathlib.Path) else val

    type DataDirPath = typing.Annotated[
        pathlib.Path, pydantic.AfterValidator(make_relative_to_data_dir)
    ]
    type OptionalDataDirPath = typing.Annotated[
        pathlib.Path | None, pydantic.AfterValidator(make_relative_to_data_dir)
    ]


class GeneralInteractiveConfig(BaseModel):
    use_unicode_font: bool = False


def validate_log_level(level: str) -> str:
    # `logging` only knows the uppercase level names, so a lowercase `log_level` in the
    # configuration file would abort every command before it starts. Accept any casing
    # and normalize, and let only a genuinely unknown name be an error, reported here
    # with its configuration field instead of surfacing from `setLevel` as a ValueError.
    if level.upper() not in logging.getLevelNamesMapping():
        names = ', '.join(f'"{name}"' for name in logging.getLevelNamesMapping())
        msg = f'must be one of {names}, got "{level}"'
        raise ValueError(msg)
    return level.upper()


LogLevel = typing.Annotated[str, pydantic.AfterValidator(validate_log_level)]


class GeneralConfig(BaseModel):
    log_level: LogLevel = 'WARNING'
    log_file: BaseModel.OptionalDataDirPath = None
    interactive: GeneralInteractiveConfig = pydantic.Field(
        default=GeneralInteractiveConfig(), alias='Interactive'
    )


def validate_base_url(url: str) -> str:
    # Reject anything that is not an absolute http(s) URL here, so that the error names
    # the offending configuration field instead of only surfacing at the first request
    # as a requests.exceptions.MissingSchema pointing at the request. Trailing slashes
    # are stripped so that appending an endpoint path cannot double the separator.
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in {'http', 'https'} or not parts.netloc:
        msg = f'must be a URL starting with "http://" or "https://", got "{url}"'
        raise ValueError(msg)
    return url.rstrip('/')


BaseUrl = typing.Annotated[str, pydantic.AfterValidator(validate_base_url)]


def validate_datetime_format(fmt: str) -> str:
    # `strftime` rejects an unknown directive on Windows but not on Linux, so a format
    # using e.g. the POSIX `%-d` idiom works in development and still aborts the run on
    # the target platform. Reject it here, where the error can name the offending
    # configuration field instead of surfacing from an f-string three modules away.
    try:
        datetime.datetime.now(tz=datetime.UTC).strftime(fmt)
    except ValueError as e:
        msg = f'is not a valid date/time format: {e}'
        raise ValueError(msg) from None
    return fmt


DateTimeFormat = typing.Annotated[
    str, pydantic.AfterValidator(validate_datetime_format)
]


class ChurchToolsConfig(BaseModel):
    base_url: BaseUrl
    login_token: str
    replacements: dict[str, str] = pydantic.Field(default={}, alias='Replacements')


class SongBeamerPowerPointServicesConfig(BaseModel):
    template_pptx: BaseModel.OptionalDataDirPath = None
    portraits_dir: BaseModel.DataDirPath = pathlib.Path()


class SongBeamerPowerPointAppointmentsTableConfig(BaseModel):
    regular_datetime_format: DateTimeFormat = '%a. %d.%m. %H:%M'
    allday_datetime_format: DateTimeFormat = '%a. %d.%m.'
    multiday_datetime_format: DateTimeFormat = '%d.%m.'
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
    datetime_format: DateTimeFormat = '%a. %d.%m.%Y %H:%M'
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


def compile_glob(value: str) -> re.Pattern[str]:
    return re.compile(fnmatch.translate(value), re.IGNORECASE)


Globbing = typing.Annotated[re.Pattern[str], pydantic.BeforeValidator(compile_glob)]


class ImmichConfig(BaseModel):
    base_url: BaseUrl
    login_token: str
    include_globbings: list[Globbing] = [
        compile_glob(x) for x in ('*.jpg', '*.jpeg', '*.mp4', '*.mov', '*.heic')
    ]
    exclude_globbings: list[Globbing] = []
    tags: list[str] = []


class TomlConfig(BaseModel):
    general: GeneralConfig = pydantic.Field(default=GeneralConfig(), alias='General')
    churchtools: ChurchToolsConfig = pydantic.Field(alias='ChurchTools')
    songbeamer: SongBeamerConfig = pydantic.Field(alias='SongBeamer')
    immich: ImmichConfig | None = pydantic.Field(default=None, alias='Immich')

    @pydantic.model_validator(mode='before')
    @classmethod
    def apply_recursive_string_processing(cls, values: JsonValue) -> JsonValue:
        return recursive_expand_envvars(values)


def format_validation_error(e: pydantic.ValidationError) -> str:
    # Pydantic reports the location of an error in terms of the aliases, which are
    # exactly the PascalCase section and key names as written in the TOML file, so the
    # parts can be joined as-is; only list indices need bracket instead of dot syntax.
    def location(loc: tuple[int | str, ...]) -> str:
        return ''.join(
            f'[{item}]' if isinstance(item, int) else f'.{item}' for item in loc
        ).lstrip('.')

    return '\n'.join(f'  {location(err["loc"])}: {err["msg"]}' for err in e.errors())


class Configuration(TomlConfig):
    # The handlers live on the package's root logger, so that every module can log
    # through its own `logging.getLogger(__name__)` and have the records propagate
    # up to here - `%(name)s` in the formatter then tells the components apart.
    log: typing.ClassVar[typing.Final[logging.Logger]] = logging.getLogger(
        BaseModel.package_name.lower()
    )

    def __init__(self) -> None:  # noqa: PLR0915, C901
        # Constructing a second Configuration in one process re-does the setup below
        # instead of logging everything twice through the handlers of the first one.
        for handler in self.log.handlers[:]:
            self.log.removeHandler(handler)
            handler.close()  # the rotating file handler keeps the log file open

        self.log.setLevel(logging.INFO)
        log_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)-8s - %(name)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
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
        except tomllib.TOMLDecodeError as e:
            # The exception message already carries the offending line and column.
            msg = f'Configuration file "{self.config_toml}" is not valid TOML: {e}'
            raise CliError(msg) from None
        except pydantic.ValidationError as e:
            msg = (
                f'Configuration file "{self.config_toml}" is invalid:\n'
                f'{format_validation_error(e)}'
            )
            raise CliError(msg) from None
        except Exception as e:
            logger.fatal(e, exc_info=True)
            raise

        # Switch to configured logging.
        self.log.setLevel(self.general.log_level)
        log_file = self.general.log_file or self.data_dir / pathlib.Path(
            f'./Logs/{self.package_name}.log'
        )
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_to_file = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=5 * 1024 * 1024, backupCount=7
            )
        except OSError as e:
            msg = f'Cannot create log file "{log_file}": {e}'
            logger.error(msg)
            raise CliError(msg) from None
        log_to_file.setFormatter(log_formatter)
        self.log.addHandler(log_to_file)
        self.log.removeHandler(log_to_stderr)

        # Ensure the configured output directory exists from now on.
        try:
            self.songbeamer.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            msg = (
                'Cannot create SongBeamer output directory '
                f'"{self.songbeamer.output_dir}": {e}'
            )
            logger.error(msg)
            raise CliError(msg) from None

        # Setup locale specific settings and translations.
        try:
            locale.setlocale(locale.LC_TIME, (locale.getlocale()[0], 'utf-8'))
            cc = loc[0:2] if (loc := locale.getlocale()[0]) else 'en'
        except locale.Error:
            cc = 'en'
        try:
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
            contextlib.suppress(
                FileNotFoundError,
                KeyError,
                tomllib.TOMLDecodeError,
                packaging.version.InvalidVersion,
            ),
            (pathlib.Path(__file__).parent.parent.parent / 'pyproject.toml').open(
                'rb'
            ) as f,
        ):
            return packaging.version.Version(tomllib.load(f)['project']['version'])
        # Otherwise we are in Distribution Package mode.
        with contextlib.suppress(
            importlib.metadata.PackageNotFoundError,
            AssertionError,
            packaging.version.InvalidVersion,
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
                f'https://pypi.org/pypi/{self.package_name}/json', timeout=5
            )
            r.raise_for_status()
            later = packaging.version.Version(PyPIInfo(**r.json()).info.version)
        except (
            requests.RequestException,
            pydantic.ValidationError,
            packaging.version.InvalidVersion,
        ):
            return None
        else:
            return later if later > self.version else None
