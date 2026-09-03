# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import dataclasses
import datetime
import logging
import subprocess
import typing

import packaging.version
import pytest
import requests
import typer.main
import typer.testing

from churchsong import __main__ as cli
from churchsong.churchtools import EventShort
from churchsong.churchtools.events import Item, ItemType, Person
from churchsong.churchtools.song_statistics import ChurchToolsSongStatistics
from churchsong.configuration import Configuration
from churchsong.interactivescreen import DownloadSelection
from tests.conftest import make_config

if typing.TYPE_CHECKING:
    import pathlib

runner = typer.testing.CliRunner()


@pytest.fixture(scope='session', autouse=True)
def resolve_cli_annotations() -> None:
    # Python 3.14 evaluates annotations lazily (PEP 649), and the `typing.Annotated`
    # metadata of the commands reads attributes off the module globals, e.g.
    # `ChurchToolsSongVerification.available_checks()`. That expression therefore only
    # runs when Typer first builds the command tree, and is cached from then on. Force
    # it here while the real classes are still in place - otherwise whichever test
    # invokes the CLI first decides the outcome, and one that installs a fake
    # beforehand would resolve the annotations against the fake and fail.
    typer.main.get_command(cli.app)


# Rich wraps its output at the terminal width, which would split the strings
# the assertions below look for.
CLI_ENV = {'COLUMNS': '200'}

AGENDA_ITEMS = [Item(ItemType.SONG, 'Amazing Grace')]
SERVICE_ITEMS = [Item(ItemType.SERVICE, 'Pastor')]
SERVICE_LEADS = {'Pastor': {Person(fullname='John Newton', shortname='John')}}

TEMPLATES = {
    'PowerPoint': {
        'Services': {'template_pptx': 'services.pptx'},
        'Appointments': {'template_pptx': 'appointments.pptx'},
    }
}


def invoke(
    args: list[str], config: Configuration | None = None
) -> typer.testing.Result:
    return runner.invoke(cli.app, args, obj=config or make_config(), env=CLI_ENV)


def set_later_version(monkeypatch: pytest.MonkeyPatch, version: str | None) -> None:
    later = packaging.version.Version(version) if version else None
    monkeypatch.setattr(
        Configuration, 'later_version_available', property(lambda _self: later)
    )


@pytest.fixture(autouse=True)
def offline_version_check(monkeypatch: pytest.MonkeyPatch) -> None:
    # Without this every command would query PyPI over the network.
    set_later_version(monkeypatch, None)


def no_uv(_cmd: str) -> str | None:
    return None


def some_uv(_cmd: str) -> str | None:
    return '/usr/bin/uv'


def make_event_short() -> EventShort:
    return EventShort.model_validate(
        {
            'id': 42,
            'name': 'Sunday Service',
            'startDate': '2026-08-23T10:00:00Z',
            'endDate': '2026-08-23T12:00:00Z',
        }
    )


@dataclasses.dataclass
class Pipeline:
    """Records what _handle_agenda() drove its (faked) collaborators to do."""

    steps: list[str] = dataclasses.field(default_factory=list[str])
    download_kwargs: dict[str, object] = dataclasses.field(
        default_factory=dict[str, object]
    )
    schedule_kwargs: dict[str, object] = dataclasses.field(
        default_factory=dict[str, object]
    )
    requested_date: datetime.datetime | None = None
    agenda_required: bool = False
    service_leads: object = None


