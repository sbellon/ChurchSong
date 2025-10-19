# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import dataclasses
import typing

from textual import on
from textual.app import App
from textual.color import Color
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.events import Blur, Enter, Focus, Key, Leave, Mount
from textual.reactive import reactive
from textual.style import Style
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Footer, Label, Static

from churchsong.configuration import Configuration

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import ComposeResult
    from textual.binding import BindingType
    from textual.css.types import EdgeType

    _: Callable[[str], str]


@dataclasses.dataclass
class DownloadSelection:
    schedule: bool
    songs: bool
    files: bool
    slides: bool
    songsheets: bool


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
        &:blur:hover {
            & > .toggle--label {
                background: $background;
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
    is_hovered = reactive(default=False)

    @dataclasses.dataclass
    class Style:
        color: Color
        background: Color
        border: tuple[EdgeType, Color | str]

    def __init__(self, **kwargs: typing.Any) -> None:  # noqa: ANN401
        super().__init__(**kwargs)
        self.app: App[DownloadSelection]
        self.styles_map: dict[str, FocusButton.Style] = {
            'default': FocusButton.Style(
                color=self.styles.color,
                background=self.styles.background,
                border=('round', self.styles.background),
            ),
            'hover': FocusButton.Style(
                color=self.styles.color,
                background=self.styles.background,
                border=('round', self.app.current_theme.primary),
            ),
            'focus': FocusButton.Style(
                color=self.styles.color,
                background=self.styles.background,
                border=('round', self.app.current_theme.primary),
            ),
        }
        self.apply_style('default')

    def apply_style(self, style_name: str) -> None:
        if style := self.styles_map.get(style_name):
            self.styles.color = style.color
            self.styles.background = style.background
            self.styles.border = style.border

    @on(Enter)
    def hover_enter(self, _event: Enter) -> None:
        self.is_hovered = True
        self.apply_style('hover')

    @on(Leave)
    def hover_leave(self, _event: Leave) -> None:
        self.is_hovered = False
        self.apply_style('focus' if self.has_focus else 'default')

    @on(Focus)
    def focus_enter(self, _event: Focus) -> None:
        self.apply_style('focus')

    @on(Blur)
    def focus_leave(self, _event: Blur) -> None:
        self.apply_style('hover' if self.is_hovered else 'default')

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


class InteractiveScreen(App[DownloadSelection]):
    BINDINGS: typing.ClassVar[list[BindingType]] = [
        ('up', 'focus_previous', 'Up'),
        ('down', 'focus_next', 'Down'),
        ('^q', 'quit', 'Quit'),
    ]

    def __init__(self, config: Configuration) -> None:
        super().__init__()
        self.app: App[DownloadSelection]
        self.config = config

    def compose(self) -> ComposeResult:
        use_unicode_font = self.config.general.interactive.use_unicode_font
        with Vertical():
            yield Header()
            with ScrollableCenterMiddle():
                yield FocusCheckbox(id='schedule', unicode=use_unicode_font)
                yield FocusCheckbox(id='songs', unicode=use_unicode_font)
                yield FocusCheckbox(id='files', unicode=use_unicode_font)
                yield FocusCheckbox(id='slides', unicode=use_unicode_font)
                yield FocusCheckbox(id='songsheets', unicode=use_unicode_font)
                yield FocusButton(id='submit')
            yield NoticeFooter()
            yield Footer(show_command_palette=False)

    @on(Mount)
    def initialize(self) -> None:
        self.theme = 'textual-dark'

        self.query_one('#header_label_left', Label).update(Configuration.package_name)
        version_label = self.query_one('#header_label_right', Label)
        version = self.config.version
        if later_version := self.config.later_version_available:
            version = _(
                'Update available\nCurrent version: {}\nLatest version: {}'
            ).format(version, later_version)
            version_label.styles.color = self.current_theme.accent
        version_label.update(str(version))
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
        self.query_one('#songsheets', Checkbox).label = _(
            'Create and upload PDF song sheets to ChurchTools'
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
