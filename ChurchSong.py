#!/usr/bin/env python

from __future__ import annotations

import argparse
import configparser
import io
import os
import pathlib
import subprocess
import sys
import typing
import zipfile
from collections import defaultdict

import marshmallow
import marshmallow_dataclass
import pptx
import pptx.shapes
import pptx.shapes.placeholder
import requests


class Configuration:
    def __init__(self, ini_file: pathlib.Path) -> None:
        self._config = configparser.RawConfigParser(
            interpolation=configparser.ExtendedInterpolation(),
        )
        self._config.optionxform = lambda optionstr: optionstr
        self._config.read(ini_file, encoding='utf-8')

    def _expand_vars(self, section: str, option: str) -> str:
        return self._config.get(section, option, vars=dict(os.environ))

    @property
    def base_url(self) -> str:
        return self._expand_vars('ChurchTools.Settings', 'base_url')

    @property
    def login_token(self) -> str:
        return self._expand_vars('ChurchTools.Settings', 'login_token')

    @property
    def person_dict(self) -> dict[str, str]:
        return dict(self._config.items('ChurchTools.Replacements'))

    @property
    def template_pptx(self) -> pathlib.Path:
        return pathlib.Path(self._expand_vars('SongBeamer.Settings', 'template_pptx'))

    @property
    def portraits_dir(self) -> pathlib.Path:
        return pathlib.Path(self._expand_vars('SongBeamer.Settings', 'portraits_dir'))

    @property
    def temp_dir(self) -> pathlib.Path:
        return pathlib.Path(self._expand_vars('SongBeamer.Settings', 'temp_dir'))

    @property
    def replacements(self) -> list[tuple[str, str]]:
        return [
            (key, val.replace('\\n', '\n').replace('\\r', '\r'))
            for key, val in self._config.items(
                'SongBeamer.Replacements',
                vars=dict(os.environ),
            )
        ]


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
    name: str


@deserialize
class ServicesData:
    Schema: SchemaType  # for pylance
    data: list[Service]


@deserialize
class EventShort:
    Schema: SchemaType  # for pylance
    id: int
    startDate: str  # noqa: N815


@deserialize
class EventsData:
    Schema: SchemaType  # for pylance
    data: list[EventShort]


@deserialize
class EventService:
    Schema: SchemaType  # for pylance
    serviceId: int  # noqa: N815
    name: str


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
        r = requests.request(
            method,
            f'{self._base_url}{url}',
            headers=self._headers(),
            params=params,
            timeout=None,  # noqa: S113
        )
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

    def _get_events(self, from_date: str | None = None) -> list[EventShort]:
        r = self._get('/api/events', params={'from': from_date} if from_date else None)
        result = EventsData.Schema().load(r.json())
        assert isinstance(result, EventsData)
        return result.data

    def _get_next_event(self, from_date: str | None = None) -> EventShort:
        return self._get_events(from_date)[0]

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

    def get_service_leads(self, from_date: str | None = None) -> defaultdict[str, str]:
        services = self._get_services()
        next_event = self._get_next_event(from_date)
        event = self._get_event(next_event.id)
        # Initialize the "None" person for all services.
        service_leads = defaultdict(lambda: self._person_dict.get(str(None), str(None)))
        # Update with the actual persons of the eventservice.
        service_leads.update(
            {
                service.name: self._person_dict.get(
                    eventservice.name,
                    eventservice.name,
                )
                for eventservice in event.eventServices
                for service in services
                if eventservice.serviceId == service.id
            },
        )
        return service_leads

    def get_url_for_songbeamer_agenda(self, from_date: str | None = None) -> str:
        next_event = self._get_next_event(from_date)
        date = next_event.startDate[0:10]
        try:
            agenda = self._get_event_agenda(next_event.id)
        except requests.HTTPError as e:
            if e.response.status_code == requests.codes['not_found']:
                sys.stderr.write(f'No event agenda present for {date} in ChurchTools\n')
                sys.exit(1)
            raise
        return self._get_agenda_export(agenda.id).url

    def download_and_extract_agenda_zip(self, url: str) -> None:
        r = self._get(url)
        assert isinstance(r.content, bytes)
        buf = io.BytesIO(r.content)
        zipfile.ZipFile(buf, mode='r').extractall(path=self._temp_dir)


class PowerPoint:
    def __init__(self, config: Configuration) -> None:
        self._portraits_dir = config.portraits_dir
        self._temp_dir = config.temp_dir
        self._template_pptx = config.template_pptx
        self._prs = pptx.Presentation(os.fspath(self._template_pptx))

    def create(self, service_leads: dict[str, str]) -> None:
        slide_layout = self._prs.slide_layouts[0]
        slide = self._prs.slides.add_slide(slide_layout)
        for ph in slide.placeholders:
            name = service_leads[ph._base_placeholder.name]  # noqa: SLF001 # pyright: ignore[reportAttributeAccessIssue]
            if isinstance(ph, pptx.shapes.placeholder.PicturePlaceholder):
                ph.insert_picture(os.fspath(self._portraits_dir / f'{name}.jpeg'))
            elif (
                isinstance(ph, pptx.shapes.placeholder.SlidePlaceholder)
                and ph.has_text_frame
            ):
                ph.text_frame.paragraphs[0].text = name.split(' ')[0]

    def save(self) -> None:
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        self._prs.save(os.fspath(self._temp_dir / self._template_pptx.name))


class SongBeamer:
    def __init__(self, config: Configuration) -> None:
        self._replacements = config.replacements
        self._temp_dir = config.temp_dir.resolve()
        self._schedule_filename = 'Schedule.col'
        self._schedule_filepath = self._temp_dir / self._schedule_filename

    def modify_and_save_agenda(self) -> None:
        with self._schedule_filepath.open(mode='r', encoding='utf-8') as fd:
            content = fd.read()
        for search, replace in self._replacements:
            content = content.replace(search, replace)
        with self._schedule_filepath.open(mode='w', encoding='utf-8') as fd:
            fd.write(content)

    def launch(self) -> None:
        subprocess.run(  # noqa: S602
            ['start', self._schedule_filename],  # noqa: S607
            shell=True,
            check=True,
            cwd=self._temp_dir,
        )


def main() -> None:
    config = Configuration(pathlib.Path(__file__).with_suffix('.ini'))
    parser = argparse.ArgumentParser(
        prog='ChurchSong',
        description='Download ChurchTools event agenda and import into SongBeamer.',
    )
    parser.add_argument(
        '-v',
        '--verbose',
        action='store_true',
        help='verbose output for exceptions',
    )
    parser.add_argument(
        'from_date',
        metavar='FROM_DATE',
        nargs='?',
        help='search in ChurchTools for next event starting at FROM_DATE (YYYY-MM-DD)',
    )
    args = parser.parse_args()

    try:
        ct = ChurchTools(config)
        service_leads = ct.get_service_leads(args.from_date)

        pp = PowerPoint(config)
        pp.create(service_leads)
        pp.save()

        ct.download_and_extract_agenda_zip(
            ct.get_url_for_songbeamer_agenda(args.from_date),
        )

        sb = SongBeamer(config)
        sb.modify_and_save_agenda()
        sb.launch()
    except Exception as e:
        if args.verbose:
            raise
        sys.stderr.write(f'{e}\n')
        sys.exit(1)


if __name__ == '__main__':
    main()