def install_fake_pipeline(  # noqa: C901 (one small fake per collaborator)
    monkeypatch: pytest.MonkeyPatch,
    *,
    appointment_permission: bool = True,
    failing_step: str | None = None,
) -> Pipeline:
    """Replace everything _handle_agenda() orchestrates with recording fakes."""
    pipeline = Pipeline()

    def record(step: str) -> None:
        pipeline.steps.append(step)
        if step == failing_step:
            msg = '502 Server Error: Bad Gateway for url: https://churchtools.test'
            raise requests.exceptions.HTTPError(msg)

    class FakeChurchToolsAPI:
        def __init__(self, _config: Configuration) -> None:
            record('api')

        def get_next_event(
            self, from_date: datetime.datetime, *, agenda_required: bool = False
        ) -> EventShort:
            record('get_next_event')
            pipeline.requested_date = from_date
            pipeline.agenda_required = agenda_required
            return make_event_short()

        def has_permissions(
            self, _required_perms: list[str], log_reason: str = ''
        ) -> bool:
            record(f'permissions:{log_reason}')
            return appointment_permission

        def get_appointments(self, _event: EventShort) -> list[object]:
            return []

    class FakeSongSheets:
        def upload(self) -> None:
            record('song_sheets.upload')

    class FakeChurchToolsEvent:
        def __init__(
            self, _cta: object, _event: EventShort, _config: Configuration
        ) -> None:
            record('event')

        def download_agenda_items(
            self, **kwargs: object
        ) -> tuple[list[Item], FakeSongSheets]:
            record('download')
            pipeline.download_kwargs = kwargs
            return AGENDA_ITEMS, FakeSongSheets()

        def get_service_info(
            self,
        ) -> tuple[list[Item], dict[str, set[Person]]]:
            record('service_info')
            return SERVICE_ITEMS, SERVICE_LEADS

    class FakeImmichAPI:
        def __init__(self, _config: Configuration) -> None:
            record('immich')

    class FakePowerPointServices:
        def __init__(self, _config: Configuration) -> None:
            record('services')

        def create(self, service_leads: dict[str, set[Person]]) -> None:
            record('services.create')
            pipeline.service_leads = service_leads

        def save(self) -> None:
            record('services.save')

    class FakePowerPointAppointments:
        def __init__(
            self, _config: Configuration, _event_start_date: datetime.datetime
        ) -> None:
            record('appointments')

        def create(self, _appointments: typing.Iterable[object]) -> None:
            record('appointments.create')

        def save(self) -> None:
            record('appointments.save')

    class FakeSongBeamer:
        def __init__(self, _config: Configuration) -> None:
            record('songbeamer')

        def create_schedule(self, **kwargs: object) -> None:
            record('create_schedule')
            pipeline.schedule_kwargs = kwargs

        def launch(self) -> None:
            record('launch')

    monkeypatch.setattr(cli, 'ChurchToolsAPI', FakeChurchToolsAPI)
    monkeypatch.setattr(cli, 'ChurchToolsEvent', FakeChurchToolsEvent)
    monkeypatch.setattr(cli, 'ImmichAPI', FakeImmichAPI)
    monkeypatch.setattr(cli, 'PowerPointServices', FakePowerPointServices)
    monkeypatch.setattr(cli, 'PowerPointAppointments', FakePowerPointAppointments)
    monkeypatch.setattr(cli, 'SongBeamer', FakeSongBeamer)
    return pipeline


def install_fake_interactive_screen(
    monkeypatch: pytest.MonkeyPatch, selection: DownloadSelection | None
) -> None:
    class FakeInteractiveScreen:
        def __init__(self, _config: Configuration) -> None: ...

        def run(self) -> DownloadSelection | None:
            return selection

    monkeypatch.setattr(cli, 'InteractiveScreen', FakeInteractiveScreen)


