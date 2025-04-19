# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import os
import re


def expand_envvars(text: str) -> str:
    return re.sub(
        r'\${([^${]+)}',
        lambda x: os.environ.get(x.group(1), f'${{{x.group(1)}}}'),
        text,
    )
