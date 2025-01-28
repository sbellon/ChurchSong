import dataclasses
import io
import os
import pathlib
import re
import typing
import zipfile
from collections import defaultdict

import alive_progress
import requests

from churchsong.churchtools import ChurchToolsAPI, EventShort
from churchsong.configuration import Configuration


@dataclasses.dataclass
class AgendaFileItem:
    title: str
    filename: str


@dataclasses.dataclass(eq=True, frozen=True)
class Person:
    fullname: str
    shortname: str


class ChurchToolsEvent:
    def __init__(
        self, cta: ChurchToolsAPI, event: EventShort, config: Configuration
    ) -> None:
        self.cta = cta
        self._log = config.log
        self._event = event
        self._full_event = self.cta.get_full_event(self._event)
        self._temp_dir = config.temp_dir
        self._files_dir = config.temp_dir / 'Files'
        self._person_dict = config.person_dict

    def get_service_leads(self) -> defaultdict[str, set[Person]]:
        self._log.info('Fetching service teams')
        service_id2name = {
            service.id: service.name for service in self.cta.get_services()
        }
        service_leads = defaultdict(
            lambda: {
                Person(
                    fullname=self._person_dict.get(str(None), str(None)),
                    shortname=fullname.split(' ')[0],
                )
            }
        )
        for event_service in self._full_event.event_services:
            service_name = service_id2name[event_service.service_id]
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
        return service_leads

    def _download_with_progress(
        self,
        response: requests.Response,
        title: str,
        output: typing.BinaryIO,
    ) -> None:
        filesize = int(response.headers.get('Content-Length', 0))
        with alive_progress.alive_bar(
            filesize if filesize > 0 else None,
            title=title,
            spinner=None,
            receipt=False,
        ) as bar:
            for chunk in response.iter_content(chunk_size=None):
                output.write(chunk)
                bar(len(chunk))

    def _download_file(self, title: str, url: str) -> pathlib.Path:
        r = self.cta.download_url(url)
        filename = title
        if 'Content-Disposition' in r.headers and (
            match := re.search('filename="([^"]+)"', r.headers['Content-Disposition'])
        ):
            filename = match.group(1)
        self._files_dir.mkdir(parents=True, exist_ok=True)
        filename = self._files_dir / filename
        with filename.open(mode='wb+') as fd:
            self._download_with_progress(r, f'Downloading "{filename}"', output=fd)
        return filename

    def _fetch_service_attachments(self) -> list[AgendaFileItem]:
        self._log.info('Fetching event attachments')
        result = []
        for event_file in self._full_event.event_files:
            match event_file.domain_type:
                case 'file':
                    filename = self._download_file(
                        event_file.title, event_file.frontend_url
                    )
                    result.append(AgendaFileItem(event_file.title, os.fspath(filename)))
                case 'link':
                    result.append(
                        AgendaFileItem(event_file.title, event_file.frontend_url)
                    )
                case _:
                    self._log.warning(
                        f'Unexpected event file type: {event_file.domain_type}'
                    )
        return result

    def download_and_extract_agenda_zip(self) -> list[AgendaFileItem]:
        self._log.info('Downloading and extracting SongBeamer export')
        r = self.cta.download_agenda_zip(self._event)
        with io.BytesIO() as buf:
            self._download_with_progress(r, 'Downloading agenda', output=buf)
            buf.seek(0)
            zipfile.ZipFile(buf, mode='r').extractall(path=self._temp_dir)
        return self._fetch_service_attachments()
