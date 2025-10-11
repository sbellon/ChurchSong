# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import dataclasses
import datetime  # noqa: TC003 (used within Annotated)
import os
import pathlib  # noqa: TC003 (used within Annotated)
import shutil
import subprocess
import typing

import rich
import typer

from churchsong.churchtools import ChurchToolsAPI
from churchsong.churchtools.events import ChurchToolsEvent
from churchsong.churchtools.song_statistics import ChurchToolsSongStatistics
from churchsong.churchtools.song_verification import ChurchToolsSongVerification
from churchsong.configuration import Configuration
from churchsong.interactivescreen import DownloadSelection, InteractiveScreen
from churchsong.powerpoint.appointments import PowerPointAppointments
from churchsong.powerpoint.services import PowerPointServices
from churchsong.songbeamer import SongBeamer
from churchsong.utils import CliError, flattened_split
from churchsong.utils.date import DateRange, now, parse_datetime, parse_year_range

app = typer.Typer(
    add_completion=False,  # disable tab completion
    context_settings={'help_option_names': ['-h', '--help']},
    invoke_without_command=True,  # even invoke app callback without arguments
)
cmd_songs = typer.Typer(
    no_args_is_help=True, help='Operate on the ChurchTools songs database.'
)
cmd_self = typer.Typer(
    no_args_is_help=True,
    help=f'Operate on the {Configuration.package_name} application itself.',
)
app.add_typer(cmd_songs, name='songs')
app.add_typer(cmd_self, name='self')


def show_version(ctx: typer.Context, show: bool) -> None:
    if show:
        rich.print(f'{ctx.obj.version}')
        raise typer.Exit


@app.callback(
    help='Download event agenda from ChurchTools and create SongBeamer schedule.'
)
def callback(
    ctx: typer.Context,
    _version: bool = typer.Option(
        None,
        '--version',
        '-v',
        help='Show the version and exit.',
        callback=show_version,
        is_eager=True,
    ),
) -> None:
    match ctx.invoked_subcommand:
        case None:
            ctx.obj.log.info('Starting interactive screen')
            if selection := InteractiveScreen(ctx.obj).run():
                _handle_agenda(now(), ctx.obj, selection)
        case _ if ctx.invoked_subcommand != 'self':
            if later_version := ctx.obj.later_version_available:
                rich.get_console().print(
                    f'Note: Update to version {later_version} possible via '
                    f'"{Configuration.package_name} self update".',
                    style='yellow',
                )
        case _:
            pass


@app.command(help='Create SongBeamer agenda and start SongBeamer.')
def agenda(
    ctx: typer.Context,
    date: typing.Annotated[
        datetime.datetime,
        typer.Argument(
            parser=parse_datetime,
            default_factory=lambda: now().isoformat(),
            show_default=f'{now():%Y-%m-%d}',
            help='Search in ChurchTools for next event >= DATE (YYYY-MM-DD).',
        ),
    ],
) -> None:
    selection = DownloadSelection(
        schedule=True, songs=True, files=True, slides=True, songsheets=True
    )
    _handle_agenda(date, ctx.obj, selection)


@cmd_songs.command(
    help='Check all songs for inconsistent and incomplete data and then exit.'
)
def verify(  # noqa: PLR0913
    ctx: typer.Context,
    date: typing.Annotated[
        datetime.datetime,
        typer.Argument(
            parser=parse_datetime,
            default_factory=lambda: now().isoformat(),
            show_default=f'{now():%Y-%m-%d}',
            help='Verify only songs of next event >= DATE (YYYY-MM-DD), or "all".',
        ),
    ],
    *,
    exclude_tags: typing.Annotated[
        list[str],
        typer.Option(
            '--exclude_tags',
            metavar='TAG,TAG,...',
            default_factory=list,
            show_default='no tags',
            help='Song tags that should be excluded from verification.',
        ),
    ],
    include_tags: typing.Annotated[
        list[str],
        typer.Option(
            '--include_tags',
            metavar='TAG,TAG,...',
            default_factory=list,
            show_default='all tags',
            help='Song tags that should be included in verification.',
        ),
    ],
    execute_checks: typing.Annotated[
        list[str],
        typer.Option(
            '--execute_checks',
            metavar='CHECK,CHECK,...',
            default_factory=list,
            show_default=','.join(ChurchToolsSongVerification.available_checks()),
            parser=ChurchToolsSongVerification.validate_checks,
            help='Checks to execute (header names of result table).',
        ),
    ],
    all_arrangements: typing.Annotated[
        bool,
        typer.Option(
            '--all_arrangements',
            help='Check all arrangements of the songs '
            'instead of just the default arrangement.',
        ),
    ] = False,
) -> None:
    ctx.obj.log.info(
        'Starting %s song verification with DATE=%s', Configuration.package_name, date
    )
    cta = ChurchToolsAPI(ctx.obj)
    ctsv = ChurchToolsSongVerification(cta, ctx.obj)
    ctsv.verify_songs(
        date=date,
        include_tags=flattened_split(include_tags),
        exclude_tags=flattened_split(exclude_tags),
        execute_checks=flattened_split(execute_checks),
        all_arrangements=all_arrangements,
    )


