from __future__ import annotations

import dataclasses
import datetime  # noqa: TCH003
import io
import sys
import typing
import zipfile
from collections import defaultdict

import alive_progress
import marshmallow
import marshmallow_dataclass
import prettytable
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
    start_date: datetime.datetime = dataclasses.field(
        metadata={'data_key': 'startDate'}
    )


@deserialize
class EventsData:
    Schema: SchemaType  # for pylance
    data: list[EventShort]


@deserialize
class EventService:
    Schema: SchemaType  # for pylance
    name: str | None
    service_id: int = dataclasses.field(metadata={'data_key': 'serviceId'})


@deserialize
class EventFull:
    Schema: SchemaType  # for pylance
    id: int
    event_services: list[EventService] = dataclasses.field(
        metadata={'data_key': 'eventServices'}
    )


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


@deserialize
class File:
    Schema: SchemaType  # for pylance
    name: str
    file_url: str = dataclasses.field(metadata={'data_key': 'fileUrl'})


@deserialize
class Arrangement:
    Schema: SchemaType  # for pylance
    id: int
    name: str
    bpm: str | None
    beat: str | None
    duration: int
    files: list[File]
    source_name: str | None = dataclasses.field(metadata={'data_key': 'sourceName'})
    source_reference: str | None = dataclasses.field(
        metadata={'data_key': 'sourceReference'}
    )
    key_of_arrangement: str | None = dataclasses.field(
        metadata={'data_key': 'keyOfArrangement'}
    )


@deserialize
class Song:
    Schema: SchemaType  # for pylance
    id: int
    name: str
    author: str | None
    ccli: str | None
    arrangements: list[Arrangement]
    tags: set[str] = dataclasses.field(
        default_factory=set, metadata={'required': False}
    )


@deserialize
class Pagination:
    Schema: SchemaType  # for pylance
    total: int
    limit: int
    current: int
    last_page: int = dataclasses.field(
        default_factory=int, metadata={'data_key': 'lastPage'}
    )


@deserialize
class SongsMeta:
    Schema: SchemaType  # for pylance
    count: int
    pagination: Pagination


@deserialize
class SongsData:
    Schema: SchemaType  # for pylance
    data: list[Song]
    meta: SongsMeta


@deserialize
class Tag:
    Schema: SchemaType  # for pylance
    id: int
    name: str


@deserialize
class TagsData:
    Schema: SchemaType  # for pylance
    data: list[Tag]


@deserialize
class AJAXSong:
    Schema: SchemaType  # for pylance
    id: str
    tags: list[int]


@deserialize
class AJAXSongs:
    Schema: SchemaType  # for pylance
    songs: dict[str, AJAXSong]


