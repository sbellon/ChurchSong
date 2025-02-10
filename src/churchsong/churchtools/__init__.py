from __future__ import annotations

import datetime  # noqa: TC003
import sys
import typing

import pydantic
import requests

if typing.TYPE_CHECKING:
    from churchsong.configuration import Configuration


class PermissionsGlobalChurchCal(pydantic.BaseModel):
    view: bool
    view_category: list[int] = pydantic.Field(alias='view category')


class PermissionsGlobalChurchService(pydantic.BaseModel):
    view: bool
    view_servicegroup: list[int] = pydantic.Field(alias='view servicegroup')
    view_history: bool = pydantic.Field(alias='view history')
    view_events: list[int] = pydantic.Field(alias='view events')
    view_agenda: list[int] = pydantic.Field(alias='view agenda')
    view_songcategory: list[int] = pydantic.Field(alias='view songcategory')


class PermissionsGlobal(pydantic.BaseModel):
    churchcal: PermissionsGlobalChurchCal
    churchservice: PermissionsGlobalChurchService


class PermissionsGlobalData(pydantic.BaseModel):
    data: PermissionsGlobal

    def get_permission(self, perm: str) -> bool | list[int]:
        perm = perm.replace(' ', '_')
        obj = self.data
        for key in perm.split(':'):
            if hasattr(obj, key):
                obj = getattr(obj, key)
            else:
                return False
        assert isinstance(obj, bool | list)  # noqa: S101
        return obj


class CalendarAppointmentBase(pydantic.BaseModel):
    title: str
    subtitle: str | None
    description: str | None
    image: str | None
    link: str | None
    start_date: datetime.datetime = pydantic.Field(alias='startDate')
    all_day: bool = pydantic.Field(alias='allDay')


class CalendarAppointment(pydantic.BaseModel):
    base: CalendarAppointmentBase


class CalendarAppointmentsData(pydantic.BaseModel):
    data: list[CalendarAppointment]


class Calendar(pydantic.BaseModel):
    id: int
    name: str


class CalendarsData(pydantic.BaseModel):
    data: list[Calendar]


class Person(pydantic.BaseModel):
    firstname: str = pydantic.Field(alias='firstName')
    lastname: str = pydantic.Field(alias='lastName')
    nickname: str | None


class PersonsData(pydantic.BaseModel):
    data: Person


class Service(pydantic.BaseModel):
    id: int
    name: str | None


class ServicesData(pydantic.BaseModel):
    data: list[Service]


class EventShort(pydantic.BaseModel):
    id: int
    start_date: datetime.datetime = pydantic.Field(alias='startDate')
    end_date: datetime.datetime = pydantic.Field(alias='endDate')


class EventsData(pydantic.BaseModel):
    data: list[EventShort]


class EventService(pydantic.BaseModel):
    person_id: int | None = pydantic.Field(alias='personId')
    name: str | None
    service_id: int = pydantic.Field(alias='serviceId')

    # If a `person` element is present in the `eventService`, prefer it over the
    # `eventService.name` for finding the person's name. Within the `person`, prefer
    # a `person.domainAttributes.firstName` and `person.domainAttributes.lastName`,
    # if set, over `person.title`.
    @pydantic.root_validator(pre=True)
    def flatten_person_name(cls, values: dict[str, str]) -> dict[str, str]:
        person = values.get('person')
        if isinstance(person, dict):
            attrs = person.get('domainAttributes', {})
            first_name = attrs.get('firstName')
            last_name = attrs.get('lastName')
            name = (
                f'{first_name} {last_name}'
                if first_name and last_name
                else person.get('title')
            )
            if name:
                values['name'] = name
        return values


class EventFile(pydantic.BaseModel):
    title: str
    domain_type: str = pydantic.Field(alias='domainType')
    frontend_url: str = pydantic.Field(alias='frontendUrl')


class EventFull(pydantic.BaseModel):
    id: int
    event_files: list[EventFile] = pydantic.Field(alias='eventFiles')
    event_services: list[EventService] = pydantic.Field(alias='eventServices')


class EventFullData(pydantic.BaseModel):
    data: EventFull


class EventAgenda(pydantic.BaseModel):
    id: int


class EventAgendaData(pydantic.BaseModel):
    data: EventAgenda


class AgendaExport(pydantic.BaseModel):
    url: str


class AgendaExportData(pydantic.BaseModel):
    data: AgendaExport


class File(pydantic.BaseModel):
    name: str
    file_url: str = pydantic.Field(alias='fileUrl')


