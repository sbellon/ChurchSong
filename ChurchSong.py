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

import pptx
import requests


class Configuration:
    def __init__(self, ini_file: pathlib.Path) -> None:
        self._config = configparser.RawConfigParser(
            interpolation=configparser.ExtendedInterpolation(),
        )
        self._config.optionxform = lambda optionstr: optionstr
        self._config.read(ini_file, encoding="utf-8")

    def _expand_vars(self, section: str, option: str) -> str:
        return self._config.get(section, option, vars=dict(os.environ))

    @property
    def base_url(self) -> str:
        return self._expand_vars("ChurchTools.Settings", "base_url")

    @property
    def login_token(self) -> str:
        return self._expand_vars("ChurchTools.Settings", "login_token")

    @property
    def kigo_group(self) -> str:
        return self._expand_vars("ChurchTools.Settings", "kigo_group")

    @property
    def person_dict(self) -> dict[str, str]:
        return dict(self._config.items("ChurchTools.Replacements"))

    @property
    def template_pptx(self) -> pathlib.Path:
        return pathlib.Path(self._expand_vars("SongBeamer.Settings", "template_pptx"))

    @property
    def portraits_dir(self) -> pathlib.Path:
        return pathlib.Path(self._expand_vars("SongBeamer.Settings", "portraits_dir"))

    @property
    def temp_dir(self) -> pathlib.Path:
        return pathlib.Path(self._expand_vars("SongBeamer.Settings", "temp_dir"))

    @property
    def replacements(self) -> list[tuple[str, str]]:
        return [
            (key, val.replace("\\n", "\n").replace("\\r", "\r"))
            for key, val in self._config.items(
                "SongBeamer.Replacements",
                vars=dict(os.environ),
            )
        ]


JSON = dict[str, typing.Any]


class ChurchTools:
    def __init__(self, config: Configuration) -> None:
        self._base_url = config.base_url
        self._login_token = config.login_token
        self._kigo_group = config.kigo_group
        self._person_dict = config.person_dict
        self._temp_dir = config.temp_dir

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Login {self._login_token}",
        }

    def _request(
        self,
        method: str,
        url: str,
        params: dict[str, str] | None = None,
    ) -> requests.Response:
        r = requests.request(
            method,
            f"{self._base_url}{url}",
            headers=self._headers(),
            params=params,
            timeout=None,  # noqa: S113
        )
        r.raise_for_status()
        return r

    def _get(self, url: str, params: dict[str, str] | None = None) -> requests.Response:
        return self._request("GET", url, params)

    def _post(
        self,
        url: str,
        params: JSON | None = None,
    ) -> requests.Response:
        return self._request("POST", url, params)

    def _get_servicegroups(self) -> JSON:
        r = self._get("/api/servicegroups")
        return r.json()["data"]

    def _get_services(self) -> JSON:
        r = self._get("/api/services")
        return r.json()["data"]

    def _get_events(self, from_date: str | None = None) -> JSON:
        r = self._get("/api/events", params={"from": from_date} if from_date else None)
        return r.json()["data"]

    def _get_event(self, event_id: int) -> JSON:
        r = self._get(f"/api/events/{event_id}")
        return r.json()["data"]

    def _get_event_agenda(self, event_id: int) -> JSON:
        r = self._get(f"/api/events/{event_id}/agenda")
        return r.json()["data"]

    def _get_agenda_export(self, agenda_id: int) -> JSON:
        r = self._post(
            f"/api/agendas/{agenda_id}/export",
            params={
                "target": "SONG_BEAMER",
                "exportSongs": True,
                "appendArrangement": False,
                "withCategory": False,
            },
        )
        return r.json()["data"]

    def get_kigo_team(self, from_date: str | None = None) -> dict[str, str]:
        kigo_group_id = None
        for servicegroup in self._get_servicegroups():
            if servicegroup.get("name") == self._kigo_group:
                kigo_group_id = servicegroup["id"]
        if kigo_group_id is None:
            sys.stderr.write(f"Cannot find service group '{self._kigo_group}'.\n")
            return {}
        kigo_groups = {
            service["id"]: service["name"]
            for service in self._get_services()
            if service.get("serviceGroupId") == kigo_group_id
        }
        next_event = self._get_events(from_date)[0]
        _date = next_event["startDate"][0:10]
        event = self._get_event(next_event["id"])
        # Initialize result with all possible groups and the "None" person.
        kigo_team = {
            kigo_group: self._person_dict.get(str(None), str(None))
            for kigo_group in kigo_groups.values()
        }
        # Update with the actual persons of the eventservice.
        kigo_team.update(
            {
                kigo_group: self._person_dict.get(
                    eventservice["name"],
                    eventservice["name"],
                )
                for eventservice in event["eventServices"]
                for kigo_id, kigo_group in kigo_groups.items()
                if eventservice["serviceId"] == kigo_id
            },
        )
        return kigo_team

    def get_url_for_songbeamer_agenda(self, from_date: str | None = None) -> str:
        next_event = self._get_events(from_date)[0]
        _date = next_event["startDate"][0:10]
        agenda = self._get_event_agenda(next_event["id"])
        return self._get_agenda_export(agenda["id"])["url"]

    def download_and_extract_agenda_zip(self, url: str) -> None:
        r = self._get(url)
        buf = io.BytesIO(r.content)
        zipfile.ZipFile(buf, mode="r").extractall(path=self._temp_dir)


