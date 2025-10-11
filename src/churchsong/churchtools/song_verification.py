# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import ast
import inspect
import typing
from collections import OrderedDict, defaultdict

import rich
import rich.box
import rich.table
import typer

from churchsong.utils.progress import Progress

if typing.TYPE_CHECKING:
    import datetime

    from churchsong.churchtools import Arrangement, ChurchToolsAPI, Song, Tag
    from churchsong.configuration import Configuration


class SongChecks:
    type CheckFunc = typing.Callable[[Song, list[Arrangement]], list[str]]

    _song_checks: typing.ClassVar[typing.OrderedDict[str, CheckFunc]] = OrderedDict()

    @classmethod
    def register(cls, key: str) -> typing.Callable[[CheckFunc], CheckFunc]:
        def decorator(func: SongChecks.CheckFunc) -> SongChecks.CheckFunc:
            if key in cls._song_checks:
                msg = f'Song check {key} is already registered'
                raise RuntimeError(msg)
            cls._song_checks[key] = func
            return func

        return decorator

    @classmethod
    def get(cls, key: str) -> CheckFunc | None:
        return cls._song_checks.get(key)

    @classmethod
    def available_checks(cls) -> typing.OrderedDict[str, CheckFunc]:
        return cls._song_checks

    @staticmethod
    def miss_if(b: bool) -> str:
        return 'miss' if b else ''

    @staticmethod
    def contains(tag: str, tags: list[Tag]) -> bool:
        return any(t.name == tag for t in tags)


@SongChecks.register('CCLI')
def check_ccli(song: Song, arrangements: list[Arrangement]) -> list[str]:
    return [SongChecks.miss_if(not song.author or not song.ccli) for _ in arrangements]


@SongChecks.register('Tags')
def check_tags(song: Song, arrangements: list[Arrangement]) -> list[str]:
    return [
        ', '.join(
            filter(
                None,  # remove all falsy elements to not join them
                [  # now the list of individual tag checks ...
                    (
                        f'miss "{tag}"'
                        if arr.source
                        and arr.source.shorty
                        and arr.source_reference
                        and not SongChecks.contains(
                            (tag := f'{arr.source.shorty} {arr.source_reference}'),
                            song.tags,
                        )
                        else ''
                    ),
                    (
                        'miss "EN/DE"'
                        if any(
                            line.startswith(
                                ('#LangCount=2', '#LangCount=3', '#LangCount=4')
                            )
                            for line in arr.sng_file_content
                        )
                        and not SongChecks.contains('EN/DE', song.tags)
                        else ''
                    ),
                    # ... add further tag checks here ...
                ],
            )
        )
        for arr in arrangements
    ] or [SongChecks.miss_if(not song.tags)]


@SongChecks.register('Src.')
def check_source(_song: Song, arrangements: list[Arrangement]) -> list[str]:
    return [
        SongChecks.miss_if(not arr.source or not arr.source_reference)
        for arr in arrangements
    ]


@SongChecks.register('Dur.')
def check_duration(_song: Song, arrangements: list[Arrangement]) -> list[str]:
    return [SongChecks.miss_if(not arr.duration) for arr in arrangements]


@SongChecks.register('.sng')
def check_sng_file(_song: Song, arrangements: list[Arrangement]) -> list[str]:
    return [
        SongChecks.miss_if(
            arr.is_default and not any(file.name.endswith('.sng') for file in arr.files)
        )
        for arr in arrangements
    ]


@SongChecks.register('BGImg')
def check_bgimage(_song: Song, arrangements: list[Arrangement]) -> list[str]:
    return [
        SongChecks.miss_if(
            not any(
                line.startswith('#BackgroundImage=') for line in arr.sng_file_content
            )
            if arr.sng_file_content
            else False
        )
        for arr in arrangements
    ]