class Arrangement(pydantic.BaseModel):
    id: int
    name: str
    source_name: str | None = pydantic.Field(alias='sourceName')
    source_reference: str | None = pydantic.Field(alias='sourceReference')
    key_of_arrangement: str | None = pydantic.Field(alias='keyOfArrangement')
    bpm: str | None
    beat: str | None
    duration: int | None
    files: list[File]
    sng_file_content: list[str] = []  # NOT filled by ChurchTools, but internally


class Song(pydantic.BaseModel):
    id: int
    name: str
    author: str | None
    ccli: str | None
    arrangements: list[Arrangement]
    tags: set[str] = set()


class Pagination(pydantic.BaseModel):
    total: int
    limit: int
    current: int
    last_page: int = pydantic.Field(alias='lastPage')


class SongsMeta(pydantic.BaseModel):
    count: int
    pagination: Pagination | None = None


class SongsData(pydantic.BaseModel):
    data: list[Song]
    meta: SongsMeta


class Tag(pydantic.BaseModel):
    id: int
    name: str


class TagsData(pydantic.BaseModel):
    data: list[Tag]


class AJAXSong(pydantic.BaseModel):
    id: str
    tags: list[int]


class AJAXSongs(pydantic.BaseModel):
    songs: dict[str, AJAXSong]


class AJAXSongsData(pydantic.BaseModel):
    data: AJAXSongs


