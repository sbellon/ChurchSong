# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import sys

# The module under test only exists on Windows, and so do these tests - the
# same platform guard as in churchsong/songbeamer/windows.py keeps both the
# type checker and the test collection quiet everywhere else.
if sys.platform == 'win32':
    import ctypes
    import os
    import typing

    import psutil

    from churchsong.songbeamer import windows

    if typing.TYPE_CHECKING:
        import pathlib

        import pytest

    class FakeProcess:
        def __init__(self, name: str) -> None:
            self.info: dict[str, str] = {'name': name}

    def install_processes(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
        def process_iter(_attrs: list[str]) -> list[FakeProcess]:
            return [FakeProcess(name) for name in names]

        monkeypatch.setattr(psutil, 'process_iter', process_iter)

    class FakeUser32:
        """The handful of user32 calls the module makes."""

        def __init__(self, titles: dict[int, str] | None = None) -> None:
            self._titles = titles or {}
            self.message_boxes: list[tuple[str, str]] = []
            self.foreground: int | None = None

        def MessageBoxW(  # noqa: N802 (win32 API name)
            self, _hwnd: int, message: str, title: str, _flags: int
        ) -> int:
            self.message_boxes.append((title, message))
            return 1

        def GetWindowTextLengthW(self, hwnd: int) -> int:  # noqa: N802 (win32 API name)
            return len(self._titles.get(hwnd, ''))

        def GetWindowTextW(  # noqa: N802 (win32 API name)
            self, hwnd: int, buffer: ctypes.Array[ctypes.c_wchar], _length: int
        ) -> int:
            buffer.value = self._titles.get(hwnd, '')
            return len(buffer.value)

        def EnumWindows(  # noqa: N802 (win32 API name)
            self, callback: typing.Callable[[int, object], bool], lparam: object
        ) -> int:
            for hwnd in self._titles:
                if not callback(hwnd, lparam):
                    break
            return 1

        def SetForegroundWindow(self, hwnd: ctypes.c_void_p) -> int:  # noqa: N802 (win32 API name)
            self.foreground = hwnd.value
            return 1

    class FakeKernel32:
        def __init__(self) -> None:
            self.last_error: int | None = None

        def SetLastError(self, code: int) -> None:  # noqa: N802 (win32 API name)
            self.last_error = code

    def install_windll(
        monkeypatch: pytest.MonkeyPatch, user32: FakeUser32
    ) -> FakeKernel32:
        kernel32 = FakeKernel32()
        monkeypatch.setattr(ctypes.windll, 'user32', user32, raising=False)
        monkeypatch.setattr(ctypes.windll, 'kernel32', kernel32, raising=False)
        return kernel32

    def test_is_songbeamer_running_finds_the_process(
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        install_processes(monkeypatch, 'explorer.exe', 'SongBeamer.exe')
        assert windows.is_songbeamer_running()

    def test_is_songbeamer_running_without_the_process(
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        install_processes(monkeypatch, 'explorer.exe', 'powershell.exe')
        assert not windows.is_songbeamer_running()

    def test_start_songbeamer_opens_the_schedule_in_the_output_dir(
        monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        opened: list[tuple[str, pathlib.Path]] = []

        def startfile(path: str, *, cwd: pathlib.Path) -> None:
            opened.append((path, cwd))

        monkeypatch.setattr(os, 'startfile', startfile)
        windows.start_songbeamer(tmp_path)
        # SongBeamer is started by opening its schedule with the shell.
        assert opened == [('Schedule.col', tmp_path)]

    def test_open_message_box_passes_title_and_message(
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user32 = FakeUser32()
        install_windll(monkeypatch, user32)
        windows.open_message_box('ChurchSong', 'SongBeamer is already running.')
        assert user32.message_boxes == [
            ('ChurchSong', 'SongBeamer is already running.')
        ]

    def test_bring_songbeamer_window_to_front_picks_the_matching_window(
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user32 = FakeUser32({0x1000: 'Some Editor', 0x2000: 'SongBeamer 6'})
        kernel32 = install_windll(monkeypatch, user32)
        windows.bring_songbeamer_window_to_front()
        assert user32.foreground == 0x2000
        assert kernel32.last_error == 0

    def test_bring_songbeamer_window_to_front_without_a_match(
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user32 = FakeUser32({0x1000: 'Some Editor', 0x2000: ''})
        install_windll(monkeypatch, user32)
        windows.bring_songbeamer_window_to_front()
        assert user32.foreground is None
