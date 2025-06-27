# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import os
import re
import typing

from click import ClickException

CliError = ClickException


def expand_envvars(text: str) -> str:
    return re.sub(
        r'\${([^${]+)}',
        lambda x: os.environ.get(x.group(1), f'${{{x.group(1)}}}'),
        text,
    )


T = typing.TypeVar('T', str, dict[str, typing.Any], list[typing.Any])


def recursive_expand_envvars(data: T) -> T:  # noqa: UP047
    match data:
        case str():
            return expand_envvars(data)
        case dict():
            return {k: recursive_expand_envvars(v) for k, v in data.items()}
        case list():
            return [recursive_expand_envvars(item) for item in data]
    return data


def flattened_split(the_list: list[str], *, sep: str = ',') -> list[str]:
    return [split for item in the_list for split in item.split(sep)]
