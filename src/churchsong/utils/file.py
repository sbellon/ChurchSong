# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import contextlib
import os
import pathlib
import tempfile
import typing


@contextlib.contextmanager
def atomic_replace(filepath: pathlib.Path) -> typing.Generator[pathlib.Path]:
    """Yield a temporary path to write to, then move it onto `filepath`.

    The move is atomic on both Windows and POSIX, so an interrupted or failing write
    leaves the previous contents of `filepath` in place instead of a truncated file.
    The temporary file is created next to `filepath` to keep the move within one
    filesystem, and is removed again if anything goes wrong.
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fd, tempname = tempfile.mkstemp(
        dir=filepath.parent, prefix=f'.{filepath.name}.', suffix='.tmp'
    )
    os.close(fd)  # the caller opens the path itself, e.g. in text mode
    temppath = pathlib.Path(tempname)
    try:
        yield temppath
        temppath.replace(filepath)
    except BaseException:
        temppath.unlink(missing_ok=True)
        raise
