# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import contextlib
import os
import pathlib
import re
import tempfile
import typing

# Characters Windows rejects in a filename, plus the control characters that are
# illegal in a path component everywhere.
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Device names Windows reserves, with or without an extension: `CON`, `CON.pdf` and
# even `CON.tar.gz` all address the console, so the check looks at the part before the
# first dot.
_RESERVED_NAMES = frozenset(
    {'CON', 'PRN', 'AUX', 'NUL'}
    | {f'COM{n}' for n in range(1, 10)}
    | {f'LPT{n}' for n in range(1, 10)}
)

# Short enough that a long output directory still leaves the whole path within the 260
# characters of `MAX_PATH` on systems without long path support.
MAX_FILENAME_LENGTH = 128


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


def safe_filename(filename: str, *, max_length: int = MAX_FILENAME_LENGTH) -> str:
    """Turn a server-supplied name into one that can be created on Windows.

    Reduces the name to its last component, so that a name like `../../evil` cannot
    escape the directory it is meant to be written into, then applies the Windows
    filename rules the server does not know about: illegal characters become `_`,
    trailing dots and spaces are dropped, a reserved device name gets prefixed, and an
    overlong name is truncated while keeping its extension. Returns `unnamed` if
    nothing usable is left.
    """
    name = _ILLEGAL_CHARS.sub('_', pathlib.PureWindowsPath(filename).name).rstrip('. ')
    if name.partition('.')[0].upper() in _RESERVED_NAMES:
        name = f'_{name}'
    if len(name) > max_length:
        # Keep the extension, but only while it leaves room for a stem in front of it -
        # an absurdly long one is worth less than a recognizable name.
        suffix = pathlib.PureWindowsPath(name).suffix
        if len(suffix) > max_length // 2:
            suffix = ''
        name = f'{name[: max_length - len(suffix)].rstrip(". ")}{suffix}'
    return name or 'unnamed'
