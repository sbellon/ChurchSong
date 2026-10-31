# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

"""Check the configured ChurchTools and Immich instances like an agenda run uses them.

Every step asks the servers what a run would, through the very same calls, but
writes nothing: neither song sheets nor tags are created. A step fails on an
exception, and is reported with a warning for every warning it logs, so that the
calls which degrade instead of raising cannot hide a problem either.

Fields the server marks deprecated are listed only if asked for, as notes that
leave the status alone: a user cannot act on them, and some are read on purpose.
"""

import contextlib
import dataclasses
import enum
import logging
import typing
import warnings

import requests
import rich
import rich.box
import rich.table
import rich.text

from churchsong.churchtools import ChurchToolsAPI, NoEventError
from churchsong.churchtools.events import ChurchToolsEvent
from churchsong.immich import ImmichAPI
from churchsong.utils.date import now
from churchsong.utils.progress import Progress

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from churchsong.churchtools import EventShort
    from churchsong.configuration import Configuration, ImmichConfig

logger = logging.getLogger(__name__)


class Status(enum.IntEnum):
    """The outcome of a step, ordered by severity.

    A step starts as `OK`, and `Result.add()` only ever raises its status, so a
    switched off feature has to rank above `OK`.
    """

    OK = enum.auto()
    OFF = enum.auto()
    WARN = enum.auto()
    FAIL = enum.auto()


STATUS_STYLE = {
    Status.OK: 'green',
    Status.OFF: 'dim',
    Status.WARN: 'yellow',
    Status.FAIL: 'red',
}


@dataclasses.dataclass
class Result:
    service: str
    name: str
    status: Status = Status.OK
    details: list[str] = dataclasses.field(default_factory=list[str])
    notes: list[str] = dataclasses.field(default_factory=list[str])

    def add(self, status: Status, detail: str) -> None:
        self.status = max(self.status, status)
        if detail not in self.details:  # e.g. the same warning for every song
            self.details.append(detail)


def _count(number: int, noun: str) -> str:
    return f'{number} {noun}' if number == 1 else f'{number} {noun}s'


class _WarningCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    @typing.override
    def emit(self, record: logging.LogRecord) -> None:
        # A feature skipped by `has_feature()` is reported by its own row already.
        if not hasattr(record, 'feature'):
            self.messages.append(record.getMessage())


