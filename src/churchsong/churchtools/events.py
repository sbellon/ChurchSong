import dataclasses
import io
import os
import zipfile
from collections import defaultdict

from churchsong.churchtools import ChurchToolsAPI, EventShort
from churchsong.configuration import Configuration


@dataclasses.dataclass
class AgendaFileItem:
    title: str
    filename: str


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

    def get_service_leads(self) -> defaultdict[str, set[str]]:
        self._log.info('Fetching service teams')
        service_id2name = {
            service.id: service.name for service in self.cta.get_services()
        }
        service_leads = defaultdict(
            lambda: {self._person_dict.get(str(None), str(None))}
        )
        for event_service in self._full_event.event_services:
            service_name = service_id2name[event_service.service_id]
            person_name = self._person_dict.get(
                str(event_service.name), str(event_service.name)
            )
            if service_name not in service_leads:
                service_leads[service_name] = {person_name}
            else:
                service_leads[service_name].add(person_name)
        return service_leads

    def _fetch_service_attachments(self) -> list[AgendaFileItem]:
        self._log.info('Fetching event attachments')
        result = []
        for event_file in self._full_event.event_files:
            match event_file.domain_type:
                case 'file':
                    filename, file_content = self.cta.download_file(
                        event_file.frontend_url
                    )
                    filename = filename if filename else event_file.title
                    self._files_dir.mkdir(parents=True, exist_ok=True)
                    filename = self._files_dir / filename
                    with filename.open(mode='wb+') as fd:
                        fd.write(file_content)
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
        content = self.cta.download_agenda_zip(self._event)
        buf = io.BytesIO(content)
        zipfile.ZipFile(buf, mode='r').extractall(path=self._temp_dir)
        return self._fetch_service_attachments()
