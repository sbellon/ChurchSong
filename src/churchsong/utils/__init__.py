# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import os
import re

from click import ClickException

CliError = ClickException


def expand_envvars(text: str) -> str:
    return re.sub(
        r'\${([^${]+)}',
        lambda x: os.environ.get(x.group(1), f'${{{x.group(1)}}}'),
        text,
    )


def flattened_split(the_list: list[str], *, sep: str = ',') -> list[str]:
    return [split for item in the_list for split in item.split(sep)]
