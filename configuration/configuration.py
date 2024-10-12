from __future__ import annotations

import configparser
import logging
import logging.handlers
import os
import pathlib
import sys


class Configuration:
    def __init__(self, ini_file: pathlib.Path) -> None:
        self._log = logging.getLogger(__name__)
        self._log.setLevel(logging.INFO)
        log_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)-8s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
        )

        # Log to stderr before we have the log_file name from the .ini file.
        log_to_stderr = logging.StreamHandler(sys.stderr)
        log_to_stderr.setFormatter(log_formatter)
        self._log.addHandler(log_to_stderr)

        # Read the configuration .ini file.
        self._config = configparser.RawConfigParser(
            interpolation=configparser.ExtendedInterpolation(),
        )
        self._config.optionxform = lambda optionstr: optionstr
        self._config.read(ini_file, encoding='utf-8')

        # Switch to configured logging.
        self._log.setLevel(self.log_level)
        log_to_file = logging.handlers.RotatingFileHandler(
            self.log_file, maxBytes=5 * 1024 * 1024, backupCount=7
        )
        log_to_file.setFormatter(log_formatter)
        self._log.addHandler(log_to_file)
        self._log.removeHandler(log_to_stderr)

    def _expand_vars(self, section: str, option: str) -> str:
        return self._config.get(section, option, vars=dict(os.environ))

    @property
    def log(self) -> logging.Logger:
        return self._log

    @property
    def log_level(self) -> str:
        return self._expand_vars('General', 'log_level')

    @property
    def log_file(self) -> pathlib.Path:
        filename = pathlib.Path(self._expand_vars('General', 'log_file'))
        filename.parent.mkdir(parents=True, exist_ok=True)
        return filename

    @property
    def base_url(self) -> str:
        return self._expand_vars('ChurchTools.Settings', 'base_url')

    @property
    def login_token(self) -> str:
        return self._expand_vars('ChurchTools.Settings', 'login_token')

    @property
    def person_dict(self) -> dict[str, str]:
        return dict(self._config.items('ChurchTools.Replacements'))

    @property
    def template_pptx(self) -> pathlib.Path:
        return pathlib.Path(self._expand_vars('SongBeamer.Settings', 'template_pptx'))

    @property
    def portraits_dir(self) -> pathlib.Path:
        return pathlib.Path(self._expand_vars('SongBeamer.Settings', 'portraits_dir'))

    @property
    def temp_dir(self) -> pathlib.Path:
        directory = pathlib.Path(self._expand_vars('SongBeamer.Settings', 'temp_dir'))
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @property
    def replacements(self) -> list[tuple[str, str]]:
        return [
            (key, val.replace('\\n', '\n').replace('\\r', '\r').replace('\\', '/'))
            for key, val in self._config.items(
                'SongBeamer.Replacements',
                vars=dict(os.environ),
            )
        ]
