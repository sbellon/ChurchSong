#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ['babel']
# ///

import contextlib
import os
import pathlib

from babel.messages.frontend import CommandLineInterface


LANGUAGES = ['de']


@contextlib.contextmanager
def working_directory(path: pathlib.Path):
    prev_cwd = pathlib.Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(prev_cwd)


def extract(root: pathlib.Path, directory: str, pot_file: str) -> None:
    with working_directory(root):
        CommandLineInterface().run(['pybabel', 'extract', '-o', pot_file, directory])


def update(root: pathlib.Path, language: str, pot_file: str) -> None:
    po_file = os.path.join(os.path.dirname(pot_file), f'{language}.po')

    with working_directory(root):
        CommandLineInterface().run(
            [
                'pybabel',
                'update',
                '-l',
                language,
                '-i',
                pot_file,
                '-o',
                po_file,
                '--no-wrap',
                '--init-missing',
                '--ignore-obsolete',
                '--update-header-comment',
            ]
        )


def main():
    root = pathlib.Path(__file__).parent.parent
    directory = 'src/churchsong'
    locale_dir = os.path.join(directory, 'locales')
    pot_file = os.path.join(locale_dir, 'messages.pot')

    extract(root, directory, pot_file)
    for language in LANGUAGES:
        update(root, language, pot_file)


if __name__ == '__main__':
    main()
