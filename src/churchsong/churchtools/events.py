# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import contextlib
import dataclasses
import datetime
import enum
import io
import os
import re
import typing
from collections import defaultdict

import pypdf
import reportlab.lib.pagesizes
import reportlab.pdfgen.canvas

from churchsong.churchtools import EventAgendaItemType, EventFileDomainType
from churchsong.utils.progress import Progress

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from churchsong.churchtools import (
        ChurchToolsAPI,
        EventAgendaItem,
        EventFile,
        EventFull,
        EventShort,
        File,
    )
    from churchsong.configuration import Configuration

    _: Callable[[str], str]


# The values of ItemType need to match those in configuration.SongBeamerColorConfig:
class ItemType(enum.StrEnum):
    SERVICE = 'Service'
    HEADER = 'Header'
    NORMAL = 'Normal'
    SONG = 'Song'
    FILE = 'File'
    LINK = 'Link'


@dataclasses.dataclass
class Item:
    type: ItemType
    title: str
    filename: str | None = None


@dataclasses.dataclass(eq=True, frozen=True)
class Person:
    fullname: str
    shortname: str


# The values of Subfolder are the actual subfolder names created beneath output_dir.
class Subfolder(enum.StrEnum):
    FILES = 'Files'
    SONGS = 'Songs'


@dataclasses.dataclass
class SongFiles:
    title: str
    arrangement: str
    sng_file: File | None
    chords_file: File | None
    leads_file: File | None
    last_modified: datetime.datetime


class PdfSheet:
    def __init__(self, title: str, subtitle: str, subsubtitle: str) -> None:
        self._title = title
        self._subtitle = subtitle
        self._subsubtitle = subsubtitle
        self._pdf = pypdf.PdfWriter()
        self._toc: list[tuple[str, str]] = []

    def _create_title_page(self, last_modified: datetime.datetime) -> pypdf.PageObject:
        data = io.BytesIO()
        pagesize = reportlab.lib.pagesizes.A4
        canvas = reportlab.pdfgen.canvas.Canvas(data, pagesize=pagesize)
        width, height = pagesize

        # Font settings
        font = 'Helvetica'
        font_h1 = f'{font}-Bold'
        size_h1 = 36
        size_h2 = 24
        size_h3 = 18
        size_b = 12
        margin = 72
        line_spacing = 1.66

        # Page header
        y = height * 2 / 3
        canvas.setFont(font_h1, size_h1)
        canvas.drawCentredString(width / 2, y, self._title)
        y -= int(size_h1 * line_spacing)
        canvas.setFont(font, size_h2)
        canvas.drawCentredString(width / 2, y, self._subtitle)
        y -= int(size_h2 * line_spacing)
        canvas.setFont(font, size_h3)
        canvas.drawCentredString(
            width / 2, y, self._subsubtitle.format(last_modified=last_modified)
        )
        y -= int(size_h3 * line_spacing)

        # Table of Contents
        y -= margin
        canvas.setFont(font, size_b)
        for idx, (title, arrangement) in enumerate(self._toc, start=1):
            canvas.drawString(margin, y, f'{idx}.')
            canvas.drawString(margin + 30, y, title)
            canvas.drawRightString(width - margin, y, arrangement)
            y -= int(size_b * line_spacing)
            if y < margin:  # continue on new page if list is too long
                canvas.showPage()
                y = height - margin

        canvas.save()
        data.seek(0)
        return pypdf.PdfReader(data).pages[0]

    def append(self, title: str, arrangement: str, content: io.BytesIO) -> None:
        self._pdf.append(content)
        self._toc.append((title, arrangement))

    def finalize(self, last_modified: datetime.datetime) -> bytes:
        self._pdf.insert_page(
            self._create_title_page(last_modified=last_modified), index=0
        )
        content = io.BytesIO()
        self._pdf.write(content)
        return content.getvalue()


