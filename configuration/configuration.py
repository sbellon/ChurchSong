from __future__ import annotations

import logging
import logging.handlers
import os
import pathlib
import re
import sys
import tomllib


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
        with config_file.open('rb') as fd:
            self._config = tomllib.load(fd)

        # Switch to configured logging.
        self._log.setLevel(self.log_level)
        log_to_file = logging.handlers.RotatingFileHandler(
            self.log_file, maxBytes=5 * 1024 * 1024, backupCount=7
        )
        log_to_file.setFormatter(log_formatter)
        self._log.addHandler(log_to_file)
        self._log.removeHandler(log_to_stderr)

    def validate(self) -> None:
        schema_error = False
        match self._config:
            case {
                'General': {'log_level': str(), 'log_file': str()},
                'ChurchTools': {
                    'Settings': {'base_url': str(), 'login_token': str()},
                    'Replacements': {**name_replace_map},
                },
                'SongBeamer': {
                    'Settings': {
                        'template_pptx': str(),
                        'portraits_dir': str(),
                        'temp_dir': str(),
                    },
                    'Slides': {
                        'Opening': {'content': str()},
                        'Closing': {'content': str()},
                        'Insert': [*insert_slide_items],
                    },
                    'Color': {
                        'Service': {'color': str(), 'bgcolor': str()},
                        'Replacements': [*color_replace_items],
                    },
                },
            }:
                for key, val in name_replace_map.items():
                    match key, val:
                        case str(), str():
                            pass
                        case _:
                            schema_error |= True
                for item in insert_slide_items:
                    match item:
                        case {'keywords': [*_], 'content': str()}:
                            pass
                        case _:
                            schema_error |= True
                for item in color_replace_items:
                    match item:
                        case {'match_color': str(), 'color': str(), 'bgcolor': str()}:
                            pass
                        case _:
                            schema_error |= True
            case _:
                schema_error |= True
        if schema_error:
            raise ValueError(f'invalid configuration: {self._config}')  # noqa: TRY003 EM102

    def _expand_vars(self, text: str) -> str:
        return re.sub(
            r'\${([^${]+)}',
            lambda x: os.environ.get(x.group(1), f'${{{x.group(1)}}}'),
            text,
        )

    def _lookup_str(self, *key_path: str) -> str:
        data = self._config
        for key in key_path:
            data = data[key]
        assert isinstance(data, str)
        return self._expand_vars(data)

    def _lookup_dict(self, *key_path: str) -> dict[str, str]:
        data = self._config
        for key in key_path:
            data = data[key]
        assert isinstance(data, dict)
        return {key: self._expand_vars(val) for key, val in data.items()}

    def _lookup_list(self, *key_path: str) -> list[dict[str, str]]:
        data = self._config
        for key in key_path:
            data = data[key]
        assert isinstance(data, list)
        return [
            {key: self._expand_vars(val) for key, val in elem.items()} for elem in data
        ]

    def _lookup_list_list(self, *key_path: str) -> list[dict[str, str | list[str]]]:
        data = self._config
        for key in key_path:
            data = data[key]
        assert isinstance(data, list)
        return [
            {
                key: [self._expand_vars(item) for item in val]
                if isinstance(val, list)
                else self._expand_vars(val)
                for key, val in elem.items()
            }
            for elem in data
        ]

    @property
    def log(self) -> logging.Logger:
        return self._log

    @property
    def log_level(self) -> str:
        return self._lookup_str('General', 'log_level')

    @property
    def log_file(self) -> pathlib.Path:
        filename = pathlib.Path(self._lookup_str('General', 'log_file'))
        filename.parent.mkdir(parents=True, exist_ok=True)
        return filename

    @property
    def base_url(self) -> str:
        return self._lookup_str('ChurchTools', 'Settings', 'base_url')

    @property
    def login_token(self) -> str:
        return self._lookup_str('ChurchTools', 'Settings', 'login_token')

    @property
    def person_dict(self) -> dict[str, str]:
        return self._lookup_dict('ChurchTools', 'Replacements')

    @property
    def template_pptx(self) -> pathlib.Path:
        return pathlib.Path(self._lookup_str('SongBeamer', 'Settings', 'template_pptx'))

    @property
    def portraits_dir(self) -> pathlib.Path:
        return pathlib.Path(self._lookup_str('SongBeamer', 'Settings', 'portraits_dir'))

    @property
    def temp_dir(self) -> pathlib.Path:
        directory = pathlib.Path(self._lookup_str('SongBeamer', 'Settings', 'temp_dir'))
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @property
    def opening_slides(self) -> str:
        return self._lookup_str('SongBeamer', 'Slides', 'Opening', 'content')

    @property
    def closing_slides(self) -> str:
        return self._lookup_str('SongBeamer', 'Slides', 'Closing', 'content')

    @property
    def insert_slides(self) -> list[dict[str, str | list[str]]]:
        return self._lookup_list_list('SongBeamer', 'Slides', 'Insert')

    @property
    def color_service(self) -> dict[str, str]:
        return self._lookup_dict('SongBeamer', 'Color', 'Service')

    @property
    def color_replacements(self) -> list[dict[str, str]]:
        return self._lookup_list('SongBeamer', 'Color', 'Replacements')
