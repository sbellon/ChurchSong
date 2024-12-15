from __future__ import annotations

import argparse
import datetime
import functools
import pathlib
import shutil
import subprocess
import sys
import tomllib

from churchsong.churchtools import ChurchToolsAPI
from churchsong.churchtools.events import ChurchToolsEvent
from churchsong.churchtools.song_verification import ChurchToolsSongVerification
from churchsong.configuration import Configuration
from churchsong.powerpoint import PowerPoint
from churchsong.songbeamer import SongBeamer


def get_app_version(app_root: pathlib.Path) -> str:
    try:
        with (app_root / 'pyproject.toml').open('rb') as f:
            return tomllib.load(f)['project']['version']
    except FileNotFoundError:
        pass
    return 'unknown'


def cmd_agenda(args: argparse.Namespace, config: Configuration) -> None:
    if args.command is None:
        args.from_date = None

    config.log.info('Starting ChurchSong with FROM_DATE=%s', args.from_date)
    cta = ChurchToolsAPI(config)
    event = cta.get_next_event(args.from_date, agenda_required=True)
    cte = ChurchToolsEvent(cta, event, config)
    service_leads = cte.get_service_leads()
    event_files = cte.download_and_extract_agenda_zip()

    pp = PowerPoint(config)
    pp.create(service_leads)
    pp.save()

    sb = SongBeamer(config)
    sb.modify_and_save_agenda(event.start_date, service_leads, event_files)
    sb.launch()


def cmd_songs_verify(args: argparse.Namespace, config: Configuration) -> None:
    config.log.info('Starting song verification')
    cta = ChurchToolsAPI(config)
    ctsv = ChurchToolsSongVerification(cta, config)
    ctsv.verify_songs(
        from_date=args.from_date,
        include_tags=args.include_tags,
        exclude_tags=args.exclude_tags,
        execute_checks=args.execute_checks,
    )


def cmd_self_update(_args: argparse.Namespace, config: Configuration) -> None:
    config.log.info('Starting ChurchSong update')
    uv = shutil.which(config.app_root / 'bin/uv')
    if not uv:
        uv = shutil.which('uv')
    if not uv:
        err_msg = 'Cannot find "uv", aborting self update'
        config.log.fatal(err_msg)
        sys.stderr.write(f'{err_msg}\n')
        sys.exit(1)
    git = shutil.which('git')
    if not git:
        err_msg = 'Cannot find "git", aborting self update'
        config.log.fatal(err_msg)
        sys.stderr.write(f'{err_msg}\n')
        sys.exit(1)
    try:
        subprocess.run([uv, 'self', 'update'], check=True)  # noqa: S603
    except subprocess.CalledProcessError as e:
        config.log.fatal(f'"uv self update" failed: {e}')
        raise
    try:
        subprocess.run([git, 'restore', '*'], check=True)  # noqa: S603
    except subprocess.CalledProcessError as e:
        config.log.fatal(f'"git restore *" failed: {e}')
        raise
    try:
        subprocess.run([git, 'pull'], check=True)  # noqa: S603
    except subprocess.CalledProcessError as e:
        config.log.fatal(f'"git pull" failed: {e}')
        raise


def main() -> None:
    sys.stderr.write('\r\033[2K\r')
    app_root = pathlib.Path(__file__).parent.parent.parent
    config = Configuration(app_root)
    try:
        config.log.debug('Parsing command line with args: %s', sys.argv)
        parser = argparse.ArgumentParser(
            prog='ChurchSong',
            description='Download ChurchTools event agenda and import into SongBeamer.',
            allow_abbrev=False,
        )
        parser.set_defaults(func=functools.partial(cmd_agenda, config=config))
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
            type=datetime.date.fromisoformat,
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
            'from_date',
            metavar='FROM_DATE',
            type=datetime.date.fromisoformat,
            nargs='?',
            help='verify only songs of next event >= FROM_DATE (YYYY-MM-DD)',
        )
        parser_songs_verify.set_defaults(
            func=functools.partial(cmd_songs_verify, config=config)
        )
        parser_self = subparsers.add_parser(
            'self',
            help='operate on the ChurchSong application itself',
            allow_abbrev=False,
        )
        subparser_self = parser_self.add_subparsers(
            dest='subcommand',
            help='commands to execute on the ChurchSong application itself',
            required=True,
        )
        parser_self_update = subparser_self.add_parser(
            'update',
            help='updates the ChurchSong application',
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
            func=lambda _: sys.stdout.write(f'{get_app_version(app_root)}\n')
        )
        parser.add_argument(
            '-v', '--version', action='version', version=get_app_version(app_root)
        )
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
