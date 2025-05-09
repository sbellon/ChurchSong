# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import datetime
import enum
import re
import sys
import typing
import warnings

import pydantic
import requests

from churchsong.configuration import Configuration
from churchsong.utils import CliError


class DeprecationAwareModel(pydantic.BaseModel):
    _DEPRECATION_KEY: typing.ClassVar[typing.Final[str]] = '@deprecated'
    _RE_STRING_DEPRECATIONS: typing.ClassVar[typing.Final] = re.compile(
        r'(?P<old>\w+) \(now: (?P<new>\w+)\)'
    )

    @pydantic.model_validator(mode='before')
    @classmethod
    def _warn_deprecated_fields(
        cls, data: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        deprecated_fields = data.get(cls._DEPRECATION_KEY, {})
        if isinstance(deprecated_fields, str):
            deprecated_fields = {
                m.group('old'): m.group('new')
                for m in cls._RE_STRING_DEPRECATIONS.finditer(deprecated_fields)
            }
        for old_field, new_field in deprecated_fields.items():
            if old_field in cls.model_fields and new_field is not None:
                warnings.warn(
                    f"Model '{cls.__name__}' defines deprecated field '{old_field}', "
                    f"consider using '{new_field}' instead.",
                    DeprecationWarning,
                    stacklevel=1,
                )
        return data


class PermissionsGlobalChurchCal(DeprecationAwareModel):
    view: bool
    view_category: list[int] = pydantic.Field(alias='view category')


class PermissionsGlobalChurchService(DeprecationAwareModel):
    view: bool
    view_servicegroup: list[int] = pydantic.Field(alias='view servicegroup')
    view_history: bool = pydantic.Field(alias='view history')
    view_events: list[int] = pydantic.Field(alias='view events')
    view_agenda: list[int] = pydantic.Field(alias='view agenda')
    view_songcategory: list[int] = pydantic.Field(alias='view songcategory')


class PermissionsGlobal(DeprecationAwareModel):
    churchcal: PermissionsGlobalChurchCal
    churchservice: PermissionsGlobalChurchService


class PermissionsGlobalData(DeprecationAwareModel):
    data: PermissionsGlobal

    def get_permission(self, perm: str) -> bool | list[int]:
        perm = perm.replace(' ', '_')
        obj = self.data
        for key in perm.split(':'):
            if hasattr(obj, key):
                obj = getattr(obj, key)
            else:
                return False
        match obj:
            case bool():
                return obj
            case list() if all(
                isinstance(item, int) for item in typing.cast('list[typing.Any]', obj)
            ):
                return typing.cast('list[typing.Any]', obj)
            case _:
                return False


class Address(DeprecationAwareModel):
    name: str | None
    street: str | None
    zip: str | None
    city: str | None


class RepeatId(enum.Enum):
    NONE = 0
    DAILY = 1
    WEEKLY = 7
    MONTHLY_BY_DATE = 31
    MONTHLY_BY_WEEKDAY = 32
    YEARLY = 365
    MANUALLY = 999


class Image(DeprecationAwareModel):
    name: str | None
    image_url: str | None = pydantic.Field(alias='imageUrl')


class CalendarAppointmentBase(DeprecationAwareModel):
    title: str
    subtitle: str | None
    description: str | None
    image: Image | None
    link: str | None
    start_date: datetime.datetime = pydantic.Field(alias='startDate')
    end_date: datetime.datetime = pydantic.Field(alias='endDate')
    all_day: bool = pydantic.Field(alias='allDay')
    repeat_id: RepeatId | None = pydantic.Field(alias='repeatId')
    repeat_frequency: int | None = pydantic.Field(alias='repeatFrequency')
    address: Address | None


class CalendarAppointmentAppointment(DeprecationAwareModel):
    base: CalendarAppointmentBase

    @pydantic.model_validator(mode='before')
    @classmethod
    def _patch_base_dates(cls, data: dict[str, typing.Any]) -> dict[str, typing.Any]:
        if (base := data.get('base')) and (calculated := data.get('calculated', {})):
            all_day = base.get('allDay', False)
            for key, time_suffix in (
                ('startDate', 'T00:00:00Z'),
                ('endDate', 'T23:59:59Z'),
            ):
                if value := calculated.get(key):
                    if all_day and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                        value = f'{value}{time_suffix}'
                    base[key] = value

        return data


class CalendarAppointmentItem(DeprecationAwareModel):
    appointment: CalendarAppointmentAppointment


class CalendarAppointmentsData(DeprecationAwareModel):
    data: list[CalendarAppointmentItem]


class Calendar(DeprecationAwareModel):
    id: int
    name: str


class CalendarsData(DeprecationAwareModel):
    data: list[Calendar]


class Person(DeprecationAwareModel):
    firstname: str = pydantic.Field(alias='firstName')
    lastname: str = pydantic.Field(alias='lastName')
    nickname: str | None


class PersonsData(DeprecationAwareModel):
    data: Person


class Service(DeprecationAwareModel):
    id: int
    name: str | None


class ServicesData(DeprecationAwareModel):
    data: list[Service]


class EventShort(DeprecationAwareModel):
    id: int
    name: str
    start_date: datetime.datetime = pydantic.Field(alias='startDate')
    end_date: datetime.datetime = pydantic.Field(alias='endDate')


class EventsData(DeprecationAwareModel):
    data: list[EventShort]


class EventService(DeprecationAwareModel):
    person_id: int | None = pydantic.Field(alias='personId')
    name: str | None
    service_id: int = pydantic.Field(alias='serviceId')

    # If a `person` element is present in the `eventService`, prefer it over the
    # `eventService.name` for finding the person's name. Within the `person`, prefer
    # a `person.domainAttributes.firstName` and `person.domainAttributes.lastName`,
    # if set, over `person.title`.
    @pydantic.model_validator(mode='before')
    @classmethod
    def _flatten_person_name(cls, data: dict[str, typing.Any]) -> dict[str, typing.Any]:
        person: dict[str, typing.Any] | None = data.get('person')
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
                data['name'] = name
        return data


class EventFileDomainType(enum.StrEnum):
    FILE = 'file'
    LINK = 'link'


class EventFile(DeprecationAwareModel):
    title: str
    domain_type: EventFileDomainType = pydantic.Field(alias='domainType')
    frontend_url: str = pydantic.Field(alias='frontendUrl')


class EventFull(DeprecationAwareModel):
    id: int
    start_date: datetime.datetime = pydantic.Field(alias='startDate')
    end_date: datetime.datetime = pydantic.Field(alias='endDate')
    event_files: list[EventFile] = pydantic.Field(alias='eventFiles')
    event_services: list[EventService] = pydantic.Field(alias='eventServices')


class EventFullData(DeprecationAwareModel):
    data: EventFull


class EventAgendaSong(DeprecationAwareModel):
    song_id: int = pydantic.Field(alias='songId')
    arrangement_id: int = pydantic.Field(alias='arrangementId')
    title: str


class EventAgendaItemType(enum.StrEnum):
    HEADER = 'header'
    NORMAL = 'normal'
    SONG = 'song'


class EventAgendaItem(DeprecationAwareModel):
    title: str
    type: EventAgendaItemType = EventAgendaItemType.NORMAL
    song: EventAgendaSong | None = None


class EventAgenda(DeprecationAwareModel):
    id: int
    items: list[EventAgendaItem]


class EventAgendaData(DeprecationAwareModel):
    data: EventAgenda


class AgendaExport(DeprecationAwareModel):
    url: str


class AgendaExportData(DeprecationAwareModel):
    data: AgendaExport


class File(DeprecationAwareModel):
    name: str
    file_url: str = pydantic.Field(alias='fileUrl')


class Arrangement(DeprecationAwareModel):
    id: int
    name: str
    is_default: bool = pydantic.Field(alias='isDefault')
    source_name: str | None = pydantic.Field(alias='sourceName')
    source_reference: str | None = pydantic.Field(alias='sourceReference')
    key_of_arrangement: str | None = pydantic.Field(alias='keyOfArrangement')
    beat: str | None
    tempo: int | None
    duration: int | None
    files: list[File]
    sng_file_content: list[str] = []  # NOT filled by ChurchTools, but internally


class Tag(DeprecationAwareModel):
    id: int
    name: str


class TagsData(DeprecationAwareModel):
    data: list[Tag]


class Song(DeprecationAwareModel):
    id: int
    name: str
    author: str | None
    ccli: str | None
    arrangements: list[Arrangement]
    tags: list[Tag] = []


class Pagination(DeprecationAwareModel):
    total: int
    limit: int
    current: int
    last_page: int = pydantic.Field(alias='lastPage')


class SongsMeta(DeprecationAwareModel):
    count: int
    pagination: Pagination | None = None


class SongsData(DeprecationAwareModel):
    data: list[Song]
    meta: SongsMeta


class SongData(DeprecationAwareModel):
    data: Song


ParamsType = typing.Mapping[
    str, str | int | float | bool | list[str] | list[int] | None
]


class ChurchToolsAPI:
    def __init__(self, config: Configuration) -> None:
        self._log = config.log
        self._base_url = config.churchtools.settings.base_url
        self._login_token = config.churchtools.settings.login_token
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
            msg = (
                f'{e}\n\n'
                'Did you configure the URL of your ChurchTools instance correctly?'
            )
            raise CliError(msg) from None
        except requests.exceptions.HTTPError as e:
            self._log.error(e)
            msg = f'{e}'
            if e.response.status_code in (
                requests.codes.forbidden,
                requests.codes.unauthorized,
            ):
                msg += '\n\nDid you configure your ChurchTools API token correctly?'
            raise CliError(msg) from None
        permissions = PermissionsGlobalData(**r.json())
        if missing_perms := {
            perm for perm in required_perms if not permissions.get_permission(perm)
        }:
            msg = 'Missing required permissions for token user: {}'.format(
                ', '.join(f'"{perm}"' for perm in missing_perms)
            )
            self._log.error(msg)
            raise CliError(msg) from None

    def _headers(self) -> dict[str, str]:
        return {
            'Accept': 'application/json',
            'Authorization': f'Login {self._login_token}',
        }

    def _request(
        self,
        method: str,
        url: str,
        params: ParamsType | None = None,
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
            stream=stream,
        )
        self._log.debug('Response is %s %s', r.status_code, r.reason)
        r.raise_for_status()
        return r

    def _get(
        self,
        url: str,
        params: ParamsType | None = None,
        *,
        stream: bool = False,
    ) -> requests.Response:
        return self._request('GET', url, params, stream=stream)

    def _post(
        self,
        url: str,
        params: ParamsType | None = None,
        *,
        stream: bool = False,
    ) -> requests.Response:
        return self._request('POST', url, params, stream=stream)

    def _get_song_tags(self, song_id: int) -> list[Tag]:
        r = self._get('/api/songs', params={'ids[]': f'{song_id}', 'include': 'tags'})
        result = SongsData(**r.json())
        return result.data[0].tags

    def get_songs(
        self, event: EventShort | None = None, *, require_tags: bool = True
    ) -> tuple[int, typing.Generator[Song]]:
        if event:
            self._log.info(f'Getting songs for {event.start_date:%Y-%m-%d}')
            api_url = f'/api/events/{event.id}/agenda/songs'
            params = {}  # {'include': 'tags'} is sadly not supported by that API.
        else:
            self._log.info('Getting all songs')
            api_url = '/api/songs'
            params = {'include': 'tags'}
            require_tags = False  # Tags are already included in the result by default.

        def empty_generator() -> typing.Generator[Song]:
            yield from []

        def inner_generator() -> typing.Generator[Song]:
            current_page = 0
            last_page = sys.maxsize
            while current_page < last_page:
                r = self._get(api_url, params={'page': str(current_page + 1), **params})
                tmp = SongsData(**r.json())
                if tmp.meta.pagination:
                    current_page = tmp.meta.pagination.current
                    last_page = tmp.meta.pagination.last_page
                else:
                    current_page = last_page
                for song in tmp.data:
                    if require_tags and not song.tags:
                        song.tags = self._get_song_tags(song.id)
                    yield song

        try:
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

    def get_song(self, song_id: int) -> Song:
        r = self._get(f'/api/songs/{song_id}')
        result = SongData(**r.json())
        return result.data

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

    def get_appointments(
        self, event: EventShort
    ) -> typing.Generator[CalendarAppointmentBase]:
        """Get appointments of the next 10 weeks *after* event."""
        next_10weeks = event.start_date + datetime.timedelta(weeks=10)
        r = self._get(
            '/api/calendars/appointments',
            params={
                'calendar_ids[]': [calendar.id for calendar in self._get_calendars()],
                'from': f'{event.start_date:%Y-%m-%d}',
                'to': f'{next_10weeks:%Y-%m-%d}',
            },
        )
        result = CalendarAppointmentsData(**r.json())
        yield from (
            base
            for item in result.data
            if (base := item.appointment.base)
            and not (  # filter out current event
                base.title == event.name and base.start_date == event.start_date
            )
        )

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
            date = f'{from_date.date():%Y-%m-%d}'
            msg = f'No events present after {date} in ChurchTools.'
            self._log.error(msg)
            raise CliError(msg) from None
        if agenda_required:
            try:
                _agenda = self.get_event_agenda(event)
            except requests.HTTPError as e:
                if e.response.status_code == requests.codes.not_found:
                    date = f'{event.start_date.date():%Y-%m-%d}'
                    msg = f'No event agenda present for {date} in ChurchTools.'
                    self._log.error(msg)
                    raise CliError(msg) from None
                raise
        return event

    def get_full_event(self, event: EventShort) -> EventFull:
        r = self._get(f'/api/events/{event.id}')
        result = EventFullData(**r.json())
        return result.data

    def get_event_agenda(self, event: EventShort) -> EventAgenda:
        r = self._get(f'/api/events/{event.id}/agenda')
        result = EventAgendaData(**r.json())
        return result.data

    def download_url(self, full_url: str) -> requests.Response:
        self._log.debug('Request GET %s', full_url)
        return requests.get(full_url, headers=self._headers(), stream=True)
