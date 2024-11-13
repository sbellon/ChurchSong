#!/usr/bin/env python

from __future__ import annotations

import argparse
import datetime
import pathlib
import sys
import tomllib

from churchtools import ChurchTools
from configuration import Configuration
from powerpoint import PowerPoint
from songbeamer import SongBeamer


def get_app_version() -> str:
    try:
        with pathlib.Path('pyproject.toml').open('rb') as f:
            return tomllib.load(f)['project']['version']
    except FileNotFoundError:
        pass
    return 'unknown'


def main() -> None:
    try:
        config = Configuration(pathlib.Path(__file__).with_suffix('.toml'))
        config.validate()

        config.log.debug('Parsing command line with args: %s', sys.argv)
        parser = argparse.ArgumentParser(
            prog='ChurchSong',
            description='Download ChurchTools event agenda and import into SongBeamer.',
        )
        subparsers = parser.add_subparsers(
            dest='command',
            help='possible commands, use --help to get detailed help',
        )
        parser_agenda = subparsers.add_parser('agenda', help='create SongBeamer agenda')
        parser_agenda.add_argument(
            'from_date',
            metavar='FROM_DATE',
            type=datetime.date.fromisoformat,
            nargs='?',
            help='search in ChurchTools for next event >= FROM_DATE (YYYY-MM-DD)',
        )
        parser_songs = subparsers.add_parser(
            'songs', help='operate on the ChurchTools songs'
        )
        subparser_songs = parser_songs.add_subparsers(
            dest='subcommand',
            help='commands to execute on the ChurchTools song database',
            required=True,
        )
        parser_songs_verify = subparser_songs.add_parser(
            'verify',
            help='check all songs for inconsistent and incomplete data and then exit',
        )
        parser_songs_verify.add_argument(
            '--exclude_tags',
            metavar='TAGS',
            action='extend',
            nargs='+',
            help='list of song tags that should be excluded from verification',
        )
        parser_songs_verify.add_argument(
            '--include_tags',
            metavar='TAGS',
            action='extend',
            nargs='+',
            help='list of song tags that should be included in verification',
        )
        parser.add_argument(
            '-v', '--version', action='version', version=get_app_version()
        )
        args = parser.parse_args()

        ct = ChurchTools(config)
        match args.command:
            case 'songs':
                match args.subcommand:
                    case 'verify':
                        config.log.info('Starting song verification')
                        try:
                            ct.verify_songs(args.include_tags, args.exclude_tags)
                        except KeyboardInterrupt:
                            sys.stdout.write('Aborted.\n')
                    case _:
                        parser_songs.print_help()

            case 'agenda' | None:
                if args.command is None:
                    args.from_date = None

                config.log.info('Starting ChurchSong with FROM_DATE=%s', args.from_date)
                service_leads = ct.get_service_leads(args.from_date)

                pp = PowerPoint(config)
                pp.create(service_leads)
                pp.save()

                ct.download_and_extract_agenda_zip(args.from_date)

                sb = SongBeamer(config)
                sb.modify_and_save_agenda(service_leads)
                sb.launch()

            case _:
                parser.print_help()

    except Exception as e:
        config.log.fatal(e, exc_info=True)
        raise


if __name__ == '__main__':
    main()