class PowerPoint:
    def __init__(self, config: Configuration) -> None:
        self._portraits_dir = config.portraits_dir
        self._temp_dir = config.temp_dir
        self._template_pptx = config.template_pptx
        self._prs = pptx.Presentation(os.fspath(self._template_pptx))

    def create(self, kigo_team: dict[str, str]) -> None:
        slide_layout = self._prs.slide_layouts[0]
        slide = self._prs.slides.add_slide(slide_layout)
        for ph in slide.placeholders:
            name = kigo_team.get(ph._base_placeholder.name)
            if isinstance(ph, pptx.shapes.placeholder.PicturePlaceholder):
                ph.insert_picture(os.fspath(self._portraits_dir / f"{name}.jpeg"))
            elif (
                isinstance(ph, pptx.shapes.placeholder.SlidePlaceholder)
                and ph.has_text_frame
            ):
                ph.text_frame.paragraphs[0].text = name.split(" ")[0]

    def save(self) -> None:
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        self._prs.save(os.fspath(self._temp_dir / self._template_pptx.name))


class SongBeamer:
    def __init__(self, config: Configuration) -> None:
        self._temp_dir = config.temp_dir.resolve()
        self._replacements = config.replacements
        self._schedule_file = self._temp_dir / "Schedule.col"

    def modify_and_save_agenda(self) -> None:
        with self._schedule_file.open(mode="r", encoding="utf-8") as fd:
            content = fd.read()
        for search, replace in self._replacements:
            content = content.replace(search, replace)
        with self._schedule_file.open(mode="w", encoding="utf-8") as fd:
            fd.write(content)

    def launch(self) -> None:
        _ = subprocess.Popen([self._schedule_file], shell=True, cwd=self._temp_dir)  # noqa: S602


def main() -> None:
    config = Configuration(pathlib.Path(__file__).with_suffix(".ini"))
    parser = argparse.ArgumentParser(
        prog="ChurchSong",
        description="Download ChurchTools event agenda and import into SongBeamer.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="verbose output for exceptions",
    )
    parser.add_argument(
        "from_date",
        metavar="FROM_DATE",
        nargs="?",
        help="search in ChurchTools for next event starting at FROM_DATE (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    try:
        ct = ChurchTools(config)
        kigo_team = ct.get_kigo_team(args.from_date)

        pptx = PowerPoint(config)
        pptx.create(kigo_team)
        pptx.save()

        ct.download_and_extract_agenda_zip(
            ct.get_url_for_songbeamer_agenda(args.from_date),
        )

        sb = SongBeamer(config)
        sb.modify_and_save_agenda()
        sb.launch()
    except Exception as e:
        if args.verbose:
            raise
        sys.stderr.write(f"{e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
