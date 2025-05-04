# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import os
import pathlib

import pptx
import pptx.exc

from churchsong.configuration import Configuration


class PowerPointBase:
    def __init__(
        self,
        config: Configuration,
        template_pptx: pathlib.Path | None,
        output_dir: pathlib.Path,
    ) -> None:
        self._log = config.log
        if template_pptx:
            self._output_pptx = output_dir / template_pptx.name
            try:
                self._prs = pptx.Presentation(os.fspath(template_pptx))
            except pptx.exc.PackageNotFoundError as e:
                self._log.error(f'Cannot load PowerPoint template: {e}')
                self._prs = pptx.Presentation()
        else:
            self._output_pptx = None
            self._prs = pptx.Presentation()

    def save(self) -> None:
        if self._output_pptx:
            self._prs.save(os.fspath(self._output_pptx))
