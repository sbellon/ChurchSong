# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import asyncio
import threading
import time
import typing

import packaging.version
import pytest
from textual.color import Color
from textual.widgets import Label

from churchsong.configuration import Configuration
from churchsong.interactivescreen import (
    DownloadSelection,
    FocusButton,
    FocusCheckbox,
    InteractiveScreen,
)
from tests.conftest import make_config

if typing.TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from textual.pilot import Pilot
    from textual.widget import Widget

    type AppPilot = Pilot[DownloadSelection]
    type Scenario = Callable[[InteractiveScreen, AppPilot], Awaitable[None]]

# Large enough to fit header, all checkboxes, button and both footers without
# the ScrollableCenterMiddle container starting to scroll.
TERMINAL_SIZE = (80, 30)

CHECKBOX_IDS = ('schedule', 'songs', 'files', 'slides', 'songsheets')

# Long enough to bridge a busy machine, short enough to not stall the suite if the
# version check never reaches the header at all.
VERSION_CHECK_TIMEOUT = 5.0


@pytest.fixture(autouse=True)
def offline_version_check(monkeypatch: pytest.MonkeyPatch) -> None:
    # The header shows an "update available" hint, which would otherwise make
    # every single test query PyPI over the network.
    monkeypatch.setattr(
        Configuration, 'later_version_available', property(lambda _self: None)
    )


def run_scenario(scenario: Scenario) -> InteractiveScreen:
    """Drive the real InteractiveScreen through a headless Textual test run."""
    app = InteractiveScreen(make_config())

    async def main() -> None:
        async with app.run_test(size=TERMINAL_SIZE) as pilot:
            await scenario(app, pilot)

    asyncio.run(main())
    return app


async def wait_for_update_notice(pilot: AppPilot, label: Label) -> str:
    """Wait for the version check, which runs in its own thread, to reach the header."""
    deadline = time.monotonic() + VERSION_CHECK_TIMEOUT
    while 'Update available' not in (text := str(label.content)):
        assert time.monotonic() < deadline, 'version check never updated the header'
        await asyncio.sleep(0.01)
        await pilot.pause()
    return text


def has_visible_border(widget: Widget) -> bool:
    """Whether the widget is visually outlined.

    Both FocusCheckbox and FocusButton draw their resting border in their own
    background color, so it only becomes visible once it deviates from it.
    """
    return widget.styles.border.top[1] != widget.styles.background


def highlighted(app: InteractiveScreen) -> set[str | None]:
    """The ids of all interactive widgets that currently show a border."""
    widgets = [*app.query(FocusCheckbox), *app.query(FocusButton)]
    return {widget.id for widget in widgets if has_visible_border(widget)}


def test_mouse_hover_outlines_checkbox_and_releases_it_again() -> None:
    async def scenario(app: InteractiveScreen, pilot: AppPilot) -> None:
        schedule = app.query_one('#schedule', FocusCheckbox)
        app.screen.set_focus(None)
        await pilot.pause()
        assert not has_visible_border(schedule)

        await pilot.hover('#schedule')
        await pilot.pause()
        assert schedule.mouse_hover
        assert has_visible_border(schedule)

        # Moving on to another widget must take the border away again.
        await pilot.hover('#songs')
        await pilot.pause()
        assert not schedule.mouse_hover
        assert not has_visible_border(schedule)
        assert highlighted(app) == {'songs'}

    run_scenario(scenario)


def test_hover_border_uses_rounded_primary_color() -> None:
    async def scenario(app: InteractiveScreen, pilot: AppPilot) -> None:
        app.screen.set_focus(None)
        await pilot.pause()
        await pilot.hover('#schedule')
        await pilot.pause()
        schedule = app.query_one('#schedule', FocusCheckbox)
        assert schedule.styles.border.top == (
            'round',
            Color.parse(app.current_theme.primary),
        )

    run_scenario(scenario)


def test_cursor_keys_drop_hover_until_the_mouse_moves_again() -> None:
    async def scenario(app: InteractiveScreen, pilot: AppPilot) -> None:
        # Park the keyboard focus somewhere else, so that the border seen on
        # #schedule can only ever come from the mouse hover.
        app.query_one('#songs', FocusCheckbox).focus()
        await pilot.pause()
        schedule = app.query_one('#schedule', FocusCheckbox)
        await pilot.hover('#schedule')
        await pilot.pause()
        assert schedule.mouse_hover
        assert has_visible_border(schedule)

        await pilot.press('down')
        await pilot.pause()
        assert not schedule.mouse_hover
        assert not has_visible_border(schedule)

        # ... but the hover comes back as soon as the mouse is moved again.
        await pilot.hover('#schedule', offset=(1, 0))
        await pilot.pause()
        assert schedule.mouse_hover
        assert has_visible_border(schedule)

    run_scenario(scenario)


def test_cursor_keys_drop_hover_of_the_button_as_well() -> None:
    async def scenario(app: InteractiveScreen, pilot: AppPilot) -> None:
        app.query_one('#schedule', FocusCheckbox).focus()
        await pilot.pause()
        submit = app.query_one('#submit', FocusButton)
        await pilot.hover('#submit')
        await pilot.pause()
        assert submit.is_hovered
        assert has_visible_border(submit)

        await pilot.press('down')
        await pilot.pause()
        assert not submit.is_hovered
        assert not has_visible_border(submit)

    run_scenario(scenario)


