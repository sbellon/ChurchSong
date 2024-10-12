from __future__ import annotations

import datetime  # noqa: TCH003
import io
import sys
import typing
import zipfile
from collections import defaultdict

import marshmallow
import marshmallow_dataclass
import requests

if typing.TYPE_CHECKING:
    from configuration import Configuration


@typing.dataclass_transform()
def deserialize(cls: type) -> type:
    class Meta:
        unknown = marshmallow.EXCLUDE

    cls.Meta = Meta
    return marshmallow_dataclass.dataclass(cls)


SchemaType = typing.ClassVar[type[marshmallow.Schema]]  # for pylance


@deserialize
class Service:
    Schema: SchemaType  # for pylance
    id: int
    name: str | None


@deserialize
class ServicesData:
    Schema: SchemaType  # for pylance
    data: list[Service]


@deserialize
class EventShort:
    Schema: SchemaType  # for pylance
    id: int
    startDate: datetime.datetime  # noqa: N815


@deserialize
class EventsData:
    Schema: SchemaType  # for pylance
    data: list[EventShort]


@deserialize
class EventService:
    Schema: SchemaType  # for pylance
    serviceId: int  # noqa: N815
    name: str | None


@deserialize
class EventFull:
    Schema: SchemaType  # for pylance
    id: int
    eventServices: list[EventService]  # noqa: N815


@deserialize
class EventFullData:
    Schema: SchemaType  # for pylance
    data: EventFull


@deserialize
class EventAgenda:
    Schema: SchemaType  # for pylance
    id: int


@deserialize
class EventAgendaData:
    Schema: SchemaType  # for pylance
    data: EventAgenda


@deserialize
class AgendaExport:
    Schema: SchemaType  # for pylance
    url: str


@deserialize
class AgendaExportData:
    Schema: SchemaType  # for pylance
    data: AgendaExport


class ChurchTools:
    def __init__(self, config: Configuration) -> None:
        self._log = config.log
        self._base_url = config.base_url
        self._login_token = config.login_token
        self._person_dict = config.person_dict
        self._temp_dir = config.temp_dir

    def _headers(self) -> dict[str, str]:
        return {
            'Accept': 'application/json',
            'Authorization': f'Login {self._login_token}',
        }

    def _request(
        self,
        method: str,
        url: str,
        params: dict[str, str] | None = None,
    ) -> requests.Response:
        self._log.debug(
            'Request %s %s%s with params=%s', method, self._base_url, url, params
        )
        r = requests.request(
            method,
            f'{self._base_url}{url}',
            headers=self._headers(),
            params=params,
            timeout=None,  # noqa: S113
        )
        self._log.debug('Response is %s %s', r.status_code, r.reason)
        r.raise_for_status()
        return r

    def _get(
        self,
        url: str,
        params: dict[str, str] | None = None,
    ) -> requests.Response:
        return self._request('GET', url, params)

    def _post(
        self,
        url: str,
        params: dict[str, str] | None = None,
    ) -> requests.Response:
        return self._request('POST', url, params)

    def _get_services(self) -> list[Service]:
        r = self._get('/api/services')
        result = ServicesData.Schema().load(r.json())
        assert isinstance(result, ServicesData)
        return result.data

    def _get_events(self, from_date: datetime.date | None = None) -> list[EventShort]:
        r = self._get(
            '/api/events', params={'from': f'{from_date}'} if from_date else None
        )
        result = EventsData.Schema().load(r.json())
        assert isinstance(result, EventsData)
        return result.data

    def _get_next_event(self, from_date: datetime.date | None = None) -> EventShort:
        try:
            return self._get_events(from_date)[0]
        except IndexError:
            err_msg = 'No events present{} in ChurchTools'.format(
                f' after {from_date}' if from_date else ''
            )
            self._log.error(err_msg)
            sys.stderr.write(f'{err_msg}\n')
            sys.exit(1)

    def _get_event(self, event_id: int) -> EventFull:
        r = self._get(f'/api/events/{event_id}')
        result = EventFullData.Schema().load(r.json())
        assert isinstance(result, EventFullData)
        return result.data

    def _get_event_agenda(self, event_id: int) -> EventAgenda:
        r = self._get(f'/api/events/{event_id}/agenda')
        result = EventAgendaData.Schema().load(r.json())
        assert isinstance(result, EventAgendaData)
        return result.data

    def _get_agenda_export(self, agenda_id: int) -> AgendaExport:
        r = self._post(
            f'/api/agendas/{agenda_id}/export',
            params={
                'target': 'SONG_BEAMER',
                'exportSongs': 'true',
                'appendArrangement': 'false',
                'withCategory': 'false',
            },
        )
        result = AgendaExportData.Schema().load(r.json())
        assert isinstance(result, AgendaExportData)
        return result.data

    def get_service_leads(
        self, from_date: datetime.date | None = None
    ) -> defaultdict[str, str]:
        self._log.info('Fetching service teams')
        services = self._get_services()
        next_event = self._get_next_event(from_date)
        event = self._get_event(next_event.id)
        # Initialize the "None" person for all services.
        service_leads = defaultdict(lambda: self._person_dict.get(str(None), str(None)))
        # Update with the actual persons of the eventservice.
        service_leads.update(
            {
                service.name: self._person_dict.get(
                    str(eventservice.name),
                    str(eventservice.name),
                )
                for eventservice in event.eventServices
                for service in services
                if eventservice.serviceId == service.id
            },
        )
        return service_leads

    def get_url_for_songbeamer_agenda(
        self, from_date: datetime.date | None = None
    ) -> str:
        self._log.info('Fetching SongBeamer export URL')
        next_event = self._get_next_event(from_date)
        try:
            agenda = self._get_event_agenda(next_event.id)
        except requests.HTTPError as e:
            if e.response.status_code == requests.codes['not_found']:
                date = next_event.startDate.date()
                err_msg = f'No event agenda present for {date} in ChurchTools'
                self._log.error(err_msg)
                sys.stderr.write(f'{err_msg}\n')
                sys.exit(1)
            raise
        return self._get_agenda_export(agenda.id).url

    def download_and_extract_agenda_zip(self, url: str) -> None:
        self._log.info('Downloading and extracting SongBeamer export')
        r = self._get(url)
        assert isinstance(r.content, bytes)
        buf = io.BytesIO(r.content)
        zipfile.ZipFile(buf, mode='r').extractall(path=self._temp_dir)
