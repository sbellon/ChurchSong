# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import typing

from xlsxwriter.format import Format

Types = bool | float | int | str | Format


class Worksheet:
    def write(self, row: int, col: int, *args: Types) -> int: ...
    def set_column(
        self,
        first_col: int,
        last_col: int,
        width: int | None = None,
        cell_format: int | None = None,
        options: dict[str, typing.Any] | None = None,
    ) -> int: ...
