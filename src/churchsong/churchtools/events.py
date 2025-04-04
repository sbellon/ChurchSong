import dataclasses
import enum
import os
import re
from collections import defaultdict

import alive_progress  # pyright: ignore[reportMissingTypeStubs]

from churchsong.churchtools import (
    ChurchToolsAPI,
    EventAgendaItem,
    EventAgendaItemType,
    EventFileDomainType,
    EventShort,
    File,
)
from churchsong.configuration import Configuration


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


# The values of Subfolder are the actual subfolder names created beneath temp_dir.
class Subfolder(enum.StrEnum):
    FILES = 'Files'
    SONGS = 'Songs'


class ChurchToolsEvent:
    def __init__(
        self, cta: ChurchToolsAPI, event: EventShort, config: Configuration
    ) -> None:
        self.cta = cta
        self._log = config.log
        self._event = self.cta.get_full_event(event)
        self._agenda = self.cta.get_event_agenda(event)
        self._temp_dir = config.temp_dir
        self._person_dict = config.person_dict

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
        (self._temp_dir / subfolder).mkdir(parents=True, exist_ok=True)
        filename = self._temp_dir / subfolder / filename
        if overwrite:
            with filename.open(mode='wb') as fd:
                fd.write(r.content)
        return os.fspath(filename)

    def _sng_file(self, item: EventAgendaItem) -> File | None:
        sng_file = None
        if item.song:
            song = self.cta.get_song(item.song.song_id)
            item.title = song.name
            # Take first .sng file in chosen arrangement if it exists,
            # fall back to first .sng file in default arrangement otherwise.
            sng_file = next(
                (
                    file
                    for arr in song.arrangements
                    if arr.id == item.song.arrangement_id
                    for file in arr.files
                    if file.name.endswith('.sng')
                ),
                None,
            ) or next(
                (
                    file
                    for arr in song.arrangements
                    if arr.is_default
                    for file in arr.files
                    if file.name.endswith('.sng')
                ),
                None,
            )
        return sng_file

    def download_agenda_items(
        self, *, download_files: bool = True, download_songs: bool = True
    ) -> list[Item]:
        self._log.info('Downloading agenda items and songs')
        agenda_items: list[Item] = []
        with alive_progress.alive_bar(
            len(self._event.event_files) + len(self._agenda.items),
            length=20,
            title='Downloading: Agenda',
            title_length=32,
            spinner=None,
            receipt=False,
        ) as bar:  # pyright: ignore[reportUnknownVariableType]

            def progress() -> None:
                bar.title = f'Downloading: {item.title}'
                bar()

            for item in self._event.event_files:
                progress()
                match item.domain_type:
                    case EventFileDomainType.FILE:
                        filename = self._download_file(
                            item.title,
                            item.frontend_url,
                            Subfolder.FILES,
                            overwrite=download_files,
                        )
                        event_file = Item(ItemType.FILE, item.title, filename)
                    case EventFileDomainType.LINK:
                        event_file = Item(ItemType.LINK, item.title, item.frontend_url)
                    case _:
                        self._log.warning(
                            f'Unexpected event file type: {item.domain_type}'
                        )
                        continue
                agenda_items.append(event_file)
            for item in self._agenda.items:
                match item.type:
                    case EventAgendaItemType.HEADER:
                        progress()
                        agenda_item = Item(ItemType.HEADER, item.title)
                    case EventAgendaItemType.NORMAL:
                        progress()
                        agenda_item = Item(ItemType.NORMAL, item.title)
                    case EventAgendaItemType.SONG:
                        sng_file = self._sng_file(item)
                        progress()
                        filename = (
                            self._download_file(
                                item.title,
                                sng_file.file_url,
                                Subfolder.SONGS,
                                overwrite=download_songs,
                            )
                            if sng_file
                            else None
                        )
                        agenda_item = Item(ItemType.SONG, item.title, filename)
                    case _:
                        self._log.warning(f'Unexpected event item type: {item.type}')
                        continue
                agenda_items.append(agenda_item)
        return agenda_items

    def get_service_info(self) -> tuple[list[Item], defaultdict[str, set[Person]]]:
        self._log.info('Fetching service team information')
        service_id2name = {
            service.id: service.name for service in self.cta.get_services()
        }
        service_leads: defaultdict[str, set[Person]] = defaultdict(
            lambda: {
                Person(
                    fullname=self._person_dict.get(str(None), str(None)),
                    shortname=fullname.split(' ')[0],
                )
            }
        )
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
                fullname = str(event_service.name)
                nickname = None
            # Still fall back to our configuration mapping.
            fullname = self._person_dict.get(fullname, fullname)
            person = Person(fullname, nickname or fullname.split(' ')[0])
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
