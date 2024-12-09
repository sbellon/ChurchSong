import ast
import datetime
import inspect
import sys
import typing
from collections import OrderedDict

import alive_progress
import prettytable

from churchsong.churchtools import ChurchToolsAPI, Song
from churchsong.configuration import Configuration


def miss_if(b: bool) -> str:  # noqa: FBT001
    return 'miss' if b else ''


SONG_CHECKS: typing.Final[
    typing.OrderedDict[str, typing.Callable[[Song], list[str]]]
] = OrderedDict(
    [  # now the list of checks for each song ...
        (
            'CCLI',
            lambda song: [
                miss_if(not song.author or not song.ccli) for _ in song.arrangements
            ],
        ),
        (
            'Tags',
            lambda song: [
                ', '.join(
                    filter(
                        None,  # remove all falsy elements to not join them
                        [  # now the list of individual tag checks ...
                            (
                                f'miss "{a.source_name} {a.source_reference}"'
                                if a.source_name
                                and a.source_reference
                                and not song.tags
                                else miss_if(not song.tags)
                            ),
                            (
                                'miss "EN/DE"'
                                if any(
                                    line.startswith('#LangCount=2')
                                    for line in a.sng_file_content
                                )
                                and 'EN/DE' not in song.tags
                                else ''
                            ),
                            # ... add further checks here ...
                        ],
                    )
                )
                for a in song.arrangements
            ]
            or [miss_if(not song.tags)],
        ),
        (
            'Src.',
            lambda song: [
                miss_if(not a.source_name or not a.source_reference)
                for a in song.arrangements
            ],
        ),
        (
            'Dur.',
            lambda song: [miss_if(a.duration == 0) for a in song.arrangements],
        ),
        (
            '.sng',
            lambda song: [
                miss_if(not any(file.name.endswith('.sng') for file in a.files))
                for a in song.arrangements
            ],
        ),
        (
            'BGImg',
            lambda song: [
                miss_if(
                    not any(
                        line.startswith('#BackgroundImage=')
                        for line in a.sng_file_content
                    )
                    if a.sng_file_content
                    else False
                )
                for a in song.arrangements
            ],
        ),
        (
            '#Lang',
            lambda song: [
                miss_if(
                    'EN/DE' in song.tags
                    and not any(
                        line.startswith(
                            ('#LangCount=2', '#LangCount=3', '#LangCount=4')
                        )
                        for line in a.sng_file_content
                    )
                    if a.sng_file_content
                    else False
                )
                for a in song.arrangements
            ],
        ),
    ]
)


class ChurchToolsSongVerification:
    def __init__(self, cta: ChurchToolsAPI, config: Configuration) -> None:
        self.cta = cta
        self._log = config.log

    class MemberAccessChecker(ast.NodeVisitor):
        def __init__(self, member_name: str) -> None:
            self._member_name = member_name
            self._accessed = False

        def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
            if node.attr == self._member_name:
                self._accessed = True
                self.generic_visit(node)

        def accessed(self) -> bool:
            return self._accessed

    @staticmethod
    def _is_sng_file_content_required(func: typing.Callable[[Song], list[str]]) -> bool:
        checker = ChurchToolsSongVerification.MemberAccessChecker('sng_file_content')
        checker.visit(ast.parse(inspect.getsource(func).strip(), mode='exec'))
        return checker.accessed()

    def verify_songs(
        self,
        *,
        from_date: datetime.datetime | None = None,
        include_tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        execute_checks: list[str] | None = None,
    ) -> None:
        self._log.info('Verifying ChurchTools song database')

        # Use activated checks from command line or all as default.
        active_song_checks = OrderedDict(
            (name, SONG_CHECKS[name])
            for name in (execute_checks if execute_checks else SONG_CHECKS.keys())
            if name in SONG_CHECKS
        )
        if not active_song_checks:
            sys.stderr.write('Error: no valid check to execute selected\n')
            sys.exit(1)
        needs_sng_file_contents = any(
            self._is_sng_file_content_required(check)
            for check in active_song_checks.values()
        )

        # Prepare the check result table.
        table = prettytable.PrettyTable()
        table.field_names = ['Id', 'Song', 'Arrangement', *active_song_checks.keys()]
        table.align['Id'] = 'r'
        for field_id in table.field_names[1:]:
            table.align[field_id] = 'l'

        # Iterate over songs (either from agenda of specified date, or all songs) and
        # execute selected checks.
        event = (
            self.cta.get_next_event(from_date, agenda_required=True)
            if from_date
            else None
        )
        number_songs, songs = self.cta.get_songs(event)
        with alive_progress.alive_bar(
            number_songs, title='Verifying Songs', spinner=None, receipt=False
        ) as bar:
            for song in sorted(songs, key=lambda e: e.name):
                # Apply include and exclude tag switches.
                if (
                    include_tags and not any(tag in song.tags for tag in include_tags)
                ) or (exclude_tags and any(tag in song.tags for tag in exclude_tags)):
                    bar()
                    continue

                # Load .sng files - if existing - to have them available for checking.
                if needs_sng_file_contents:
                    for arr in song.arrangements:
                        # If multiple .sng files are present, ChurchTools seems to
                        # export the .sng file of the arrangement with the lowest #id?
                        sngfile = next(
                            (file for file in arr.files if file.name.endswith('.sng')),
                            None,
                        )
                        if sngfile:
                            arr.sng_file_content = self.cta.load_sng_file(
                                sngfile.file_url
                            ).splitlines()

                # Execute the actual checks.
                check_results = zip(
                    *(check(song) for check in active_song_checks.values()), strict=True
                )

                # Create the result table row(s) for later output.
                for arr, check_result in zip(
                    song.arrangements, check_results, strict=True
                ):
                    if any(res for res in check_result):
                        table.add_row(
                            [
                                f'#{song.id}',
                                song.name if song.name else f'#{song.id}',
                                arr.name if arr.name else f'#{arr.id}',
                                *check_result,
                            ]
                        )
                bar()

        # Output nicely formatted result table.
        sys.stdout.write(
            '{}\n'.format(table.get_string(print_empty=False) or 'No problems found.')
        )