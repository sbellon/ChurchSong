#!/usr/bin/env python

from __future__ import annotations

import argparse
import datetime
import pathlib
import sys

from churchtools import ChurchTools
from configuration import Configuration
from powerpoint import PowerPoint
from songbeamer import SongBeamer


def main() -> None:
    try:
        config = Configuration(pathlib.Path(__file__).with_suffix('.ini'))

        config.log.debug('Parsing command line with args: %s', sys.argv)
        parser = argparse.ArgumentParser(
            prog='ChurchSong',
            description='Download ChurchTools event agenda and import into SongBeamer.',
        )
        parser.add_argument(
            'from_date',
            metavar='FROM_DATE',
            type=datetime.date.fromisoformat,
            nargs='?',
            help='search in ChurchTools for next event starting at FROM_DATE (YYYY-MM-DD)',
        )
        args = parser.parse_args()

        config.log.info('Starting ChurchSong with FROM_DATE=%s', args.from_date)
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
        config.log.fatal(e, exc_info=True)
        raise


if __name__ == '__main__':
    main()
