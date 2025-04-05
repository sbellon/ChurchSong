import dataclasses

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Center, Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Checkbox, Label, Static

from churchsong.configuration import Configuration


@dataclasses.dataclass
class DownloadSelection:
    schedule: bool
    songs: bool
    files: bool
    slides: bool


class UnifiedCheckbox(Checkbox):
    DEFAULT_CSS = """
    UnifiedCheckbox:focus {
        border: round $primary;
        color: $primary;
    }
    """
    BUTTON_INNER = '✓'

    async def on_key(self, event: events.Key) -> None:
        if event.key in ('enter', 'space'):
            self.value = not self.value
            self.post_message(self.Changed(self, self.value))
            event.stop()
        elif event.key == 'down':
            self.screen.focus_next()
            event.stop()
        elif event.key == 'up':
            self.screen.focus_previous()
            event.stop()


class UnifiedButton(Button):
    class Selected(Message):
        pass

    async def on_key(self, event: events.Key) -> None:
        if event.key in ('enter', 'space'):
            self.post_message(self.Selected())
            event.stop()
        elif event.key == 'down':
            self.screen.focus_next()
            event.stop()
        elif event.key == 'up':
            self.screen.focus_previous()
            event.stop()

    async def on_click(self, event: events.Click) -> None:
        self.post_message(self.Selected())
        event.stop()


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
            yield Label('Header1', id='header_label_left')
        with Vertical(id='right'):
            yield Label('Header2', id='header_label_right')


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
        yield Static('Footer', id='footer')


class InteractiveScreen(App[DownloadSelection]):
    DEFAULT_CSS = """
    Screen {
        align: center middle;
    }
    #submit {
        align: right middle;
    }
    """

    def __init__(self, config: Configuration) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        yield Header()

        with Center():
            yield UnifiedCheckbox(
                _('Get SongBeamer schedule from ChurchTools and launch SongBeamer'),
                id='schedule',
                value=True,
            )
            yield UnifiedCheckbox(
                _('Download song files from ChurchTools'),
                id='songs',
                value=True,
            )
            yield UnifiedCheckbox(
                _('Download event files from ChurchTools'),
                id='files',
                value=True,
            )
            yield UnifiedCheckbox(
                _('Create PointPoint slides from ChurchTools data'),
                id='slides',
                value=True,
            )
            yield UnifiedButton(_('Execute'), id='submit')

        yield Footer()

    def on_mount(self) -> None:
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
        self.query_one('#submit').focus()

    def on_unified_button_selected(self, _message: UnifiedButton.Selected) -> None:
        checkboxes = self.app.query(UnifiedCheckbox)
        ds = DownloadSelection(**{cb.id: cb.value for cb in checkboxes if cb.id})
        self.app.exit(ds)
