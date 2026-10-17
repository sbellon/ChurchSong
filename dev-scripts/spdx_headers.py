#!/usr/bin/env -S uv run --script
#
# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT
#
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///

# Keeps SPDX headers in shape, run by pre-commit on the staged files:
# Python files without a header get one, and the committer's copyright year
# is brought up to date in every file that has one (2026 -> 2026-2027,
# 2024-2026 -> 2024-2027). Changed files make pre-commit stop the commit, so
# the changes can be reviewed and staged. ruff (flake8-copyright) checks that
# headers exist; this only adds and maintains them.

import datetime as dt
import pathlib
import re
import subprocess
import sys

HEADER_SUFFIXES = ('.py', '.pyi')
HEAD_LINES = 10


def committer_name() -> str:
    result = subprocess.run(
        ['git', 'config', 'user.name'],  # noqa: S607 (git is looked up on PATH)
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()


def add_header(text: str, name: str, year: int) -> str:
    header = (
        f'# SPDX-FileCopyrightText: {year} {name}\n#\n# SPDX-License-Identifier: MIT\n'
    )
    if text.startswith('#!'):
        shebang, _, rest = text.partition('\n')
        return f'{shebang}\n#\n{header}{rest}'
    return f'{header}\n{text}'


def update_year(text: str, name: str, year: int) -> str:
    years = r'(\d{4})(?:-(\d{4}))?'
    pattern = re.compile(
        rf'^(\S+ SPDX-FileCopyrightText: ){years}( {re.escape(name)})(?=\r?$)',
        re.MULTILINE,
    )

    def bump(match: re.Match[str]) -> str:
        prefix, start, end, suffix = match.group(1, 2, 3, 4)
        if int(end or start) >= year:
            return match[0]
        return f'{prefix}{start}-{year}{suffix}'

    return pattern.sub(bump, text, count=1)


def fix(text: str, suffix: str, name: str, year: int) -> str:
    head = '\n'.join(text.splitlines()[:HEAD_LINES])
    if suffix in HEADER_SUFFIXES and 'SPDX-FileCopyrightText:' not in head:
        return add_header(text, name, year)
    return update_year(text, name, year)


def main() -> int:
    name = committer_name()
    year = dt.datetime.now().astimezone().year
    changed: list[str] = []
    for arg in sys.argv[1:]:
        path = pathlib.Path(arg)
        try:
            # Bytes, not read_text(): line endings must stay as they are.
            text = path.read_bytes().decode('utf-8')
        except UnicodeDecodeError:
            continue
        new = fix(text, path.suffix, name, year)
        if new != text:
            path.write_bytes(new.encode('utf-8'))
            changed.append(arg)
    if changed:
        sys.stderr.write(f'added or updated SPDX headers in: {" ".join(changed)}\n')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