class SongSheets:
    def __init__(
        self, cta: ChurchToolsAPI, event: EventFull, datetime_format: str, enabled: bool
    ) -> None:
        self.cta = cta
        self._event = event
        self._enabled = enabled and cta.has_permissions(['churchservice:edit events'])
        chords_name = _('Song Sheets Chords')
        leads_name = _('Song Sheets Leads')
        self._chords_file = f'{chords_name}.pdf'
        self._leads_file = f'{leads_name}.pdf'
        if self._enabled:
            event_startdate = f'{self._event.start_date.astimezone():{datetime_format}}'
            self._last_modified = datetime.datetime.min.replace(tzinfo=datetime.UTC)
            subtitle = f'{self._event.name} - {event_startdate}'
            subsubtitle = f'{_("Last update")}: {{last_modified:{datetime_format}}}'
            self._chords_pdf = PdfSheet(chords_name, subtitle, subsubtitle)
            self._leads_pdf = PdfSheet(leads_name, subtitle, subsubtitle)

    def _download_stream(self, url: str) -> io.BytesIO:
        r = self.cta.download_url(url)
        return io.BytesIO(r.content)

    def delete_event_file(self, event_file: EventFile) -> bool:
        if event_file.title in (self._chords_file, self._leads_file):
            if self._enabled:
                self.cta.delete_event_file(self._event, event_file)
            return True
        return False

    def download_and_append(self, song_files: SongFiles) -> None:
        if not self._enabled:
            return
        if f := song_files.chords_file:
            self._chords_pdf.append(
                song_files.title,
                song_files.arrangement,
                self._download_stream(f.file_url),
            )
        if f := song_files.leads_file:
            self._leads_pdf.append(
                song_files.title,
                song_files.arrangement,
                self._download_stream(f.file_url),
            )
        self._last_modified = max(self._last_modified, song_files.last_modified)

    def upload(self) -> None:
        if not self._enabled:
            return
        self.cta.upload_event_file(
            self._event,
            self._chords_file,
            self._chords_pdf.finalize(last_modified=self._last_modified),
        )
        self.cta.upload_event_file(
            self._event,
            self._leads_file,
            self._leads_pdf.finalize(last_modified=self._last_modified),
        )


