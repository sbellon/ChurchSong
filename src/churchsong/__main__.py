# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

import datetime
import os
import pathlib  # noqa: TC003 (false positive, typer needs it)
import shutil
import subprocess
import sys
import typing

import rich.traceback
import typer

from churchsong.churchtools import ChurchToolsAPI
from churchsong.churchtools.events import ChurchToolsEvent
from churchsong.churchtools.song_statistics import ChurchToolsSongStatistics, FormatType
from churchsong.churchtools.song_verification import ChurchToolsSongVerification
from churchsong.configuration import Configuration
from churchsong.interactivescreen import DownloadSelection, InteractiveScreen
from churchsong.powerpoint import PowerPoint
from churchsong.songbeamer import SongBeamer
from churchsong.utils.date import DateRange, parse_datetime, parse_year_range

rich.traceback.install(show_locals=True)

app = typer.Typer(
    add_completion=False,  # disable tab completion
    context_settings={'help_option_names': ['-h', '--help']},
    invoke_without_command=True,  # even invoke app callback without arguments
)
cmd_songs = typer.Typer(no_args_is_help=True, help='Operate on the ChurchTools songs.')
cmd_self = typer.Typer(no_args_is_help=True, help='Operate on the application itself.')
app.add_typer(cmd_songs, name='songs')
app.add_typer(cmd_self, name='self')


def show_version(ctx: typer.Context, value: bool) -> None:
    if value:
        sys.stdout.write(f'{ctx.obj.version}\n')
        raise typer.Exit


@app.callback(help='Download ChurchTools event agenda and import into SongBeamer.')
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
    if ctx.invoked_subcommand is None:
        ctx.obj.log.info('Starting interactive screen')
        if selection := InteractiveScreen(ctx.obj).run():
            ctx.obj.log.info(selection)
            _handle_agenda(datetime.datetime.now(tz=datetime.UTC), ctx.obj, selection)
    elif (latest := ctx.obj.latest_version) and latest != ctx.obj.version:
        sys.stdout.write(
            f'Note: Update to version {latest} possible via '
            f'"{ctx.obj.package_name} self update"\n'
        )


@app.command(help='Create SongBeamer agenda.')
def agenda(
    ctx: typer.Context,
    date: typing.Annotated[
        datetime.datetime,
        typer.Argument(
            parser=parse_datetime,
            default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat(),
            show_default=f'{datetime.datetime.now(datetime.UTC):%Y-%m-%d}',
            help='Search in ChurchTools for next event >= DATE (YYYY-MM-DD).',
        ),
    ],
) -> None:
    ctx.obj.log.info('Starting %s agenda with DATE=%s', ctx.obj.package_name, date)
    selection = DownloadSelection(schedule=True, songs=True, files=True, slides=True)
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
            default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat(),
            show_default=f'{datetime.datetime.now(datetime.UTC):%Y-%m-%d}',
            help='Verify only songs of next event >= DATE (YYYY-MM-DD), or "all".',
        ),
    ],
    *,
    exclude_tags: typing.Annotated[
        list[str],
        typer.Option(
            '--exclude_tags',
            metavar='TAG,TAG,...',
            parser=lambda s: s.split(','),
            default_factory=list,
            show_default='NONE',
            help='Song tags that should be excluded from verification.',
        ),
    ],
    include_tags: typing.Annotated[
        list[str],
        typer.Option(
            '--include_tags',
            metavar='TAG,TAG,...',
            parser=lambda s: s.split(','),
            default_factory=list,
            show_default='ALL',
            help='Song tags that should be included in verification.',
        ),
    ],
    execute_checks: typing.Annotated[
        list[str],
        typer.Option(
            '--execute_checks',
            metavar='TAG,TAG,...',
            parser=lambda s: s.split(','),
            default_factory=list,
            show_default='ALL',
            help='Checks to execute (header names of result table).',
        ),
    ],
    all_arrangements: typing.Annotated[
        bool,
        typer.Option(
            '--all_arrangements',
            help='Check all arrangements of the songs instead of just the default.',
        ),
    ] = False,
) -> None:
    ctx.obj.log.info(
        'Starting %s song verification with FROM_DATE=%s',
        ctx.obj.package_name,
        date,
    )
    cta = ChurchToolsAPI(ctx.obj)
    ctsv = ChurchToolsSongVerification(cta, ctx.obj)
    ctsv.verify_songs(
        from_date=date,
        include_tags=[tag for group in include_tags for tag in group],  # flatten
        exclude_tags=[tag for group in exclude_tags for tag in group],  # flatten
        execute_checks=[tag for group in execute_checks for tag in group],  # flatten
        all_arrangements=all_arrangements,
    )


