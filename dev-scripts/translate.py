#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ['babel']
# ///

import contextlib
import os
import pathlib
import typing

from babel.messages.frontend import CommandLineInterface

LANGUAGES = ['de']


@contextlib.contextmanager
def working_directory(path: pathlib.Path) -> typing.Iterator[None]:
    prev_cwd = pathlib.Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(prev_cwd)


class Babel:
    RunType = typing.Callable[[list[str] | None], typing.Literal[0, 1] | None]

    def __init__(
        self, root_dir: pathlib.Path, src_dir: pathlib.Path, locale_dir: pathlib.Path
    ) -> None:
        self.root_dir = root_dir
        self.src_dir = src_dir
        self.locale_dir = locale_dir
        self.pot_file = locale_dir / 'messages.pot'
        babel = CommandLineInterface()
        self.run = typing.cast('Babel.RunType', babel.run)  # pyright: ignore[reportUnknownMemberType]

    def extract(self) -> None:
        with working_directory(self.root_dir):
            self.run(
                [
                    'pybabel',
                    'extract',
                    '-o',
                    os.fspath(self.pot_file),
                    os.fspath(self.src_dir),
                ]
            )

    def update(self, language: str) -> None:
        with working_directory(self.root_dir):
            self.run(
                [
                    'pybabel',
                    'update',
                    '-l',
                    language,
                    '-i',
                    os.fspath(self.pot_file),
                    '-o',
                    os.fspath(self.pot_file.parent / f'{language}.po'),
                    '--no-wrap',
                    '--init-missing',
                    '--ignore-obsolete',
                    '--update-header-comment',
                ]
            )


def main() -> None:
    babel = Babel(
        pathlib.Path(__file__).parent.parent,
        pathlib.Path('src/churchsong'),
        pathlib.Path('src/churchsong/locales'),
    )

    babel.extract()
    for language in LANGUAGES:
        babel.update(language)


if __name__ == '__main__':
    main()
