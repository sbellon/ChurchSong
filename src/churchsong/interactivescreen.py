# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import dataclasses
import typing

from textual import on
from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.color import Color
from textual.containers import Center, Container, Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.events import Key, Mount
from textual.screen import ModalScreen
from textual.style import Style
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Footer, Label, Static

from churchsong.configuration import Configuration


@dataclasses.dataclass
class DownloadSelection:
    schedule: bool
    songs: bool
    files: bool
    slides: bool


class ScrollableCenterMiddle(Widget):
    DEFAULT_CSS = """
    ScrollableCenterMiddle {
        width: 1fr;
        height: 1fr;
        layout: vertical;
        overflow: auto auto;
        align: center middle;
    }
    """


class FocusCheckbox(Checkbox):
    DEFAULT_CSS = """
    FocusCheckbox {
        background: $background;
        border: $background;
        &:focus {
            border: round $primary;
            & > .toggle--label {
                color: $background;
                background: $foreground;
            }
        }
        & > .toggle--button {
            background: $background;
        }
        &.-on > .toggle--button {
            background: $background;
        }
    }
    """

    BINDINGS: typing.ClassVar[list[BindingType]] = [
        ('space | return | click', 'toggle_button', 'Toggle'),
    ]

    def __init__(
        self,
        *,
        id: str | None = None,  # noqa: A002 (introduced by ToggleButton)
        unicode: bool = False,
    ) -> None:
        super().__init__(id=id, value=True)
        self.char_on = '✅' if unicode else '■'
        self.char_off = '❌' if unicode else ' '

    @on(Checkbox.Changed)
    def handle_checkbox(self, _event: Checkbox.Changed) -> None:
        submit_button = self.screen.query_one('#submit', Button)
        submit_button.label = (
            _('Execute: Create selected files and start SongBeamer')
            if self.screen.query_one('#schedule', Checkbox).value
            else _('Execute: Create selected files')
        )
        submit_button.disabled = not any(
            cb.value for cb in self.screen.query(FocusCheckbox)
        )
        submit_button.refresh(layout=True)

    @property
    def _button(self) -> Content:
        # Clone of property textual.widgets.ToggleButton._button()
        button_style = self.get_visual_style('toggle--button')
        checkmark_style = Style(
            foreground=Color.parse('lightgreen' if self.value else 'red'),
            background=button_style.background,
        )
        return Content.assemble(
            (self.char_on if self.value else self.char_off, checkmark_style),
        )


class FocusButton(Button):
    DEFAULT_CSS = """
    FocusButton {
        background: $background;
        border: $background;
        &:focus {
            color: $foreground;
            background: $background;
            border: round $primary;
        }
        &:hover {
            background: $background;
            border: round $primary;
        }
    }
    """

    # The key binding does *not* activate space, therefore we need the @on(Key) below.
    # But it makes for a consistent appearance w.r.t. the FocusCheckbox key bindings.
    BINDINGS: typing.ClassVar[list[BindingType]] = [
        ('space | return | click', 'nonexisting_dummy', 'Select'),
    ]

    @on(Key)
    def handle_space(self, event: Key) -> None:
        if event.key == 'space':
            self.press()
            event.stop()


class Header(Horizontal):
    DEFAULT_CSS = """
    Header {
        height: 3;
        dock: top;
    }
    Vertical {
        align: center middle;
    }
    #left {
        width: 1fr;
        background: $primary;
    }
    #right {
        min-width: 1%;
        width: auto;
        background: $secondary;
    }
    Label {
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id='left'):
                yield Label(id='header_label_left')
            with Vertical(id='right'):
                yield Label(id='header_label_right')


class NoticeFooter(Horizontal):
    DEFAULT_CSS = """
    NoticeFooter {
        height: 2;
        background: $primary;
        & > VerticalScroll {
            margin: 0 1;
        }
    }
    """

    def compose(self) -> ComposeResult:
        yield VerticalScroll(Static(id='footer'), can_focus=False)


class ExitScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    ExitScreen {
        align: center middle;
    }

    ExitScreen > Container {
        width: 50%;
        height: auto;
        border: thick $background 80%;
        background: $surface;
    }

    ExitScreen > Container > Label {
        width: 100%;
        content-align-horizontal: center;
        margin: 1 2;
    }

    ExitScreen > Container > Center > Button {
        margin: 2 4;
    }
    """

    def compose(self) -> ComposeResult:
        with Container():
            yield Label('Something went wrong, we have to quit!')
            with Center():
                yield Button('Exit', id='exit', variant='error')

    @on(Key)
    def handle_space(self, event: Key) -> None:
        if event.key == 'space':
            self.query_one(Button).press()
            event.stop()

    @on(Button.Pressed, '#exit')
    def exit_app(self) -> None:
        self.app.exit()


class InteractiveScreen(App[DownloadSelection]):
    BINDINGS: typing.ClassVar[list[BindingType]] = [
        ('up', 'focus_previous', 'Up'),
        ('down', 'focus_next', 'Down'),
        ('^q', 'quit', 'Quit'),
    ]

    def __init__(self, config: Configuration) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Header()
            with ScrollableCenterMiddle():
                yield FocusCheckbox(id='schedule', unicode=self.config.use_unicode_font)
                yield FocusCheckbox(id='songs', unicode=self.config.use_unicode_font)
                yield FocusCheckbox(id='files', unicode=self.config.use_unicode_font)
                yield FocusCheckbox(id='slides', unicode=self.config.use_unicode_font)
                yield FocusButton(id='submit')
            yield NoticeFooter()
            yield Footer(show_command_palette=False)

    @on(Mount)
    def initialize(self) -> None:
        self.theme = 'textual-dark'

        self.query_one('#header_label_left', Label).update(self.config.package_name)
        version_label = self.query_one('#header_label_right', Label)
        version = self.config.version
        latest_version = self.config.latest_version
        if latest_version and latest_version != version:
            version = _(
                'Update available\nCurrent version: {}\nLatest version: {}'
            ).format(version, latest_version)
            version_label.styles.color = self.current_theme.accent
        version_label.update(version)
        footer_text = _(
            'Please make your desired choice. By default, all actions are activated.'
        )
        self.query_one('#footer', Static).update(footer_text)

        # Initialize Checkbox labels.
        schedule_checkbox = self.query_one('#schedule', Checkbox)
        schedule_checkbox.label = _(
            'Get SongBeamer schedule from ChurchTools and launch SongBeamer'
        )
        self.query_one('#songs', Checkbox).label = _(
            'Download song files from ChurchTools'
        )
        self.query_one('#files', Checkbox).label = _(
            'Download event files from ChurchTools'
        )
        self.query_one('#slides', Checkbox).label = _(
            'Create PointPoint slides from ChurchTools data'
        )

        # Trigger Changed event on first Checkbox to initialize Button label.
        schedule_checkbox.post_message(Checkbox.Changed(schedule_checkbox, value=True))

        # Focus Button.
        self.query_one('#submit').focus()

    @on(Button.Pressed, '#submit')
    def handle_button(self, _message: Button.Pressed) -> None:
        checkboxes = self.app.query(Checkbox)
        ds = DownloadSelection(**{cb.id: cb.value for cb in checkboxes if cb.id})
        self.app.exit(ds)
