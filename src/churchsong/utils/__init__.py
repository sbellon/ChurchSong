# SPDX-FileCopyrightText: 2024-2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import posixpath
import typing

from typer._click import ClickException

CliError = ClickException


def expand_envvars(text: str) -> str:
    # Not `os.path.expandvars()`: on Windows it expands `%VAR%` too, and nothing after
    # a single quote, which would leave `${VAR}` in a caption like "Jesus' Name".
    return posixpath.expandvars(text)


type JsonObject = dict[str, 'JsonValue']
type JsonValue = bool | int | float | str | list['JsonValue'] | JsonObject | None


def recursive_expand_envvars[T: JsonValue](data: T) -> T:
    match data:
        case str():
            return typing.cast('T', expand_envvars(data))
        case dict():
            return typing.cast(
                'T', {k: recursive_expand_envvars(v) for k, v in data.items()}
            )
        case list():
            return typing.cast('T', [recursive_expand_envvars(item) for item in data])
        case _:
            return data


def flattened_split(the_list: list[str], *, sep: str = ',') -> list[str]:
    return [split for item in the_list for split in item.split(sep)]
