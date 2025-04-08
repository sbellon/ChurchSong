import dataclasses

from textual import on
from textual.app import App, ComposeResult
from textual.color import Color
from textual.containers import (
    Center,
    Container,
    Horizontal,
    Middle,
    Vertical,
    VerticalScroll,
)
from textual.content import Content
from textual.events import Key, Mount
from textual.screen import ModalScreen
from textual.style import Style
from textual.widgets import Button, Checkbox, Label, Static

from churchsong.configuration import Configuration


@dataclasses.dataclass
class DownloadSelection:
    schedule: bool
    songs: bool
    files: bool
    slides: bool


class FocusCheckbox(Checkbox):
    DEFAULT_CSS = """
    FocusCheckbox:focus {
        border: round $primary;
        color: $primary;
    }
    """

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
            _('Create selected files and start SongBeamer')
            if self.screen.query_one('#schedule', Checkbox).value
            else _('Create selected files')
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
        border: round $surface;
    }
    FocusButton:focus {
        border: round $primary;
    }
    """

    @on(Key)
    def handle_space(self, event: Key) -> None:
        match event.key:
            case 'space':
                self.post_message(Button.Pressed(self))
                event.stop()
            case _:
                pass


class Header(Horizontal):
    DEFAULT_CSS = """
    Header {
        height: 5;
        dock: top;
        background: darkblue;
    }
    Vertical {
        align: center middle;
        border: round white;
    }
    #left {
        width: 75%;
    }
    #right {
        width: 25%;
    }
    Label {
        text-style: bold italic;
        color: white;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id='left'):
            yield Label(id='header_label_left')
        with Vertical(id='right'):
            yield Label(id='header_label_right')


class Footer(Horizontal):
    DEFAULT_CSS = """
    Footer {
        height: 5;
        dock: bottom;
        background: darkblue;
        border: round white;
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
        match event.key:
            case 'space':
                self.post_message(Button.Pressed(self.query_one(Button)))
                event.stop()
            case _:
                pass

    @on(Button.Pressed, '#exit')
    def exit_app(self) -> None:
        self.app.exit()


class InteractiveScreen(App[DownloadSelection]):
    def __init__(self, config: Configuration) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        yield Header()
        with Center(), Middle():
            yield FocusCheckbox(id='schedule', unicode=self.config.use_unicode_font)
            yield FocusCheckbox(id='songs', unicode=self.config.use_unicode_font)
            yield FocusCheckbox(id='files', unicode=self.config.use_unicode_font)
            yield FocusCheckbox(id='slides', unicode=self.config.use_unicode_font)
            yield FocusButton(id='submit')
        yield Footer()

    @on(Mount)
    def initialize(self) -> None:
        self.query_one('#header_label_left', Label).update(self.config.package_name)
        current_version = self.config.version
        latest_version = self.config.latest_version
        update_available = latest_version and latest_version != current_version
        version = (
            current_version
            if not update_available
            else _('Update available\nCurrent version: {}\nLatest version: {}').format(
                current_version, latest_version
            )
        )
        self.query_one('#header_label_right', Label).update(version)
        footer_text = _(
            'Typically you want all options selected, but you can also disable parts '
            'if you already made local changes in a running SongBeamer instance and '
            'do not want to overwrite them.\n'
            'Use the Mouse or Cursor Keys and Space/Enter to (de)select and press '
            'Enter to confirm.'
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

    @on(Key)
    def handle_focus(self, event: Key) -> None:
        match event.key:
            case 'down':
                self.screen.focus_next()
                event.stop()
            case 'up':
                self.screen.focus_previous()
                event.stop()
            case _:
                pass

    @on(Button.Pressed, '#submit')
    def handle_button(self, _message: Button.Pressed) -> None:
        checkboxes = self.app.query(Checkbox)
        ds = DownloadSelection(**{cb.id: cb.value for cb in checkboxes if cb.id})
        self.app.exit(ds)