@cmd_songs.command(
    context_settings={'ignore_unknown_options': True},  # allow -YEAR
    help='Calculate song usage statistics and output in various formats.',
)
def usage(
    ctx: typer.Context,
    year_range: typing.Annotated[
        DateRange,
        typer.Argument(
            metavar='[YEAR|YEAR-YEAR]',
            parser=parse_year_range,
            default_factory=lambda: '',
            show_default=f'{now():%Y}',
            help='Calculate song usage statistics for given year or range (YYYY-YYYY).',
        ),
    ],
    *,
    output_file: typing.Annotated[
        pathlib.Path | None,
        typer.Option(
            '--output',
            dir_okay=False,
            show_default=False,
            help='Output song usage statistics into file instead of console '
            '(mandatory for "xlsx").',
        ),
    ] = None,
    output_format: typing.Annotated[
        ChurchToolsSongStatistics.FormatType,
        typer.Option(
            '--format',
            case_sensitive=False,
            help='Define output format.',
        ),
    ] = ChurchToolsSongStatistics.FormatType.RICH,
) -> None:
    ctx.obj.log.info(
        'Starting %s song usage statistics for %s-%s',
        Configuration.package_name,
        year_range.from_date.year,
        year_range.to_date.year,
    )
    cta = ChurchToolsAPI(ctx.obj)
    ctss = ChurchToolsSongStatistics(cta, ctx.obj)
    ctss.song_usage(
        from_date=year_range.from_date,
        to_date=year_range.to_date,
        output_file=output_file,
        output_format=output_format,
    )


@cmd_self.command(help=f'Show the {Configuration.package_name} application version.')
def version(ctx: typer.Context) -> None:
    show_version(ctx, show=True)


@cmd_self.command(help=f'Show info about the {Configuration.package_name} application.')
def info(ctx: typer.Context) -> None:
    rich.print(f'Installed version:   {ctx.obj.version}')
    if later_version := ctx.obj.later_version_available:
        rich.print(f'Latest version:      {later_version}')
    rich.print(f'Configuration file:  {ctx.obj.config_toml}')
    rich.print(f'User data directory: {ctx.obj.data_dir}')


@cmd_self.command(help=f'Update the {Configuration.package_name} application.')
def update(ctx: typer.Context) -> None:
    ctx.obj.log.info('Starting %s update', Configuration.package_name)
    uv = shutil.which('uv')
    if not uv:
        msg = 'Cannot find "uv", aborting self update'
        ctx.obj.log.fatal(msg)
        raise CliError(msg)
    try:
        # "uv self update" does not touch any files of our application,
        # so we can use subprocess.run().
        cmd = [uv, 'self', 'update', '--no-config']
        ctx.obj.log.info('Executing: %s', subprocess.list2cmdline(cmd))
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        msg = f'"uv self update" failed: {e}'
        ctx.obj.log.fatal(msg)
        raise CliError(msg) from None
    # However "uv tool upgrade" modifies files of our application that are in use,
    # so we have to "exec" instead of starting a subprocess.
    cmd = [
        uv,
        'tool',
        'upgrade',
        '--no-config',
        '--no-progress',
        '--python-preference',
        'only-managed',
        Configuration.package_name,
    ]
    ctx.obj.log.info('Executing: %s', subprocess.list2cmdline(cmd))
    os.execl(uv, *cmd)  # noqa: S606


def _handle_agenda(
    date: datetime.datetime, config: Configuration, selection: DownloadSelection
) -> None:
    sel = '' if all(dataclasses.asdict(selection).values()) else f' and {selection}'
    config.log.info(
        'Starting %s agenda with DATE=%s%s', Configuration.package_name, date, sel
    )
    cta = ChurchToolsAPI(config)
    event = cta.get_next_event(date, agenda_required=True)
    cte = ChurchToolsEvent(cta, event, config)
    agenda_items = cte.download_agenda_items(
        download_files=selection.files,
        download_songs=selection.songs,
        upload_songsheets=selection.songsheets,
    )
    service_items, service_leads = cte.get_service_info()

    if selection.slides:
        if config.songbeamer.powerpoint.services.template_pptx:
            pps = PowerPointServices(config)
            pps.create(service_leads)
            pps.save()
        if config.songbeamer.powerpoint.appointments.template_pptx:
            with cta.permissions(
                'creation of appointment slides',
                ['churchcal:view', 'churchcal:view category'],
            ):
                ppa = PowerPointAppointments(config)
                ppa.create(cta.get_appointments(event), event.start_date)
                ppa.save()

    if selection.schedule:
        sb = SongBeamer(config)
        sb.create_schedule(
            event_date=event.start_date,
            agenda_items=agenda_items,
            service_items=service_items,
        )
        sb.launch()


def main() -> None:
    config = Configuration()
    try:
        app(obj=config)
    except Exception as e:
        config.log.fatal(e, exc_info=True)
        raise


if __name__ == '__main__':
    main()