def test_button_hover_is_released_when_the_mouse_leaves() -> None:
    async def scenario(app: InteractiveScreen, pilot: AppPilot) -> None:
        app.screen.set_focus(None)
        await pilot.pause()
        submit = app.query_one('#submit', FocusButton)
        assert not submit.is_hovered
        assert not has_visible_border(submit)

        await pilot.hover('#submit')
        await pilot.pause()
        assert submit.is_hovered
        assert has_visible_border(submit)

        await pilot.hover('#schedule')
        await pilot.pause()
        assert not submit.is_hovered
        assert not has_visible_border(submit)

    run_scenario(scenario)


def test_only_the_clicked_checkbox_stays_outlined() -> None:
    async def scenario(app: InteractiveScreen, pilot: AppPilot) -> None:
        app.query_one('#songs', FocusCheckbox).focus()
        await pilot.pause()
        assert highlighted(app) == {'songs'}

        await pilot.click('#schedule')
        await pilot.pause()
        assert app.query_one('#schedule', FocusCheckbox).has_focus
        assert not app.query_one('#songs', FocusCheckbox).has_focus
        assert highlighted(app) == {'schedule'}

    run_scenario(scenario)


def test_cursor_key_navigation_outlines_exactly_one_widget() -> None:
    async def scenario(app: InteractiveScreen, pilot: AppPilot) -> None:
        # Leave the mouse hovering over a widget the cursor keys pass through,
        # to make sure it does not contribute a second border.
        await pilot.hover('#slides')
        await pilot.pause()
        for _ in range(len(CHECKBOX_IDS) + 1):
            await pilot.press('down')
            await pilot.pause()
            assert len(highlighted(app)) == 1

    run_scenario(scenario)


def test_click_toggles_checkbox_and_space_toggles_focused_checkbox() -> None:
    async def scenario(app: InteractiveScreen, pilot: AppPilot) -> None:
        schedule = app.query_one('#schedule', FocusCheckbox)
        assert schedule.value  # all actions are enabled by default

        await pilot.click('#schedule')
        await pilot.pause()
        assert not schedule.value

        # The click focused it, so the keyboard can carry straight on.
        await pilot.press('space')
        await pilot.pause()
        assert schedule.value

    run_scenario(scenario)


def test_submit_button_reflects_the_checkbox_selection() -> None:
    async def scenario(app: InteractiveScreen, pilot: AppPilot) -> None:
        submit = app.query_one('#submit', FocusButton)
        with_songbeamer = str(submit.label)
        assert not submit.disabled

        # Unticking the schedule drops the SongBeamer launch from the label.
        await pilot.click('#schedule')
        await pilot.pause()
        assert str(submit.label) != with_songbeamer

        # With nothing left to do, the button must not be pressable.
        for checkbox_id in CHECKBOX_IDS:
            checkbox = app.query_one(f'#{checkbox_id}', FocusCheckbox)
            if checkbox.value:
                await pilot.click(f'#{checkbox_id}')
                await pilot.pause()
        assert submit.disabled

    run_scenario(scenario)


def test_pressing_submit_returns_the_selection() -> None:
    async def scenario(app: InteractiveScreen, pilot: AppPilot) -> None:
        await pilot.click('#songs')
        await pilot.pause()
        assert not app.query_one('#songs', FocusCheckbox).value
        await pilot.click('#submit')

    app = run_scenario(scenario)
    assert app.return_value == DownloadSelection(
        schedule=True, songs=False, files=True, slides=True, songsheets=True
    )


def test_space_on_the_submit_button_returns_the_selection() -> None:
    async def scenario(app: InteractiveScreen, pilot: AppPilot) -> None:
        # The submit button holds the focus right from the start.
        assert app.focused is app.query_one('#submit', FocusButton)
        await pilot.press('space')

    app = run_scenario(scenario)
    assert app.return_value == DownloadSelection(
        schedule=True, songs=True, files=True, slides=True, songsheets=True
    )


def test_backwards_cursor_navigation_outlines_exactly_one_widget() -> None:
    async def scenario(app: InteractiveScreen, pilot: AppPilot) -> None:
        # Leave the mouse hovering over a widget the cursor keys pass through,
        # to make sure it does not contribute a second border.
        await pilot.hover('#slides')
        await pilot.pause()
        for _ in range(len(CHECKBOX_IDS) + 1):
            await pilot.press('up')
            await pilot.pause()
            assert len(highlighted(app)) == 1

    run_scenario(scenario)


def test_header_points_out_an_available_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        Configuration,
        'later_version_available',
        property(lambda _self: packaging.version.Version('99.0.0')),
    )

    async def scenario(app: InteractiveScreen, pilot: AppPilot) -> None:
        version_label = app.query_one('#header_label_right', Label)
        text = await wait_for_update_notice(pilot, version_label)
        assert str(app.config.version) in text
        assert '99.0.0' in text
        assert version_label.styles.color == Color.parse(app.current_theme.accent)

    run_scenario(scenario)


def test_screen_is_usable_while_the_version_check_still_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answered = threading.Event()

    def blocking_check(_self: Configuration) -> packaging.version.Version:
        assert answered.wait(timeout=VERSION_CHECK_TIMEOUT), 'check was never released'
        return packaging.version.Version('99.0.0')

    monkeypatch.setattr(
        Configuration, 'later_version_available', property(blocking_check)
    )

    async def scenario(app: InteractiveScreen, pilot: AppPilot) -> None:
        # The check has not answered yet, but the screen is painted and takes keys.
        version_label = app.query_one('#header_label_right', Label)
        assert str(version_label.content) == str(app.config.version)
        await pilot.press('up')
        await pilot.pause()
        assert app.focused is app.query_one('#songsheets', FocusCheckbox)

        answered.set()
        assert '99.0.0' in await wait_for_update_notice(pilot, version_label)

    run_scenario(scenario)