@deserialize
class AJAXSongsData:
    Schema: SchemaType  # for pylance
    data: AJAXSongs


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

    def _get_tags(self, tag_type: str) -> typing.Generator[Tag]:
        assert tag_type in {'persons', 'songs'}
        r = self._get('/api/tags', params={'type': tag_type})
        result = TagsData.Schema().load(r.json())
        assert isinstance(result, TagsData)
        yield from result.data

    def _get_songs(self) -> tuple[int, typing.Generator[Song]]:
        # Fetch mapping from tag_id to tag_name for song tags.
        tags = {tag.id: tag.name for tag in self._get_tags('songs')}

        # NOTE: Using the old AJAX API here because the new one does not contain tags.
        # If at some point the new API also contains the tags, this part is obsolete.
        r = self._post('/?q=churchservice/ajax&func=getAllSongs')
        result = AJAXSongsData.Schema().load(r.json())
        assert isinstance(result, AJAXSongsData)
        song_tags = {
            int(song.id): {tags[tag_id] for tag_id in song.tags}
            for song in result.data.songs.values()
        }

        # Use the new API to actually fetch the other information.
        r = self._get('/api/songs', params={'page': '1', 'limit': '1'})
        result = SongsData.Schema().load(r.json())
        assert isinstance(result, SongsData)

        def inner_generator() -> typing.Generator[Song]:
            current_page = 0
            last_page = sys.maxsize
            while current_page < last_page:
                r = self._get('/api/songs', params={'page': str(current_page + 1)})
                tmp = SongsData.Schema().load(r.json())
                assert isinstance(tmp, SongsData)
                current_page = tmp.meta.pagination.current
                last_page = tmp.meta.pagination.last_page
                for song in tmp.data:
                    song.tags = song_tags[song.id]
                    yield song

        return result.meta.pagination.total, inner_generator()

    def _get_services(self) -> typing.Generator[Service]:
        r = self._get('/api/services')
        result = ServicesData.Schema().load(r.json())
        assert isinstance(result, ServicesData)
        yield from result.data

    def _get_events(
        self, from_date: datetime.date | None = None
    ) -> typing.Generator[EventShort]:
        r = self._get(
            '/api/events',
            params={'from': f'{from_date:%Y-%m-%d}'} if from_date else None,
        )
        result = EventsData.Schema().load(r.json())
        assert isinstance(result, EventsData)
        yield from result.data

    def _get_next_event(self, from_date: datetime.date | None = None) -> EventShort:
        try:
            return next(self._get_events(from_date))
        except StopIteration:
            err_msg = 'No events present{} in ChurchTools'.format(
                f' after {from_date:%Y-%m-%d}' if from_date else ''
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

    def _assert_permission(self, perm_group: str, perm_name: str) -> None:
        r = self._get('/api/permissions/global')
        data = r.json()['data']
        if not (
            (group := data.get(perm_group, False))
            and (perm := group.get(perm_name, False))
            and perm
        ):
            err_msg = f'Missing permission "{perm_group}:{perm_name}"'
            self._log.error(f'{err_msg}')
            sys.stderr.write(f'Error: {err_msg}\n')
            sys.exit(1)

    def get_service_leads(
        self, from_date: datetime.date | None = None
    ) -> defaultdict[str, set[str]]:
        self._log.info('Fetching service teams')
        next_event = self._get_next_event(from_date)
        event = self._get_event(next_event.id)
        service_id2name = {service.id: service.name for service in self._get_services()}
        service_leads = defaultdict(
            lambda: {self._person_dict.get(str(None), str(None))}
        )
        for eventservice in event.event_services:
            service_name = service_id2name[eventservice.service_id]
            person_name = self._person_dict.get(
                str(eventservice.name), str(eventservice.name)
            )
            if service_name not in service_leads:
                service_leads[service_name] = {person_name}
            else:
                service_leads[service_name].add(person_name)
        return service_leads

    def _get_url_for_songbeamer_agenda(
        self, from_date: datetime.date | None = None
    ) -> str:
        self._log.info('Fetching SongBeamer export URL')
        next_event = self._get_next_event(from_date)
        try:
            agenda = self._get_event_agenda(next_event.id)
        except requests.HTTPError as e:
            if e.response.status_code == requests.codes['not_found']:
                date = next_event.start_date.date()
                err_msg = f'No event agenda present for {date:%Y-%m-%d} in ChurchTools'
                self._log.error(err_msg)
                sys.stderr.write(f'{err_msg}\n')
                sys.exit(1)
            raise
        return self._get_agenda_export(agenda.id).url

    def download_and_extract_agenda_zip(
        self, from_date: datetime.date | None = None
    ) -> None:
        self._log.info('Downloading and extracting SongBeamer export')
        self._assert_permission('churchservice', 'view agenda')
        url = self._get_url_for_songbeamer_agenda(from_date)
        r = self._get(url)
        buf = io.BytesIO(r.content)
        zipfile.ZipFile(buf, mode='r').extractall(path=self._temp_dir)

    def _check_sng_file(self, url: str) -> bool:
        self._log.debug('Request GET %s', url)
        r = requests.get(
            url,
            headers=self._headers(),
            timeout=None,  # noqa: S113
        )
        return any(
            line.startswith(b'#BackgroundImage=') for line in r.content.splitlines()
        )

    def verify_songs(self, include_tags: list[str], exclude_tags: list[str]) -> None:
        self._log.info('Verifying ChurchTools song database')
        self._assert_permission('churchservice', 'view songcategory')

        def to_str(b: bool) -> str:  # noqa: FBT001
            return 'missing' if b else ''

        table = prettytable.PrettyTable()
        table.field_names = [
            'Id',
            'Song',
            'CCLI',
            'Tags',
            'Arrangement',
            'Source',
            'Duration',
            '.sng',
            'BGImage',
        ]
        table.align['Id'] = 'r'
        for field_id in table.field_names[1:]:
            table.align[field_id] = 'l'
        number_songs, songs = self._get_songs()
        with alive_progress.alive_bar(
            number_songs, title='Verifying Songs', spinner=None, receipt=False
        ) as bar:
            for song in sorted(songs, key=lambda e: e.name):
                if (
                    include_tags and not any(tag in song.tags for tag in include_tags)
                ) or (exclude_tags and any(tag in song.tags for tag in exclude_tags)):
                    bar()
                    continue
                song_id = f'#{song.id}'
                song_name = song.name if song.name else f'#{song.id}'
                no_ccli = song.author is None or song.ccli is None
                no_tags = not song.tags
                no_arrangement = not song.arrangements
                if no_arrangement:
                    table.add_row(
                        [
                            song_id,
                            song_name,
                            to_str(no_ccli),
                            to_str(no_tags),
                            to_str(no_arrangement),
                            '',
                            '',
                            '',
                            '',
                        ]
                    )
                for arrangement in song.arrangements:
                    arrangement_name = (
                        arrangement.name if arrangement.name else f'#{arrangement.id}'
                    )
                    source = (
                        f'{arrangement.source_name} {arrangement.source_reference}'
                        if arrangement.source_name and arrangement.source_reference
                        else None
                    )
                    no_duration = arrangement.duration == 0
                    no_sng_file = True
                    no_bgimage = True
                    for file in arrangement.files:
                        if file.name.endswith('.sng'):
                            no_sng_file = False
                            no_bgimage &= not self._check_sng_file(file.file_url)
                    if (
                        no_ccli
                        or (not source or source not in song.tags)
                        or no_duration
                        or no_sng_file
                        or no_bgimage
                    ):
                        table.add_row(
                            [
                                song_id,
                                song_name,
                                to_str(no_ccli),
                                f'missing "{source}"' if source else to_str(no_tags),
                                arrangement_name,
                                to_str(source is None),
                                to_str(no_duration),
                                to_str(no_sng_file),
                                to_str(no_bgimage),
                            ]
                        )
                bar()
        sys.stdout.write(f'{table.get_string()}\n')