def install_fake_verification(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    recorded: dict[str, object] = {}

    class FakeChurchToolsAPI:
        def __init__(self, _config: Configuration) -> None: ...

    class FakeSongVerification:
        def __init__(self, _cta: object, _config: Configuration) -> None: ...

        def verify_songs(self, **kwargs: object) -> None:
            recorded.update(kwargs)

    monkeypatch.setattr(cli, 'ChurchToolsAPI', FakeChurchToolsAPI)
    monkeypatch.setattr(cli, 'ChurchToolsSongVerification', FakeSongVerification)
    return recorded


def install_fake_statistics(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    recorded: dict[str, object] = {}

    class FakeChurchToolsAPI:
        def __init__(self, _config: Configuration) -> None: ...

    class FakeSongStatistics:
        def __init__(self, _cta: object, _config: Configuration) -> None: ...

        def song_usage(self, **kwargs: object) -> None:
            recorded.update(kwargs)

    monkeypatch.setattr(cli, 'ChurchToolsAPI', FakeChurchToolsAPI)
    monkeypatch.setattr(cli, 'ChurchToolsSongStatistics', FakeSongStatistics)
    return recorded


def test_version_option_prints_version_without_starting_the_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No InteractiveScreen is installed: the eager --version callback has to
    # exit before the app callback would start the interactive screen.
    config = make_config()
    monkeypatch.delattr(cli, 'InteractiveScreen')
    result = invoke(['--version'], config)
    assert result.exit_code == 0
    assert result.output.strip() == str(config.version)


def test_self_version_prints_installed_version() -> None:
    config = make_config()
    result = invoke(['self', 'version'], config)
    assert result.exit_code == 0
    assert result.output.strip() == str(config.version)


def test_self_info_shows_versions_and_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    set_later_version(monkeypatch, '99.0.0')
    config = make_config()
    result = invoke(['self', 'info'], config)
    assert result.exit_code == 0
    assert f'Installed version:   {config.version}' in result.output
    assert 'Latest version:      99.0.0' in result.output
    assert str(config.config_toml) in result.output
    assert str(config.data_dir) in result.output


def test_self_info_omits_latest_version_when_up_to_date() -> None:
    result = invoke(['self', 'info'])
    assert result.exit_code == 0
    assert 'Latest version' not in result.output


def test_update_notice_is_shown_for_regular_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_later_version(monkeypatch, '99.0.0')
    install_fake_verification(monkeypatch)
    result = invoke(['songs', 'verify', 'all'])
    assert result.exit_code == 0
    assert 'Update to version 99.0.0 possible' in result.output
    assert 'ChurchSong self update' in result.output


def test_update_notice_is_suppressed_for_self_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_later_version(monkeypatch, '99.0.0')
    result = invoke(['self', 'version'])
    assert result.exit_code == 0
    assert 'self update' not in result.output


def test_self_update_without_uv_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('shutil.which', no_uv)
    result = invoke(['self', 'update'])
    assert result.exit_code == 1
    assert 'Cannot find "uv"' in result.output


def install_fake_uv(
    monkeypatch: pytest.MonkeyPatch, returncode: int
) -> list[list[str]]:
    executed: list[list[str]] = []

    def fake_run(
        cmd: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        executed.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode)

    def fake_execl(_file: str, *args: str) -> None:
        executed.append(list(args))

    monkeypatch.setattr('shutil.which', some_uv)
    monkeypatch.setattr('subprocess.run', fake_run)
    monkeypatch.setattr('os.execl', fake_execl)
    return executed


def test_self_update_updates_uv_and_then_execs_tool_upgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed = install_fake_uv(monkeypatch, returncode=0)
    result = invoke(['self', 'update'])
    assert result.exit_code == 0
    # "uv self update" runs as a subprocess, "uv tool upgrade" replaces us.
    assert executed[0] == ['/usr/bin/uv', 'self', 'update', '--no-config']
    assert executed[1][:3] == ['/usr/bin/uv', 'tool', 'upgrade']
    assert executed[1][-1] == 'ChurchSong'


def test_self_update_upgrades_even_if_uv_cannot_update_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A uv from a package manager refuses to self-update, but can still upgrade us.
    executed = install_fake_uv(monkeypatch, returncode=1)
    result = invoke(['self', 'update'])
    assert result.exit_code == 0
    assert executed[1][:3] == ['/usr/bin/uv', 'tool', 'upgrade']
    assert executed[1][-1] == 'ChurchSong'


def test_agenda_command_runs_the_full_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = install_fake_pipeline(monkeypatch)
    config = make_config(songbeamer=TEMPLATES)
    result = invoke(['agenda', '2026-08-16'], config)
    assert result.exit_code == 0
    assert pipeline.steps == [
        'api',
        'get_next_event',
        'event',
        'service_info',
        'services',
        'services.create',
        'services.save',
        'permissions:appointment slides generation',
        'appointments',
        'appointments.create',
        'appointments.save',
        'immich',
        'download',
        'song_sheets.upload',
        'songbeamer',
        'create_schedule',
        'launch',
    ]
    assert pipeline.requested_date is not None
    assert pipeline.requested_date.date() == datetime.date(2026, 8, 16)
    assert pipeline.agenda_required is True
    # The `agenda` command always downloads everything.
    assert pipeline.download_kwargs['download_files'] is True
    assert pipeline.download_kwargs['download_songs'] is True
    assert pipeline.download_kwargs['upload_songsheets'] is True
    assert pipeline.service_leads == SERVICE_LEADS
    assert pipeline.schedule_kwargs['agenda_items'] == AGENDA_ITEMS
    assert pipeline.schedule_kwargs['service_items'] == SERVICE_ITEMS
    assert pipeline.schedule_kwargs['event_date'] == make_event_short().start_date


def test_agenda_writes_the_schedule_although_the_song_sheet_upload_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = install_fake_pipeline(monkeypatch, failing_step='song_sheets.upload')
    config = make_config(songbeamer=TEMPLATES)
    result = invoke(['agenda', '2026-08-16'], config)
    assert result.exit_code == 0
    # A 502 of the upload costs neither the schedule nor the launch, although both
    # of them only come afterwards.
    assert 'create_schedule' in pipeline.steps
    assert 'launch' in pipeline.steps
    assert 'Skipped song sheet upload: 502 Server Error' in result.output


def test_agenda_runs_without_a_reachable_immich_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = install_fake_pipeline(monkeypatch, failing_step='immich')
    config = make_config(songbeamer=TEMPLATES)
    result = invoke(['agenda', '2026-08-16'], config)
    assert result.exit_code == 0
    # The download gets no Immich connector instead of never being reached at all.
    assert pipeline.download_kwargs['immich'] is None
    assert 'create_schedule' in pipeline.steps
    assert 'launch' in pipeline.steps
    assert 'Skipped Immich connector: 502 Server Error' in result.output


def test_agenda_writes_the_schedule_although_the_service_info_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = install_fake_pipeline(monkeypatch, failing_step='service_info')
    config = make_config(songbeamer=TEMPLATES)
    result = invoke(['agenda', '2026-08-16'], config)
    assert result.exit_code == 0
    # The songs are what the schedule is needed for, the service items are not.
    assert pipeline.schedule_kwargs['agenda_items'] == AGENDA_ITEMS
    assert pipeline.schedule_kwargs['service_items'] == []
    assert 'launch' in pipeline.steps
    # The service slides are created from what little there is.
    assert pipeline.service_leads == {}
    assert 'appointments.save' in pipeline.steps
    assert 'Skipped service team information: 502 Server Error' in result.output


def test_agenda_launches_although_the_slides_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = install_fake_pipeline(monkeypatch, failing_step='services.create')
    config = make_config(songbeamer=TEMPLATES)
    result = invoke(['agenda', '2026-08-16'], config)
    assert result.exit_code == 0
    assert 'services.save' not in pipeline.steps
    # One failing slide deck stops neither the other one nor the schedule.
    assert 'appointments.save' in pipeline.steps
    assert 'create_schedule' in pipeline.steps
    assert 'launch' in pipeline.steps
    assert 'Skipped service slides: 502 Server Error' in result.output


def test_agenda_reports_nothing_when_no_stage_was_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_pipeline(monkeypatch)
    config = make_config(songbeamer=TEMPLATES)
    result = invoke(['agenda', '2026-08-16'], config)
    assert result.exit_code == 0
    assert 'Skipped' not in result.output


def test_agenda_command_rejects_an_invalid_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = install_fake_pipeline(monkeypatch)
    result = invoke(['agenda', 'not-a-date'])
    assert result.exit_code == 2
    assert "Invalid value for 'date'" in result.output
    assert pipeline.steps == []


def test_agenda_skips_powerpoint_without_configured_templates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = install_fake_pipeline(monkeypatch)
    result = invoke(['agenda', '2026-08-16'])  # config without any template
    assert result.exit_code == 0
    assert 'services' not in pipeline.steps
    assert 'appointments' not in pipeline.steps
    # Without a template the permission is not even asked for.
    assert 'permissions:appointment slides generation' not in pipeline.steps
    assert 'launch' in pipeline.steps


def test_agenda_skips_appointment_slides_without_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = install_fake_pipeline(monkeypatch, appointment_permission=False)
    config = make_config(songbeamer=TEMPLATES)
    result = invoke(['agenda', '2026-08-16'], config)
    assert result.exit_code == 0
    assert 'permissions:appointment slides generation' in pipeline.steps
    assert 'appointments' not in pipeline.steps
    assert 'services.save' in pipeline.steps  # services slides are unaffected


def test_interactive_selection_drives_the_agenda_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = install_fake_pipeline(monkeypatch)
    install_fake_interactive_screen(
        monkeypatch,
        DownloadSelection(
            schedule=False, songs=True, files=False, slides=False, songsheets=True
        ),
    )
    config = make_config(songbeamer=TEMPLATES)
    result = invoke([], config)
    assert result.exit_code == 0
    assert pipeline.download_kwargs['download_files'] is False
    assert pipeline.download_kwargs['download_songs'] is True
    assert pipeline.download_kwargs['upload_songsheets'] is True
    # Neither slides nor schedule were selected.
    assert 'services' not in pipeline.steps
    assert 'appointments' not in pipeline.steps
    assert 'songbeamer' not in pipeline.steps


def test_interactive_screen_without_selection_does_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = install_fake_pipeline(monkeypatch)
    install_fake_interactive_screen(monkeypatch, None)
    result = invoke([])
    assert result.exit_code == 0
    assert pipeline.steps == []


def test_songs_verify_forwards_flattened_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = install_fake_verification(monkeypatch)
    result = invoke(
        [
            'songs',
            'verify',
            '2026-08-16',
            '--include_tags',
            'German,English',
            '--include_tags',
            'Worship',
            '--exclude_tags',
            'Archive',
            '--execute_checks',
            'CCLI,Tags',
            '--all_arrangements',
        ]
    )
    assert result.exit_code == 0
    date = recorded['date']
    assert isinstance(date, datetime.datetime)
    assert date.date() == datetime.date(2026, 8, 16)
    assert recorded['include_tags'] == ['German', 'English', 'Worship']
    assert recorded['exclude_tags'] == ['Archive']
    assert recorded['execute_checks'] == ['CCLI', 'Tags']
    assert recorded['all_arrangements'] is True


def test_songs_verify_all_passes_no_date(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = install_fake_verification(monkeypatch)
    result = invoke(['songs', 'verify', 'all'])
    assert result.exit_code == 0
    assert recorded['date'] is None
    assert recorded['include_tags'] == []
    assert recorded['all_arrangements'] is False


def test_songs_verify_rejects_an_unknown_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = install_fake_verification(monkeypatch)
    result = invoke(['songs', 'verify', 'all', '--execute_checks', 'NoSuchCheck'])
    assert result.exit_code == 2
    assert 'NoSuchCheck is not a valid check' in result.output
    assert recorded == {}


def test_songs_usage_forwards_year_range_and_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    recorded = install_fake_statistics(monkeypatch)
    output_file = tmp_path / 'usage.csv'
    result = invoke(
        ['songs', 'usage', '2024-2026', '--format', 'csv', '--output', str(output_file)]
    )
    assert result.exit_code == 0
    from_date = recorded['from_date']
    to_date = recorded['to_date']
    assert isinstance(from_date, datetime.datetime)
    assert isinstance(to_date, datetime.datetime)
    assert (from_date.year, from_date.month, from_date.day) == (2024, 1, 1)
    assert (to_date.year, to_date.month, to_date.day) == (2026, 12, 31)
    assert recorded['output_file'] == output_file
    assert recorded['output_format'] == ChurchToolsSongStatistics.FormatType.CSV


def test_songs_usage_accepts_an_open_start_year_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A leading '-2020' looks like an option, which is why the command has to
    # tolerate unknown options.
    recorded = install_fake_statistics(monkeypatch)
    result = invoke(['songs', 'usage', '-2020'])
    assert result.exit_code == 0
    from_date = recorded['from_date']
    to_date = recorded['to_date']
    assert isinstance(from_date, datetime.datetime)
    assert isinstance(to_date, datetime.datetime)
    assert from_date.year == 2000
    assert to_date.year == 2020
    assert recorded['output_file'] is None
    assert recorded['output_format'] == ChurchToolsSongStatistics.FormatType.RICH


def test_main_passes_the_configuration_as_context_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_config()
    seen: dict[str, object] = {}
    monkeypatch.setattr(cli, 'Configuration', lambda: config)

    def fake_app(**kwargs: object) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(cli, 'app', fake_app)
    cli.main()
    assert seen['obj'] is config


def test_main_logs_unexpected_exceptions_before_reraising(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(**_kwargs: object) -> None:
        msg = 'kaboom'
        raise RuntimeError(msg)

    monkeypatch.setattr(cli, 'Configuration', make_config)
    monkeypatch.setattr(cli, 'app', boom)
    with (
        caplog.at_level(logging.CRITICAL),
        pytest.raises(RuntimeError, match='kaboom'),
    ):
        cli.main()
    assert 'kaboom' in caplog.text
    assert 'Traceback' in caplog.text
