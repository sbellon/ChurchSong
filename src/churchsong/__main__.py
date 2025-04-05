from __future__ import annotations

import argparse
import dataclasses
import datetime
import functools
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

import rich.traceback

from churchsong.churchtools import ChurchToolsAPI
from churchsong.churchtools.events import ChurchToolsEvent
from churchsong.churchtools.song_statistics import ChurchToolsSongStatistics, FormatType
from churchsong.churchtools.song_verification import ChurchToolsSongVerification
from churchsong.configuration import Configuration
from churchsong.interactivescreen import DownloadSelection, InteractiveScreen
from churchsong.powerpoint import PowerPoint
from churchsong.songbeamer import SongBeamer

rich.traceback.install(show_locals=True)


def print_update_hint(config: Configuration) -> None:
    latest = config.latest_version
    if latest and latest != config.version:
        sys.stdout.write(
            f'Note: Update to version {latest} possible via '
            f'"{config.package_name} self update"\n'
        )


def parse_datetime(date_str: str) -> datetime.datetime | None:
    if date_str.lower() == 'all':
        return None
    date = datetime.datetime.fromisoformat(date_str)
    if date.tzinfo is None or date.tzinfo.utcoffset(date) is None:
        # convert offset-naive datetime object to offset-aware
        local_tz = datetime.timezone(datetime.timedelta(seconds=-time.timezone))
        date = date.replace(tzinfo=local_tz)
    return date


@dataclasses.dataclass
class DateRange:
    from_date: datetime.datetime
    to_date: datetime.datetime


def parse_year_range(year_str: str) -> DateRange:
    local_tz = datetime.timezone(datetime.timedelta(seconds=-time.timezone))
    if not year_str:
        from_year = to_year = datetime.datetime.now(tz=local_tz).year
    elif m := re.fullmatch(r'(?P<year>\d{4})', year_str):
        from_year = to_year = int(m.group('year'))
    elif m := re.fullmatch(r'(?P<from_year>\d{4})?-(?P<to_year>\d{4})?', year_str):
        current_year = datetime.datetime.now(tz=local_tz).year
        from_year = int(m.group('from_year')) if m.group('from_year') else 2000
        to_year = int(m.group('to_year')) if m.group('to_year') else current_year
    else:
        msg = f'Invalid format: {year_str}'
        raise ValueError(msg)
    return DateRange(
        from_date=datetime.datetime(
            year=from_year,
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            tzinfo=local_tz,
        ),
        to_date=datetime.datetime(
            year=to_year,
            month=12,
            day=31,
            hour=23,
            minute=59,
            second=59,
            tzinfo=local_tz,
        ),
    )


def cmd_self_version(_args: argparse.Namespace, config: Configuration) -> None:
    sys.stdout.write(f'{config.version}\n')


def cmd_self_info(_args: argparse.Namespace, config: Configuration) -> None:
    sys.stderr.write(f'Installed version:   {config.version}\n')
    if latest := config.latest_version:
        sys.stderr.write(f'Latest version:      {latest}\n')
    sys.stderr.write(f'Configuration file:  {config.config_toml}\n')
    sys.stderr.write(f'User data directory: {config.data_dir}\n')


def cmd_self_update(_args: argparse.Namespace, config: Configuration) -> None:
    config.log.info('Starting %s update', config.package_name)
    uv = shutil.which('uv')
    if not uv:
        err_msg = 'Cannot find "uv", aborting self update'
        config.log.fatal(err_msg)
        sys.stderr.write(f'{err_msg}\n')
        sys.exit(1)
    try:
        # "uv self update" does not touch ChurchSong, so we can use subprocess.run().
        cmd = [uv, 'self', 'update', '--no-config']
        config.log.info('Executing: %s', subprocess.list2cmdline(cmd))
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        config.log.fatal(f'"uv self update" failed: {e}')
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
        config.package_name,
    ]
    config.log.info('Executing: %s', subprocess.list2cmdline(cmd))
    os.execl(uv, *cmd)  # noqa: S606


def cmd_interactive(args: argparse.Namespace, config: Configuration) -> None:
    config.log.info('Starting interactive screen')
    selection = InteractiveScreen(config).run()
    if selection:
        config.log.info(selection)
        args.from_date = datetime.datetime.now(tz=datetime.UTC)
        _handle_agenda(args, config, selection)


def cmd_agenda(args: argparse.Namespace, config: Configuration) -> None:
    config.log.info(
        'Starting %s agenda with FROM_DATE=%s',
        config.package_name,
        args.from_date,
    )
    selection = DownloadSelection(schedule=True, songs=True, files=True, slides=True)
    _handle_agenda(args, config, selection)


def _handle_agenda(
    args: argparse.Namespace, config: Configuration, selection: DownloadSelection
) -> None:
    cta = ChurchToolsAPI(config)
    event = cta.get_next_event(args.from_date, agenda_required=True)
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


def cmd_songs_verify(args: argparse.Namespace, config: Configuration) -> None:
    config.log.info(
        'Starting %s song verification with FROM_DATE=%s',
        config.package_name,
        args.from_date,
    )
    cta = ChurchToolsAPI(config)
    ctsv = ChurchToolsSongVerification(cta, config)
    ctsv.verify_songs(
        from_date=args.from_date,
        include_tags=args.include_tags,
        exclude_tags=args.exclude_tags,
        execute_checks=args.execute_checks,
        all_arrangements=args.all_arrangements,
    )