class ChurchToolsAPI:
    def __init__(self, config: Configuration) -> None:
        self._log = config.log
        self._base_url = config.base_url
        self._login_token = config.login_token
        self._assert_permissions(
            'churchservice:view',
            'churchservice:view agenda',
            'churchservice:view events',
            'churchservice:view servicegroup',
            'churchservice:view songcategory',
        )
        # Querying a person's nickname requires additional permissions, but they are
        # optional and if not present, the nickname will just not be considered:
        # - churchdb:view alldata(-1)
        # - churchdb:security level person(1)

    def _assert_permissions(self, *required_perms: str) -> None:
        try:
            r = self._get('/api/permissions/global')
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.MissingSchema,
        ) as e:
            self._log.error(e)
            sys.stderr.write(f'Error: {e}\n\n')
            sys.stderr.write(
                'Did you configure the URL of your ChurchTools instance correctly?\n'
            )
            sys.exit(1)
        except requests.exceptions.HTTPError as e:
            self._log.error(e)
            sys.stderr.write(f'Error: {e}\n\n')
            if e.response.status_code in (
                requests.codes.forbidden,
                requests.codes.unauthorized,
            ):
                sys.stderr.write(
                    'Did you configure your ChurchTools API token correctly?\n'
                )
            sys.exit(1)
        permissions = PermissionsGlobalData(**r.json())
        has_permission = True
        for perm in required_perms:
            if not permissions.get_permission(perm):
                err_msg = f'Missing permission "{perm}"'
                self._log.error(f'{err_msg}')
                sys.stderr.write(f'Error: {err_msg}\n')
                has_permission = False
        if not has_permission:
            sys.exit(1)

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
        *,
        stream: bool = False,
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
            stream=stream,
        )
        self._log.debug('Response is %s %s', r.status_code, r.reason)
        r.raise_for_status()
        return r

    def _get(
        self,
        url: str,
        params: dict[str, str] | None = None,
        *,
        stream: bool = False,
    ) -> requests.Response:
        return self._request('GET', url, params, stream=stream)

    def _post(
        self,
        url: str,
        params: dict[str, str] | None = None,
        *,
        stream: bool = False,
    ) -> requests.Response:
        return self._request('POST', url, params, stream=stream)

    def _get_tags(self, tag_type: str) -> typing.Generator[Tag]:
        assert tag_type in {'persons', 'songs'}  # noqa: S101
        r = self._get('/api/tags', params={'type': tag_type})
        result = TagsData(**r.json())
        yield from result.data

    def get_songs(
        self, event: EventShort | None = None, *, require_tags: bool = True
    ) -> tuple[int, typing.Generator[Song]]:
        self._log.info(
            'Getting {}'.format(
                f'songs for {event.start_date:%Y-%m-%d}' if event else 'all songs'
            )
        )

        # Fetch mapping from tag_id to tag_name for song tags.
        song_tags = {}
        if require_tags:
            tags = {tag.id: tag.name for tag in self._get_tags('songs')}

            # NOTE: Using the old AJAX API here because the new one does not contain
            # song tags. If at some point the new API also contains the song tags,
            # this part is obsolete.
            try:
                r = self._post('/?q=churchservice/ajax&func=getAllSongs')
                result = AJAXSongsData(**r.json())
                song_tags = {
                    int(song.id): {tags[tag_id] for tag_id in song.tags}
                    for song in result.data.songs.values()
                }
            except requests.RequestException as e:
                self._log.error(e)

        def empty_generator() -> typing.Generator[Song]:
            yield from []

        def inner_generator() -> typing.Generator[Song]:
            current_page = 0
            last_page = sys.maxsize
            while current_page < last_page:
                r = self._get(api_url, params={'page': str(current_page + 1)})
                tmp = SongsData(**r.json())
                if tmp.meta.pagination:
                    current_page = tmp.meta.pagination.current
                    last_page = tmp.meta.pagination.last_page
                else:
                    current_page = last_page
                for song in tmp.data:
                    if not song.tags:
                        song.tags = song_tags.get(song.id, set())
                    yield song

        # Use the new API to actually fetch the other information.
        try:
            api_url = f'/api/events/{event.id}/agenda/songs' if event else '/api/songs'
            r = self._get(api_url, params={'page': '1', 'limit': '1'})
            result = SongsData(**r.json())
        except requests.exceptions.HTTPError:
            return (0, empty_generator())

        return (
            result.meta.pagination.total
            if result.meta.pagination
            else result.meta.count,
            inner_generator(),
        )

    def _get_calendars(self) -> typing.Generator[Calendar]:
        r = self._get('/api/calendars')
        result = CalendarsData(**r.json())
        yield from result.data

    def get_person(self, person_id: int) -> Person | None:
        # This requires additional permissions in ChurchTools:
        # - churchdb:view alldata(-1)
        # - churchdb:security level person(1)
        try:
            r = self._get(f'/api/persons/{person_id}')
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == requests.codes.forbidden:
                return None
            raise
        else:
            result = PersonsData(**r.json())
            return result.data

    def _get_appointments(self) -> typing.Generator[CalendarAppointment]:
        calendar_ids = ','.join(str(calendar.id) for calendar in self._get_calendars())
        r = self._get(
            '/api/calendars/appointments', params={'calendar_ids[]': calendar_ids}
        )
        result = CalendarAppointmentsData(**r.json())
        yield from result.data

    def get_services(self) -> typing.Generator[Service]:
        r = self._get('/api/services')
        result = ServicesData(**r.json())
        yield from result.data

    def get_events(
        self, from_date: datetime.date, to_date: datetime.date | None = None
    ) -> typing.Generator[EventShort]:
        params = {'from': f'{from_date:%Y-%m-%d}'}
        if to_date:
            params['to'] = f'{to_date:%Y-%m-%d}'
        r = self._get('/api/events', params=params)
        result = EventsData(**r.json())
        yield from result.data

    def get_next_event(
        self, from_date: datetime.datetime, *, agenda_required: bool = False
    ) -> EventShort:
        try:
            event_iter = self.get_events(from_date)
            event = next(event_iter)
            while event.end_date <= from_date:
                event = next(event_iter)
        except StopIteration:
            err_msg = f'No events present after {from_date} in ChurchTools'
            self._log.error(err_msg)
            sys.stderr.write(f'{err_msg}\n')
            sys.exit(1)
        if agenda_required:
            try:
                _agenda = self._get_event_agenda(event)
            except requests.HTTPError as e:
                if e.response.status_code == requests.codes.not_found:
                    date = event.start_date.date()
                    err_msg = (
                        f'No event agenda present for {date:%Y-%m-%d} in ChurchTools'
                    )
                    self._log.error(err_msg)
                    sys.stderr.write(f'{err_msg}\n')
                    sys.exit(1)
                raise
        return event

    def get_full_event(self, event: EventShort) -> EventFull:
        r = self._get(f'/api/events/{event.id}')
        result = EventFullData(**r.json())
        return result.data

    def _get_event_agenda(self, event: EventShort) -> EventAgenda:
        r = self._get(f'/api/events/{event.id}/agenda')
        result = EventAgendaData(**r.json())
        return result.data

    def _get_agenda_export(self, agenda: EventAgenda) -> AgendaExport:
        r = self._post(
            f'/api/agendas/{agenda.id}/export',
            params={
                'target': 'SONG_BEAMER',
                'exportSongs': 'true',
                'appendArrangement': 'false',
                'withCategory': 'false',
            },
        )
        result = AgendaExportData(**r.json())
        return result.data

    def download_agenda_zip(self, event: EventShort) -> requests.Response:
        agenda = self._get_event_agenda(event)
        url = self._get_agenda_export(agenda).url
        return self._get(url, stream=True)

    def download_url(self, full_url: str) -> requests.Response:
        self._log.debug('Request GET %s', full_url)
        return requests.get(
            full_url,
            headers=self._headers(),
            timeout=None,  # noqa: S113
            stream=True,
        )
