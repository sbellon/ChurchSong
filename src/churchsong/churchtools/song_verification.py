import ast
import datetime
import inspect
import sys
import typing
from collections import OrderedDict, defaultdict

import alive_progress  # pyright: ignore[reportMissingTypeStubs]
import prettytable

from churchsong.churchtools import Arrangement, ChurchToolsAPI, Song, Tag
from churchsong.configuration import Configuration


def miss_if(b: bool) -> str:  # noqa: FBT001
    return 'miss' if b else ''


def contains(tag: str, tags: list[Tag]) -> bool:
    return any(t.name == tag for t in tags)


SONG_CHECKS: typing.Final[
    typing.OrderedDict[str, typing.Callable[[Song, list[Arrangement]], list[str]]]
] = OrderedDict(
    [  # now the list of checks for each song ...
        (
            'CCLI',
            lambda song, arrangements: [
                miss_if(not song.author or not song.ccli) for _ in arrangements
            ],
        ),
        (
            'Tags',
            lambda song, arrangements: [
                ', '.join(
                    filter(
                        None,  # remove all falsy elements to not join them
                        [  # now the list of individual tag checks ...
                            (
                                f'miss "{tag}"'
                                if arr.source_name
                                and arr.source_reference
                                and not contains(
                                    (
                                        tag
                                        := f'{arr.source_name} {arr.source_reference}'
                                    ),
                                    song.tags,
                                )
                                else ''
                            ),
                            (
                                'miss "EN/DE"'
                                if any(
                                    line.startswith('#LangCount=2')
                                    for line in arr.sng_file_content
                                )
                                and not contains('EN/DE', song.tags)
                                else ''
                            ),
                            # ... add further tag checks here ...
                        ],
                    )
                )
                for arr in arrangements
            ]
            or [miss_if(not song.tags)],
        ),
        (
            'Src.',
            lambda _song, arrangements: [
                miss_if(not arr.source_name or not arr.source_reference)
                for arr in arrangements
            ],
        ),
        (
            'Dur.',
            lambda _song, arrangements: [
                miss_if(not arr.duration) for arr in arrangements
            ],
        ),
        (
            '.sng',
            lambda _song, arrangements: [
                miss_if(
                    arr.is_default
                    and not any(file.name.endswith('.sng') for file in arr.files)
                )
                for arr in arrangements
            ],
        ),
        (
            'BGImg',
            lambda _song, arrangements: [
                miss_if(
                    not any(
                        line.startswith('#BackgroundImage=')
                        for line in arr.sng_file_content
                    )
                    if arr.sng_file_content
                    else False
                )
                for arr in arrangements
            ],
        ),
        (
            '#Lang',
            lambda song, arrangements: [
                miss_if(
                    contains('EN/DE', song.tags)
                    and not any(
                        line.startswith(
                            ('#LangCount=2', '#LangCount=3', '#LangCount=4')
                        )
                        for line in arr.sng_file_content
                    )
                    if arr.sng_file_content
                    else False
                )
                for arr in arrangements
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
    def _is_sng_file_content_required(
        func: typing.Callable[[Song, list[Arrangement]], list[str]],
    ) -> bool:
        checker = ChurchToolsSongVerification.MemberAccessChecker('sng_file_content')
        checker.visit(ast.parse(inspect.getsource(func).strip(), mode='exec'))
        return checker.accessed()

    def verify_songs(  # noqa: C901, PLR0912
        self,
        *,
        from_date: datetime.datetime | None,
        include_tags: list[str],
        exclude_tags: list[str],
        execute_checks: list[str],
        all_arrangements: bool,
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

        # Check whether there are duplicates regarding the CCLI number.
        ccli2ids: defaultdict[str | None, set[int]] = defaultdict(set)

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
        ) as bar:  # pyright: ignore[reportUnknownVariableType]
            for song in songs:
                # Apply include and exclude tag switches.
                if (
                    include_tags
                    and not any(contains(tag, song.tags) for tag in include_tags)
                ) or (
                    exclude_tags
                    and any(contains(tag, song.tags) for tag in exclude_tags)
                ):
                    bar()
                    continue

                if song.ccli:
                    ccli2ids[song.ccli].add(song.id)

                arrangements = (
                    song.arrangements
                    if all_arrangements
                    else [arr for arr in song.arrangements if arr.is_default]
                )

                # Load .sng files - if existing - to have them available for checking.
                if needs_sng_file_contents:
                    for arr in arrangements:
                        # If multiple .sng files are present, ChurchTools seems to
                        # export the .sng file of the arrangement with the lowest #id?
                        sng_file = next(
                            (file for file in arr.files if file.name.endswith('.sng')),
                            None,
                        )
                        if sng_file:
                            arr.sng_file_content = (
                                self.cta.download_url(sng_file.file_url)
                                .text.lstrip('\ufeff')
                                .splitlines()
                            )

                # Execute the actual checks.
                check_results = zip(
                    *(
                        check(song, arrangements)
                        for check in active_song_checks.values()
                    ),
                    strict=True,
                )

                # Create the result table row(s) for later output.
                for arr, check_result in zip(arrangements, check_results, strict=True):
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

        output_duplicates = ''
        for ccli_no, song_ids in sorted(ccli2ids.items()):
            if len(song_ids) > 1:
                ids = ', '.join(f'#{song_id}' for song_id in sorted(song_ids))
                output_duplicates += f'\n  CCLI {ccli_no}: {ids}'
        if output_duplicates:
            output_duplicates = '\nDuplicate songs:' + output_duplicates

        # Output nicely formatted result table.
        table_text = table.get_string(  # pyright: ignore[reportUnknownMemberType]
            print_empty=False,
            sortby=None if event else 'Song',
        )
        sys.stdout.write(
            '{}\n'.format(table_text + output_duplicates or 'No problems found.')
        )
