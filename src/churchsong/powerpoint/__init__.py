# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import abc
import os
import typing

import pptx
import pptx.exc

if typing.TYPE_CHECKING:
    import pathlib

    from churchsong.configuration import Configuration


class PowerPointBase(abc.ABC):  # noqa: B024
    def __init__(
        self, config: Configuration, template_pptx: pathlib.Path | None
    ) -> None:
        self._log = config.log
        if template_pptx:
            self._output_pptx = config.songbeamer.output_dir / template_pptx.name
            try:
                self._prs = pptx.Presentation(os.fspath(template_pptx))
            except pptx.exc.PackageNotFoundError as e:
                self._log.error(f'Cannot load PowerPoint template: {e}')
                self._prs = None
        else:
            self._log.warning('No PowerPoint template configured, skipping')
            self._prs = None

    def save(self) -> None:
        if self._prs:
            self._prs.save(os.fspath(self._output_pptx))
