import dataclasses

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Button, Checkbox, Label


@dataclasses.dataclass
class DownloadSelection:
    schedule: bool
    songs: bool
    files: bool
    slides: bool


class UnifiedCheckbox(Checkbox):
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

    async def on_click(self, event: events.Click) -> None:
        if event.button == 0:  # left button
            self.value = not self.value
            self.post_message(self.Changed(self, self.value))
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


class InteractiveScreen(App[DownloadSelection]):
    CSS = """
    Vertical {
        padding: 2;
        align: center middle;
        height: auto;
    }

    Label {
        padding-top: 2;
        color: green;
    }

    #checkbox_title {
        color: red;
        padding-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(_('ChurchSong Startmenu'), id='checkbox_title')

            yield UnifiedCheckbox(
                _('Download SongBeamer schedule and launch SongBeamer'),
                id='schedule',
                value=True,
            )
            yield UnifiedCheckbox(_('Download song files'), id='songs', value=True)
            yield UnifiedCheckbox(_('Download event files'), id='files', value=True)
            yield UnifiedCheckbox(
                _('Create PointPoint slides'), id='slides', value=True
            )

            yield UnifiedButton(_('Execute'), id='submit')

    def on_mount(self) -> None:
        self.query_one('#submit').focus()

    def on_unified_button_selected(self, _message: UnifiedButton.Selected) -> None:
        checkboxes = self.app.query(UnifiedCheckbox)
        ds = DownloadSelection(**{cb.id: cb.value for cb in checkboxes if cb.id})
        self.app.exit(ds)