class ChurchToolsEvent:
    def __init__(
        self, cta: ChurchToolsAPI, event: EventShort, config: Configuration
    ) -> None:
        self.cta = cta
        self._log = config.log
        self._event = self.cta.get_full_event(event)
        self._agenda = self.cta.get_event_agenda(event)
        self._output_dir = config.songbeamer.output_dir
        self._person_dict = config.churchtools.replacements
        self._datetime_format = config.songbeamer.slides.datetime_format

    def _download_file(
        self, name: str, url: str, subfolder: Subfolder, *, overwrite: bool = True
    ) -> str:
        r = self.cta.download_url(url)
        if 'Content-Disposition' in r.headers and (
            match := re.search('filename="([^"]+)"', r.headers['Content-Disposition'])
        ):
            # ChurchTools apparently sends the filename="xyz" in latin1 instead of utf-8
            filename = match.group(1).encode('latin1').decode('utf-8')
        else:
            filename = name
        (self._output_dir / subfolder).mkdir(parents=True, exist_ok=True)
        filename = self._output_dir / subfolder / filename
        if overwrite:
            with filename.open(mode='wb') as fd:
                fd.write(r.content)
        return os.fspath(filename)

    def _song_files(self, item: EventAgendaItem) -> SongFiles:
        assert item.song is not None  # noqa: S101
        sng_file = None
        default_sng_file = None
        chords_file = None
        leads_file = None
        song = self.cta.get_song(item.song.song_id)
        for arr in song.arrangements:
            for file in arr.files:
                if file.name.endswith('.sng'):
                    if arr.id == item.song.arrangement_id:
                        sng_file = file
                    if arr.is_default:
                        default_sng_file = file
                if file.name.endswith('.pdf') and arr.id == item.song.arrangement_id:
                    if '-lead-' in file.name.lower():
                        leads_file = file
                    else:
                        chords_file = file
        return SongFiles(
            title=item.song.title,
            arrangement=f'{item.song.arrangement} ({item.song.key})'
            if item.song.is_default
            else item.song.arrangement,
            sng_file=sng_file or default_sng_file,
            chords_file=chords_file,
            leads_file=leads_file or chords_file,
            last_modified=item.meta.modified_date,
        )

    def download_agenda_items(  # noqa: C901
        self,
        *,
        download_files: bool = True,
        download_songs: bool = True,
        upload_songsheets: bool = True,
    ) -> list[Item]:
        msg_items = (
            ['Downloading agenda items']
            + (['event files'] if download_files else [])
            + (['songs'] if download_songs else [])
            + (['uploading song sheets'] if upload_songsheets else [])
        )
        self._log.info(', '.join(msg_items))
        agenda_items: list[Item] = []
        song_sheets = SongSheets(
            self.cta, self._event, self._datetime_format, enabled=upload_songsheets
        )

        @contextlib.contextmanager
        def do_progress(
            item: EventAgendaItem | EventFile,
        ) -> typing.Generator[EventAgendaItem | EventFile]:
            with progress.do_progress(item, description=f'Downloading: {item.title}'):
                yield item

        with Progress(
            f'Downloading: Agenda for {self._event.start_date:%Y-%m-%d}',
            total=len(self._event.event_files) + len(self._agenda.items),
        ) as progress:
            for item in self._event.event_files:
                match item.domain_type:
                    case EventFileDomainType.FILE:
                        with do_progress(item):
                            if song_sheets.delete_event_file(item):
                                continue
                            filename = self._download_file(
                                item.title,
                                item.frontend_url,
                                Subfolder.FILES,
                                overwrite=download_files,
                            )
                            event_file = Item(ItemType.FILE, item.title, filename)
                    case EventFileDomainType.LINK:
                        with do_progress(item):
                            event_file = Item(
                                ItemType.LINK, item.title, item.frontend_url
                            )
                    case _:  # pyright: ignore[reportUnnecessaryComparison]
                        with do_progress(item):
                            self._log.warning(
                                f'Unexpected event file type: {item.domain_type}'
                            )
                        continue
                agenda_items.append(event_file)
            for item in self._agenda.items:
                match item.type:
                    case EventAgendaItemType.HEADER:
                        with do_progress(item):
                            agenda_item = Item(ItemType.HEADER, item.title)
                    case EventAgendaItemType.NORMAL:
                        with do_progress(item):
                            agenda_item = Item(ItemType.NORMAL, item.title)
                    case EventAgendaItemType.SONG:
                        if not item.song:
                            self._log.warning('Song event item without song data')
                            continue
                        files = self._song_files(item)
                        # item.title may not be the song title itself,
                        # so rather use item.song.title instead.
                        item.title = files.title
                        with do_progress(item):
                            filename = (
                                self._download_file(
                                    item.title,
                                    files.sng_file.file_url,
                                    Subfolder.SONGS,
                                    overwrite=download_songs,
                                )
                                if files.sng_file
                                else None
                            )
                            agenda_item = Item(ItemType.SONG, item.title, filename)
                            song_sheets.download_and_append(files)
                    case _:  # pyright: ignore[reportUnnecessaryComparison]
                        with do_progress():
                            self._log.warning(
                                f'Unexpected event item type: {item.type}'
                            )
                        continue
                agenda_items.append(agenda_item)
        song_sheets.upload()
        return agenda_items

    def get_service_info(self) -> tuple[list[Item], defaultdict[str, set[Person]]]:
        self._log.info('Fetching service team information')
        service_id2name = {
            service.id: service.name for service in self.cta.get_services()
        }
        nobody = Person(
            fullname=self._person_dict.get(str(None), _('Nobody')),
            shortname=self._person_dict.get(str(None), _('Nobody')),
        )
        service_leads: defaultdict[str, set[Person]] = defaultdict(lambda: {nobody})
        for event_service in self._event.event_services:
            service_name = str(service_id2name.get(event_service.service_id, None))
            # If we have access to the churchdb, we can query the person there and
            # perhaps even get its proper nickname, if set in the database.
            if event_service.person_id is not None and (
                person := self.cta.get_person(event_service.person_id)
            ):
                fullname = f'{person.firstname} {person.lastname}'
                nickname = person.nickname
            else:
                fullname = event_service.name
                nickname = None
            if fullname:
                fullname = self._person_dict.get(fullname, fullname)
                person = Person(fullname, nickname or fullname.split(' ')[0])
            else:
                person = nobody
            if service_name not in service_leads:
                service_leads[service_name] = {person}
            else:
                service_leads[service_name].add(person)
        service_items = [
            Item(
                ItemType.SERVICE,
                f'{service}: {", ".join(sorted(p.fullname for p in persons))}',
            )
            for service, persons in sorted(service_leads.items())
        ]
        return service_items, service_leads
