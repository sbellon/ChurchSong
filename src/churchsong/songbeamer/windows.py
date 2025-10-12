# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import sys

if sys.platform == 'win32':
    import ctypes
    import os
    import subprocess
    import typing

    import psutil

    if typing.TYPE_CHECKING:
        import pathlib

    def is_songbeamer_running() -> bool:
        return any(
            proc.name() == 'SongBeamer.exe'
            for proc in psutil.process_iter(['name'])  # pyright: ignore[reportUnknownMemberType]
        )

    def open_message_box(title: str, message: str) -> None:
        ctypes.windll.user32.MessageBoxW(0, message, title, 0)

    def bring_songbeamer_window_to_front() -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        def get_window_title(hwnd: int) -> str:
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                return buffer.value
            return ''

        def enum_windows_callback(hwnd: int, lparam: int) -> bool:
            title = get_window_title(hwnd)
            if 'songbeamer' in title.lower():
                kernel32.SetLastError(0)
                ctypes.cast(lparam, ctypes.POINTER(ctypes.c_void_p))[0] = hwnd
                return False
            return True

        hwnd_match = ctypes.c_void_p(0)
        EnumWindowsProc = ctypes.WINFUNCTYPE(  # noqa: N806
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
        )
        user32.EnumWindows(
            EnumWindowsProc(enum_windows_callback), ctypes.byref(hwnd_match)
        )
        if hwnd_match.value:
            user32.SetForegroundWindow(hwnd_match)

    def start_songbeamer(cwd: pathlib.Path) -> None:
        subprocess.run(
            [os.environ.get('COMSPEC', 'cmd'), '/C', 'start Schedule.col'],
            check=True,
            cwd=cwd,
        )