def cmd_songs_usage(args: argparse.Namespace, config: Configuration) -> None:
    config.log.info(
        'Starting %s song usage statistics for %s-%s',
        config.package_name,
        args.year_range.from_date.year,
        args.year_range.to_date.year,
    )
    cta = ChurchToolsAPI(config)
    ctsv = ChurchToolsSongStatistics(cta, config)
    ctsv.song_usage(
        from_date=args.year_range.from_date,
        to_date=args.year_range.to_date,
        output_file=args.output,
        output_format=args.format,
    )


def main() -> None:
    sys.stderr.write('\r\033[2K\r')
    config = Configuration()
    print_update_hint(config)
    try:
        config.log.debug('Parsing command line with args: %s', sys.argv)
        parser = argparse.ArgumentParser(
            prog=config.package_name,
            description='Download ChurchTools event agenda and import into SongBeamer.',
            allow_abbrev=False,
        )
        parser.set_defaults(func=functools.partial(cmd_interactive, config=config))
        subparsers = parser.add_subparsers(
            dest='command',
            help='possible commands, use --help to get detailed help',
        )
        parser_agenda = subparsers.add_parser(
            'agenda',
            help='create SongBeamer agenda',
            allow_abbrev=False,
        )
        parser_agenda.add_argument(
            'from_date',
            metavar='FROM_DATE',
            type=parse_datetime,
            default=datetime.datetime.now(datetime.UTC),
            nargs='?',
            help='search in ChurchTools for next event >= FROM_DATE (YYYY-MM-DD)',
        )
        parser_agenda.set_defaults(func=functools.partial(cmd_agenda, config=config))
        parser_songs = subparsers.add_parser(
            'songs',
            help='operate on the ChurchTools songs',
            allow_abbrev=False,
        )
        subparser_songs = parser_songs.add_subparsers(
            dest='subcommand',
            help='commands to execute on the ChurchTools song database',
            required=True,
        )
        parser_songs_verify = subparser_songs.add_parser(
            'verify',
            help='check all songs for inconsistent and incomplete data and then exit',
            allow_abbrev=False,
        )
        parser_songs_verify.add_argument(
            '--exclude_tags',
            metavar='TAG',
            action='extend',
            nargs='+',
            help='list of song tags that should be excluded from verification',
        )
        parser_songs_verify.add_argument(
            '--include_tags',
            metavar='TAG',
            action='extend',
            nargs='+',
            help='list of song tags that should be included in verification',
        )
        parser_songs_verify.add_argument(
            '--execute_checks',
            metavar='CHECK_NAME',
            action='extend',
            nargs='+',
            help=(
                'list of checks that should be performed (header names of result table)'
            ),
        )
        parser_songs_verify.add_argument(
            '--all_arrangements',
            action='store_true',
            help='check all arrangements of the songs instead of just the default',
        )
        parser_songs_verify.add_argument(
            'from_date',
            metavar='FROM_DATE',
            type=parse_datetime,
            default=datetime.datetime.now(datetime.UTC),
            nargs='?',
            help='verify only songs of next event >= FROM_DATE (YYYY-MM-DD), or "all"',
        )
        parser_songs_verify.set_defaults(
            func=functools.partial(cmd_songs_verify, config=config)
        )
        parser_songs_usage = subparser_songs.add_parser(
            'usage',
            help='calculate song usage statistics',
            allow_abbrev=False,
        )
        parser_songs_usage.add_argument(
            '--format',
            metavar='FORMAT',
            type=str,
            choices=[e.value for e in FormatType],
            default=FormatType.TEXT.value,
            help=f'define output format (default is "{FormatType.TEXT}")',
        )
        parser_songs_usage.add_argument(
            '--output',
            metavar='FILENAME',
            type=pathlib.Path,
            help='output song usage statistics into file instead of console'
            ' (mandatory for "xlsx")',
        )
        parser_songs_usage.add_argument(
            'year_range',
            metavar='[YEAR|[YEAR]-[YEAR]]',
            type=parse_year_range,
            default=parse_year_range(''),
            nargs='?',
            help='calculate song usage statistics for given year range (YYYY-YYYY)',
        )
        parser_songs_usage.set_defaults(
            func=functools.partial(cmd_songs_usage, config=config)
        )
        parser_self = subparsers.add_parser(
            'self',
            help=f'operate on the {config.package_name} application itself',
            allow_abbrev=False,
        )
        subparser_self = parser_self.add_subparsers(
            dest='subcommand',
            help=f'commands to execute on the {config.package_name} application itself',
            required=True,
        )
        parser_self_update = subparser_self.add_parser(
            'info',
            help=f'info about the {config.package_name} application',
            allow_abbrev=False,
        )
        parser_self_update.set_defaults(
            func=functools.partial(cmd_self_info, config=config)
        )
        parser_self_update = subparser_self.add_parser(
            'update',
            help=f'updates the {config.package_name} application',
            allow_abbrev=False,
        )
        parser_self_update.set_defaults(
            func=functools.partial(cmd_self_update, config=config)
        )
        parser_self_version = subparser_self.add_parser(
            'version',
            help="show program's version number and exit",
            allow_abbrev=False,
        )
        parser_self_version.set_defaults(
            func=functools.partial(cmd_self_version, config=config)
        )
        parser.add_argument('-v', '--version', action='version', version=config.version)
        args = parser.parse_args()
        try:
            args.func(args)
        except KeyboardInterrupt:
            sys.stdout.write('Aborted.\n')
            sys.exit(1)

    except Exception as e:
        config.log.fatal(e, exc_info=True)
        raise


if __name__ == '__main__':
    main()
