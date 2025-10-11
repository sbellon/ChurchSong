# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import typing

if typing.TYPE_CHECKING:
    from xlsxwriter.format import Format
    from xlsxwriter.worksheet import Worksheet


class Workbook:
    def __init__(
        self, filename: str | None = None, options: dict[str, typing.Any] | None = None
    ) -> None: ...
    def add_format(self, properties: dict[str, typing.Any] | None = None) -> Format: ...
    def add_worksheet(
        self, name: str | None = None, worksheet_class: Worksheet | None = None
    ) -> Worksheet: ...
    def close(self) -> None: ...
