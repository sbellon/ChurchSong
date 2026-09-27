# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

r"""
SongBeamer song files (.sng) start with a header of `#Key=Value` lines, followed by
the verses, each introduced by a `---` line:

  #LangCount=1
  #Title=Amazing Grace
  #BackgroundImage=Backgrounds\sunrise.jpg
  ---
  Amazing grace, how sweet the sound
  ...

A file starting with a UTF-8 byte order mark is UTF-8, any other one is read by
SongBeamer in the Windows ANSI code page.
"""

import codecs
import logging
import pathlib
import typing

from churchsong.churchtools.events import Subfolder
from churchsong.configuration import AgendaItemType
from churchsong.utils.file import atomic_replace
from churchsong.utils.progress import Progress

if typing.TYPE_CHECKING:
    from churchsong.churchtools.events import Item
    from churchsong.configuration import Configuration
    from churchsong.immich import ImmichAPI

logger = logging.getLogger(__name__)


class SngFile:
    """The lines of a song file, decoded the way SongBeamer decodes them.

    `header` holds the leading `#Key=Value` lines, `body` everything from the first
    other line on. The lines keep their line endings, and bytes that are invalid in
    the encoding survive as lone surrogates (`surrogateescape`), so that `bytes()`
    returns the content exactly as it was read, apart from what was changed in
    between.
    """

    BACKGROUND_IMAGE_KEY = '#BackgroundImage='

    def __init__(self, content: bytes) -> None:
        self._bom = codecs.BOM_UTF8 if content.startswith(codecs.BOM_UTF8) else b''
        self._encoding = 'utf-8' if self._bom else 'cp1252'
        # Split the bytes rather than the text: `str.splitlines()` would also split
        # at characters like U+2028 that SongBeamer does not take as line breaks.
        lines = [
            line.decode(self._encoding, errors='surrogateescape')
            for line in content.removeprefix(self._bom).splitlines(keepends=True)
        ]
        header_length = next(
            (idx for idx, line in enumerate(lines) if not line.startswith('#')),
            len(lines),
        )
        self.header = lines[:header_length]
        self.body = lines[header_length:]
        # Added lines end like the first line of the file does.
        first_line = lines[0] if lines else ''
        self._newline = first_line.removeprefix(first_line.rstrip('\r\n')) or '\n'

    @classmethod
    def read(cls, sng_file: pathlib.Path) -> typing.Self:
        return cls(sng_file.read_bytes())

    def write(self, sng_file: pathlib.Path) -> None:
        with atomic_replace(sng_file) as tmp_file:
            tmp_file.write_bytes(bytes(self))

    def __bytes__(self) -> bytes:
        return self._bom + ''.join(self.header + self.body).encode(
            self._encoding, errors='surrogateescape'
        )

    @classmethod
    def has_background_image(cls, header: list[str]) -> bool:
        """Whether the `header` lines of a song file set a background image."""
        return any(line.startswith(cls.BACKGROUND_IMAGE_KEY) for line in header)

    def set_background_image(self, image: pathlib.Path) -> None:
        """Insert a `#BackgroundImage` line at the end of the header.

        The absolute path is used, as a relative one would be resolved against the
        background folder of SongBeamer instead of against the song file. Raises
        `UnicodeEncodeError` if `image` cannot be represented in the encoding of the
        file, without having changed the header.
        """
        line = f'{self.BACKGROUND_IMAGE_KEY}{image.absolute()}'
        _ = line.encode(self._encoding)  # fail before changing anything
        if self.header and not self.header[-1].endswith(('\r', '\n')):
            # A file consisting of nothing but a header without a final line break.
            self.header[-1] += self._newline
        self.header.append(line + self._newline)


class SongBackgrounds:
    """Give the songs of an agenda without a background a random one from Immich."""

    def __init__(self, config: Configuration, immich: ImmichAPI) -> None:
        self._immich = immich
        self._background_dir = config.songbeamer.output_dir / Subfolder.BACKGROUNDS

    def add_missing(self, agenda_items: list[Item]) -> None:
        # A song appearing twice in the agenda refers to the same .sng file, which has
        # its background set after the first visit already.
        sng_files = list(
            dict.fromkeys(
                pathlib.Path(item.filename)
                for item in agenda_items
                if item.type == AgendaItemType.SONG and item.filename
            )
        )
        with Progress('Background images', total=len(sng_files)) as progress:
            for sng_file in sng_files:
                with progress.do_progress(
                    sng_file, description=f'Background image: {sng_file.stem}'
                ):
                    try:
                        sng = SngFile.read(sng_file)
                        if SngFile.has_background_image(sng.header):
                            continue
                        if image := self._immich.download_random_background(
                            self._background_dir
                        ):
                            logger.info(
                                'Setting background image "%s" for "%s"',
                                image.name,
                                sng_file.name,
                            )
                            sng.set_background_image(image)
                            sng.write(sng_file)
                    except (OSError, UnicodeEncodeError) as e:
                        logger.warning(
                            'Failed to set background image for "%s": %s', sng_file, e
                        )
