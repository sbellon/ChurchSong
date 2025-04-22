# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import os
import re
import typing

from click import ClickException

CliError = ClickException


T = typing.TypeVar('T')


class staticproperty(typing.Generic[T]):  # noqa: N801
    def __init__(self, f: typing.Callable[[], T]) -> None:
        self.f = f

    def __get__(self, instance: object, owner: type[object]) -> T:
        return self.f()


def expand_envvars(text: str) -> str:
    return re.sub(
        r'\${([^${]+)}',
        lambda x: os.environ.get(x.group(1), f'${{{x.group(1)}}}'),
        text,
    )


def flattened_split(the_list: list[str], *, sep: str = ',') -> list[str]:
    return [split for item in the_list for split in item.split(sep)]