@cmd_songs.command(
    context_settings={'ignore_unknown_options': True},  # allow -YEAR
    help='Calculate song usage statistics.',
)
def usage(
    ctx: typer.Context,
    year_range: typing.Annotated[
        DateRange,
        typer.Argument(
            metavar='[YEAR|YEAR-YEAR]',
            parser=parse_year_range,
            default_factory=lambda: '',
            show_default=f'{datetime.datetime.now(datetime.UTC):%Y}',
            help='Calculate song usage statistics for given year or range (YYYY-YYYY).',
        ),
    ],
    *,
    output: typing.Annotated[
        pathlib.Path | None,
        typer.Option(
            show_default=False,
            help='Output song usage statistics into file instead of console '
            '(mandatory for "xlsx").',
        ),
    ] = None,
    out_format: typing.Annotated[
        FormatType,
        typer.Option(
            '--format',
            help='Define output format.',
        ),
    ] = FormatType.TEXT,
) -> None:
    ctx.obj.log.info(
        'Starting %s song usage statistics for %s-%s',
        ctx.obj.package_name,
        year_range.from_date.year,
        year_range.to_date.year,
    )
    cta = ChurchToolsAPI(ctx.obj)
    ctsv = ChurchToolsSongStatistics(cta, ctx.obj)
    ctsv.song_usage(
        from_date=year_range.from_date,
        to_date=year_range.to_date,
        output_file=output,
        output_format=out_format,
    )


@cmd_self.command(help='Show application version.')
def version(ctx: typer.Context) -> None:
    sys.stdout.write(f'{ctx.obj.version}\n')


@cmd_self.command(help='Show info about the application.')
def info(ctx: typer.Context) -> None:
    sys.stderr.write(f'Installed version:   {ctx.obj.version}\n')
    if latest := ctx.obj.latest_version != ctx.obj.version:
        sys.stderr.write(f'Latest version:      {latest}\n')
    sys.stderr.write(f'Configuration file:  {ctx.obj.config_toml}\n')
    sys.stderr.write(f'User data directory: {ctx.obj.data_dir}\n')


@cmd_self.command(help='Updates the application.')
def update(ctx: typer.Context) -> None:
    ctx.obj.log.info('Starting %s update', ctx.obj.package_name)
    uv = shutil.which('uv')
    if not uv:
        err_msg = 'Cannot find "uv", aborting self update'
        ctx.obj.log.fatal(err_msg)
        sys.stderr.write(f'{err_msg}\n')
        sys.exit(1)
    try:
        # "uv self update" does not touch ChurchSong, so we can use subprocess.run().
        cmd = [uv, 'self', 'update', '--no-config']
        ctx.obj.log.info('Executing: %s', subprocess.list2cmdline(cmd))
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        ctx.obj.log.fatal(f'"uv self update" failed: {e}')
        raise
    # However "uv tool upgrade ChurchSong" modifies files in use, so we have to
    # "exec" instead of starting a subprocess.
    cmd = [
        uv,
        'tool',
        'upgrade',
        '--no-config',
        '--no-progress',
        '--python-preference',
        'only-managed',
        ctx.obj.package_name,
    ]
    ctx.obj.log.info('Executing: %s', subprocess.list2cmdline(cmd))
    os.execl(uv, *cmd)  # noqa: S606


def _handle_agenda(
    date: datetime.datetime, config: Configuration, selection: DownloadSelection
) -> None:
    cta = ChurchToolsAPI(config)
    event = cta.get_next_event(date, agenda_required=True)
    cte = ChurchToolsEvent(cta, event, config)
    agenda_items = cte.download_agenda_items(
        download_files=selection.files, download_songs=selection.songs
    )
    service_items, service_leads = cte.get_service_info()

    if selection.slides:
        pp = PowerPoint(config)
        pp.create(service_leads)
        pp.save()

    if selection.schedule:
        sb = SongBeamer(config)
        sb.create_schedule(
            event_date=event.start_date,
            agenda_items=agenda_items,
            service_items=service_items,
        )
        sb.launch()


def main() -> None:
    sys.stderr.write('\r\033[2K\r')
    config = Configuration()
    try:
        app(obj=config)
    except Exception as e:
        config.log.fatal(e, exc_info=True)
        raise


if __name__ == '__main__':
    main()