class SelfCheck:
    def __init__(self, config: Configuration, *, deprecations: bool = False) -> None:
        """Check `config`, listing the deprecated fields if `deprecations` is set."""
        self._config = config
        self._deprecations = deprecations
        self.results: list[Result] = []
        # Listed once for the whole check: one for every song would bury the rest.
        self._seen_deprecations: set[str] = set()
        self._current = ('', '')
        # What the steps hand on to the ones after them. A step whose prerequisite
        # is missing is left out, without a row of its own.
        self._cta: ChurchToolsAPI | None = None
        self._event: EventShort | None = None
        self._cte: ChurchToolsEvent | None = None
        self._immich: tuple[ImmichAPI, ImmichConfig] | None = None

    def _plan(self) -> list[tuple[str, str, Callable[[], None]]]:
        """Every step in order: its service, its name, and what it does."""
        cta, immich = ChurchToolsAPI, ImmichAPI
        return [
            ('ChurchTools', 'connection', self._connect_churchtools),
            ('ChurchTools', 'next event', self._check_next_event),
            ('ChurchTools', 'service team', self._check_service_team),
            ('ChurchTools', 'song database', self._check_song_database),
            ('ChurchTools', cta.SONG_SHEETS.name, self._check_song_sheets),
            ('ChurchTools', cta.NICKNAMES.name, self._check_nicknames),
            ('ChurchTools', cta.APPOINTMENT_SLIDES.name, self._check_appointments),
            ('Immich', 'connection', self._connect_immich),
            ('Immich', immich.MEDIA_UPLOAD.name, self._check_media_upload),
            ('Immich', immich.TAG_CREATION.name, self._check_tag_creation),
            ('Immich', immich.BACKGROUNDS.name, self._check_backgrounds),
        ]

    def run(self) -> list[Result]:
        logger.info('Starting self check')
        # The warnings are what the check reports, so a stricter configured log
        # level must not drop them.
        level = self._config.log.level
        self._config.log.setLevel(min(level, logging.WARNING))
        try:
            plan = self._plan()
            # The first description sets the width for the step names to come,
            # which `Progress` cuts off beyond it.
            with Progress(
                'Checking the ChurchTools and Immich setup', total=len(plan)
            ) as progress:
                for service, name, step in plan:
                    with progress.do_progress(name, f'{service}: {name}'):
                        self._current = (service, name)
                        step()
        finally:
            self._config.log.setLevel(level)
        return self.results

    def report(self) -> bool:
        """Print the results, return whether no step failed."""
        table = rich.table.Table(box=rich.box.ROUNDED)
        table.add_column('Service', no_wrap=True)
        table.add_column('Check', no_wrap=True)
        table.add_column('Status', no_wrap=True)
        # Folded rather than cut off: a URL is one long word.
        table.add_column('Details', overflow='fold')
        previous_service = None
        for result in self.results:
            if previous_service is not None and result.service != previous_service:
                table.add_section()
            table.add_row(
                rich.text.Text(
                    result.service if result.service != previous_service else ''
                ),
                rich.text.Text(result.name),
                rich.text.Text(result.status.name, style=STATUS_STYLE[result.status]),
                self._details(result),
            )
            previous_service = result.service
        rich.get_console().print(table)
        return all(result.status is not Status.FAIL for result in self.results)

    @staticmethod
    def _details(result: Result) -> rich.text.Text:
        # Details may quote server data, so never parse them as markup.
        cell = rich.text.Text('\n'.join(result.details))
        for note in result.notes:
            if cell.plain:
                cell.append('\n')
            cell.append(note, style='dim')
        return cell

    @contextlib.contextmanager
    def _step(self) -> typing.Generator[Result]:
        """Add the row of the current step, reporting what happens inside the `with`.

        Anything assigned inside needs a value before the `with`, as an exception is
        swallowed and reported as the step's failure.
        """
        service, name = self._current
        result = Result(service, name)
        self.results.append(result)
        collector = _WarningCollector()
        failure: Exception | None = None
        caught: list[warnings.WarningMessage] = []
        with contextlib.ExitStack() as stack:
            if self._deprecations:
                caught = stack.enter_context(warnings.catch_warnings(record=True))
                warnings.simplefilter('always', DeprecationWarning)
            self._config.log.addHandler(collector)
            try:
                yield result
            except Exception as e:  # noqa: BLE001 (a failing step is a finding)
                failure = e
            finally:
                self._config.log.removeHandler(collector)
        self._note_deprecations(result, caught)
        if failure is not None:
            logger.warning(
                'Self check of %s failed: %s', name, failure, exc_info=failure
            )
            result.add(Status.FAIL, str(failure))
        for message in collector.messages:
            result.add(Status.WARN, message)

    def _note_deprecations(
        self, result: Result, caught: list[warnings.WarningMessage]
    ) -> None:
        for warning in caught:
            if not issubclass(warning.category, DeprecationWarning):
                # Recording swallowed it, but it is none of the check's business.
                warnings.warn_explicit(
                    warning.message, warning.category, warning.filename, warning.lineno
                )
            elif (message := str(warning.message)) not in self._seen_deprecations:
                self._seen_deprecations.add(message)
                result.notes.append(message)

    def _connect_churchtools(self) -> None:
        with self._step() as result:
            cta = ChurchToolsAPI(self._config)
            result.add(
                Status.OK,
                f'{self._config.churchtools.base_url}, '
                f'version {cta.server_version or "unknown"}',
            )
            self._cta = cta

    def _check_next_event(self) -> None:
        """Check the next event and its agenda like a run reads them."""
        if (cta := self._cta) is None:
            return
        with self._step() as result:
            try:
                event = cta.get_next_event(now(), agenda_required=True)
            except NoEventError as e:
                result.add(Status.WARN, f'{e.message} The event checks are skipped.')
                return
            except requests.HTTPError as e:
                # The agenda is denied, but the event itself is listed: ask for it
                # once more to name the calendar a basic permission does not cover.
                if (
                    e.response is not None
                    and e.response.status_code == requests.codes['forbidden']
                ):
                    event = cta.get_next_event(now())
                    for missing in cta.missing_calendar_coverage(
                        cta.BASIC_PERMISSIONS, event
                    ):
                        result.add(Status.FAIL, missing)
                raise
            cte = ChurchToolsEvent(cta, event, self._config)
            count, songs = cta.get_songs(event)
            for _song in songs:  # walks the pages and fetches missing tags
                pass
            calendar = f' ({event.calendar.title})' if event.calendar else ''
            result.add(
                Status.OK,
                f'{event.start_date.astimezone():%Y-%m-%d %H:%M} {event.name}'
                f'{calendar}, {_count(count, "song")} in the agenda',
            )
            self._event, self._cte = event, cte

    def _check_service_team(self) -> None:
        if (cte := self._cte) is None:
            return
        with self._step():
            cte.get_service_info()

    def _check_song_database(self) -> None:
        if (cta := self._cta) is None:
            return
        with self._step() as result:
            count, songs = cta.get_songs()
            if (song := next(songs, None)) is not None:
                cta.get_song(song.id)
            result.add(Status.OK, _count(count, 'song'))

    def _check_song_sheets(self) -> None:
        if (cta := self._cta) is None:
            return
        with self._step() as result:
            if missing := cta.missing_requirements(cta.SONG_SHEETS):
                result.add(Status.WARN, f'requires {" and ".join(missing)}')
            elif self._event is not None:
                for missing in cta.missing_calendar_coverage(
                    cta.SONG_SHEETS.permissions, self._event
                ):
                    result.add(Status.WARN, missing)

    def _check_nicknames(self) -> None:
        if (cta := self._cta) is None:
            return
        with self._step() as result:
            if missing := cta.missing_requirements(cta.NICKNAMES):
                result.add(Status.WARN, f'requires {" and ".join(missing)}')

    def _check_appointments(self) -> None:
        if (cta := self._cta) is None:
            return
        appointments = self._config.songbeamer.powerpoint.appointments
        with self._step() as result:
            if not appointments.template_pptx:
                result.add(Status.OFF, 'no template configured')
            elif missing := cta.missing_requirements(cta.APPOINTMENT_SLIDES):
                result.add(Status.WARN, f'requires {" and ".join(missing)}')
            else:
                # A calendar the token cannot see is left out without an error, so
                # name the ones that are read to let a missing one stand out.
                names = ', '.join(calendar.name for calendar in cta.get_calendars())
                if self._event is None:
                    result.add(Status.OK, f'from the calendars {names or "none"}')
                else:
                    count = sum(1 for _ in cta.get_appointments(self._event))
                    weeks = _count(appointments.look_ahead_weeks, 'week')
                    result.add(
                        Status.OK,
                        f'{_count(count, "appointment")} from the calendars '
                        f'{names or "none"} in the {weeks} after the event',
                    )

    def _connect_immich(self) -> None:
        with self._step() as result:
            if not (immich_config := self._config.immich):
                result.add(Status.OFF, 'not configured')
                return
            immich = ImmichAPI(self._config)
            immich.connect()
            result.add(
                Status.OK,
                f'{immich_config.base_url}, '
                f'version {immich.server_version or "unknown"}',
            )
            self._immich = immich, immich_config

    @staticmethod
    def _upload_tags_looked_up(immich: ImmichAPI) -> bool:
        # Before create_missing_tags(), a found tag is what switches the upload on.
        return immich.upload_enabled or bool(immich.missing_upload_tags)

    def _check_media_upload(self) -> None:
        if self._immich is None:
            return
        immich, immich_config = self._immich
        tags = immich_config.upload_tags
        missing_tags = immich.missing_upload_tags
        with self._step() as result:
            if not tags:
                result.add(Status.OFF, 'no upload tags configured')
            elif missing := immich.missing_requirements(immich.MEDIA_UPLOAD):
                result.add(Status.WARN, f'requires {" and ".join(missing)}')
            elif not self._upload_tags_looked_up(immich):
                result.add(Status.WARN, 'the upload tags could not be looked up')
            elif found := [tag for tag in tags if tag not in missing_tags]:
                result.add(Status.OK, f'tags {", ".join(found)}')
            else:
                result.add(Status.OK, 'none of the upload tags exists yet')

    def _check_tag_creation(self) -> None:
        if self._immich is None:
            return
        immich, immich_config = self._immich
        missing_tags = immich.missing_upload_tags
        with self._step() as result:
            if not immich_config.upload_tags:
                result.add(Status.OFF, 'no upload tags configured')
            elif missing := immich.missing_requirements(immich.TAG_CREATION):
                result.add(
                    Status.WARN,
                    f'cannot create the missing tags {", ".join(missing_tags)}, '
                    f'it requires {" and ".join(missing)}'
                    if missing_tags
                    else f'requires {" and ".join(missing)}',
                )
            elif not self._upload_tags_looked_up(immich):
                result.add(Status.OK, 'permitted')
            elif not missing_tags:
                result.add(Status.OK, 'permitted, all upload tags exist')
            else:
                result.add(
                    Status.OK,
                    f'the next agenda run creates the tags {", ".join(missing_tags)}',
                )

    def _check_backgrounds(self) -> None:
        if self._immich is None:
            return
        immich, immich_config = self._immich
        album = immich_config.backgrounds_album
        with self._step() as result:
            if not album:
                result.add(Status.OFF, 'no backgrounds album configured')
            elif missing := immich.missing_requirements(immich.BACKGROUNDS):
                result.add(Status.WARN, f'requires {" and ".join(missing)}')
            elif not immich.backgrounds_enabled:
                result.add(Status.WARN, f'album "{album}" is not usable')
            elif candidates := immich.fetch_background_candidates():
                images = _count(len(candidates), 'image')
                result.add(Status.OK, f'album "{album}", {images}')