@SongChecks.register('#Lang')
def check_languages(song: Song, arrangements: list[Arrangement]) -> list[str]:
    return [
        ', '.join(
            filter(
                None,  # remove all falsy elements to not join them
                [  # now the list of individual tag checks ...
                    (
                        'miss #LangCount'
                        if SongChecks.contains('EN/DE', song.tags)
                        and arr.sng_file_content
                        and not any(
                            line.startswith(
                                ('#LangCount=2', '#LangCount=3', '#LangCount=4')
                            )
                            for line in arr.sng_file_content
                        )
                        else ''
                    ),
                    (
                        'miss #TitleLang'
                        if SongChecks.contains('EN/DE', song.tags)
                        and arr.sng_file_content
                        and not any(
                            line.startswith(
                                ('#TitleLang2', '#TitleLang3', '#TitleLang4')
                            )
                            for line in arr.sng_file_content
                        )
                        else ''
                    ),
                    # ... add further tag checks here ...
                ],
            )
        )
        for arr in arrangements
    ]


class ChurchToolsSongVerification:
    def __init__(self, cta: ChurchToolsAPI, config: Configuration) -> None:
        self.cta = cta
        self._log = config.log

    @staticmethod
    def available_checks() -> typing.OrderedDict[str, SongChecks.CheckFunc]:
        return SongChecks.available_checks()

    @staticmethod
    def validate_checks(value: str) -> str:
        for val in value.split(','):
            if val and val not in SongChecks.available_checks():
                msg = f'{val} is not a valid check'
                raise typer.BadParameter(msg)
        return value

    class MemberAccessChecker(ast.NodeVisitor):
        def __init__(self, member_name: str) -> None:
            self._member_name = member_name
            self._accessed = False

        def visit_Attribute(self, node: ast.Attribute) -> None:
            if node.attr == self._member_name:
                self._accessed = True
                self.generic_visit(node)

        def accessed(self) -> bool:
            return self._accessed

    @staticmethod
    def _is_sng_file_content_required(func: SongChecks.CheckFunc) -> bool:
        checker = ChurchToolsSongVerification.MemberAccessChecker('sng_file_content')
        checker.visit(ast.parse(inspect.getsource(func).strip(), mode='exec'))
        return checker.accessed()

    def verify_songs(  # noqa: C901, PLR0912
        self,
        *,
        date: datetime.datetime | None,
        include_tags: list[str],
        exclude_tags: list[str],
        execute_checks: list[str],
        all_arrangements: bool,
    ) -> None:
        self._log.info('Verifying ChurchTools song database for DATE=%s', date)

        # Use activated checks from command line or all as default.
        active_song_checks = OrderedDict(
            (name, check)
            for name in (execute_checks or SongChecks.available_checks().keys())
            if (check := SongChecks.get(name))
        )
        if not active_song_checks:
            msg = 'No valid check to execute selected.'
            raise typer.BadParameter(msg)
        needs_sng_file_contents = any(
            self._is_sng_file_content_required(check)
            for check in active_song_checks.values()
        )

        # Prepare the check result table.
        table = rich.table.Table(box=rich.box.ROUNDED)
        table.add_column('Id', justify='right')
        for column_name in ['Song', 'Arrangement', *active_song_checks.keys()]:
            table.add_column(column_name, justify='left')

        # Check whether there are duplicates regarding the CCLI number.
        ccli2ids: defaultdict[str | None, set[int]] = defaultdict(set)

        # Iterate over songs (either from agenda of specified date, or all songs) and
        # execute selected checks.
        event = self.cta.get_next_event(date, agenda_required=True) if date else None
        number_songs, songs = self.cta.get_songs(event)
        with Progress(description='Verifying Songs', total=number_songs) as progress:
            for song in progress.iterate(songs):
                # Apply include and exclude tag switches.
                if (
                    include_tags
                    and not any(
                        SongChecks.contains(tag, song.tags) for tag in include_tags
                    )
                ) or (
                    exclude_tags
                    and any(SongChecks.contains(tag, song.tags) for tag in exclude_tags)
                ):
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
                            f'#{song.id}',
                            song.name if song.name else f'#{song.id}',
                            arr.name if arr.name else f'#{arr.id}',
                            *check_result,
                        )

        output_duplicates = ''
        for ccli_no, song_ids in sorted(ccli2ids.items()):
            if len(song_ids) > 1:
                ids = ', '.join(f'#{song_id}' for song_id in sorted(song_ids))
                output_duplicates += f'\n  CCLI {ccli_no}: {ids}'

        # Output nicely formatted result table.
        if not table.rows and not output_duplicates:
            rich.print('No problems found.')
        if table.rows:
            rich.print(table)
        if output_duplicates:
            rich.print('\nDuplicate songs:' + output_duplicates)
