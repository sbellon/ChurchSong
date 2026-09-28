# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`ChurchSong` is a CLI tool that pulls the next event agenda from a [ChurchTools](https://church.tools)
instance and turns it into everything needed to run the service: a SongBeamer `Schedule.col`,
PowerPoint slides for service staff and upcoming appointments, PDF song sheets uploaded back to
ChurchTools, and optional media upload to an [Immich](https://immich.app/) instance. It also
verifies the ChurchTools song database and produces song usage statistics.

Runtime target is **Windows** (SongBeamer launching is win32-only); development happens on Linux
too. Requires **Python >= 3.14** — the code uses recent syntax (`type` aliases, PEP 695 generics,
PEP 758 unparenthesized `except A, B:`), so older interpreters will not even parse it.

## Commands

Dependency and env management is [uv](https://docs.astral.sh/uv/); there is no `pip`/`venv` path.

```sh
uv sync --all-extras --dev      # set up / refresh .venv
uv run ChurchSong --help        # run from the working tree
uv run ChurchSong agenda 2026-08-16
uv run ChurchSong songs verify all --execute_checks CCLI,Tags
uv run ChurchSong songs usage 2024-2026 --format rich
```

Quality gates (exactly what CI runs, in `.github/workflows/code-quality.yml`):

```sh
uv lock --check                 # lockfile must match pyproject.toml
uvx ruff check .                # lint
uvx ruff format --check .       # format (drop --check to apply)
uvx pyright --project .         # type check (strict) — needs `uv sync` first
uv run pytest                   # test suite in tests/ — needs `uv sync` first
uvx typos --force-exclude       # spell check (crate-ci/typos)
uv build                        # sdist + wheel
```

The same checks (minus lockfile/build) run as a git pre-commit hook via the `pre-commit`
framework (`.pre-commit-config.yaml`, local hooks calling `uvx`/`uv run`, cross-platform).
One-time setup after cloning: `uv sync && uv run pre-commit install`. Bypass with
`git commit --no-verify` when committing intentionally red work-in-progress.

**Tests** live in `tests/` (pytest). The ChurchTools/Immich clients are tested with `responses`
mocking `requests` at the adapter level; `responses.RequestsMock` also fails a test on any
unexpected *or unfired* request, which is how "a missing permission skips the upload" is asserted.
Build configurations through `tests/conftest.py`'s `make_config()` — a `FakeConfiguration` that
validates a dict through the real config model tree but bypasses `Configuration.__init__`'s
file/logging/gettext side effects — rather than constructing `Configuration`. CLI commands run
through Typer's `CliRunner` with `obj=make_config()` (`test_cli.py`), the TUI through Textual's
`app.run_test()` pilot (`test_interactivescreen.py`). Full end-to-end behaviour (SongBeamer
launch, real API quirks) still needs a real run against a configured ChurchTools instance.

Regenerate translation catalogs after touching any `_('...')` string:

```sh
./dev-scripts/translate.py      # pybabel extract + update src/churchsong/locales/*.po
```

Releases use `bump-my-version` (config in `pyproject.toml`): it rewrites the version in
`pyproject.toml`, turns the `## Unreleased` heading in `CHANGELOG.md` into the new version, runs
`uv sync`, and commits. So **add user-visible changes under `## Unreleased` in `CHANGELOG.md`** as
part of the change itself.

## Architecture

**Configuration is the root object.** `Configuration` (`configuration.py`) is a frozen Pydantic
model tree loaded from a TOML file at the platformdirs user-config path (`ChurchSong self info`
prints it). It is constructed once in `main()` and threaded everywhere as Typer's `ctx.obj`; every
component takes it in `__init__` and pulls out only what it needs. Notable behaviour baked into it:

- TOML section names are `PascalCase` aliases (`[SongBeamer.PowerPoint.Services]`) mapped onto
  snake_case fields via `pydantic.Field(alias=...)`.
- `${ENVVAR}` is expanded recursively across all string values before validation
  (`recursive_expand_envvars`); unknown vars are left literal.
- `DataDirPath` / `OptionalDataDirPath` resolve relative paths against the platform data dir.
- It also installs the gettext translation and owns logging: stderr until the config is read,
  then a rotating file handler, both on the `churchsong` parent logger, which `__init__` clears
  first so a second `Configuration` does not log everything twice. Nothing takes a logger from
  the config — every module has its own `logger = logging.getLogger(__name__)` and `%(name)s`
  names it in the log file. `utils/http.BaseAPI` is the exception: shared infrastructure, so it
  takes the logger to use from its subclass.

**Command surface** lives entirely in `__main__.py` (Typer app + `songs` and `self` sub-apps). With
no subcommand it launches the Textual TUI in `interactivescreen.py`, which returns a
`DownloadSelection` into the same `_handle_agenda()` path as the `agenda` command — the one place
that orchestrates ChurchTools → PowerPoint → SongBeamer. Everything optional in it runs inside
`_OptionalSteps.guard()`, which logs the failure, records it and lets the pipeline continue, so
that no error in them can cost the run its `Schedule.col`; `report()` then prints one console line
per skipped step before the schedule is written. A new optional step belongs in a `guard()` rather
than in the bare sequence, and anything it assigns to needs a value *before* the `with`, as the
guard swallows the exception and pyright does not flag the unbound case. Date and year-range
arguments are parsed by the `parser=` callables in `utils/date.py`. The blocking PyPI check
(`Configuration.later_version_available`) is asked for in exactly two places — `self info`, where
the answer is the output, and the TUI's thread worker — so no command has it on its critical path.
`self update` `exec`s `uv tool upgrade` in place, because it rewrites files that are in use.

**HTTP clients** subclass `utils/http.BaseAPI`, which owns one `requests.Session` per instance
(connection reuse, closed via `atexit`) and provides `_get/_put/_post/_delete` wrappers that prefix
`self._base_url`, attach `self._headers`, log, and `raise_for_status()`. Auth headers are passed
per-request and deliberately *not* put on the session, so downloads from a foreign host can drop
them (`is_same_host()`). `ChurchToolsAPI` and `ImmichAPI` both subclass it.

`BaseAPI` stays service-agnostic: it *offers* `persist_cookies=False` but takes no position on it —
each client decides at its `super().__init__()` call and states the reason in a comment there
(`ChurchToolsAPI` opts out over a CSRF interaction, `ImmichAPI` keeps the default). Add
service-specific HTTP behaviour that way rather than by putting it into `BaseAPI`.

**ChurchTools API models** (`churchtools/__init__.py`) are Pydantic models mirroring the JSON, with
camelCase aliases and `DeprecationAwareModel` as base — it inspects the `@deprecated` key ChurchTools
returns and emits `DeprecationWarning` when a model still uses a superseded field. Several models
carry `model_validator(mode='before')` shims for ChurchTools quirks (null titles, `normal` → `text`
item type, all-day appointment dates without timezone). When the upstream API changes, that is where
compatibility patches go — dated comments mark the existing ones.

**Permissions are two-tier**, in both clients: each constructor fetches the token's permissions
once and hard-asserts what basic operation needs (`CliError`), while every optional feature calls
`has_permissions([...], 'reason')`, which logs a warning and lets the caller skip that feature. Add
new optional features that way rather than by asserting. The whole trio lives in `BaseAPI`, together
with the fetch error ladder (`_fetch_required()`, which keeps the "Did you configure ...?"
hints `_parse()` deliberately omits). What a client supplies is its endpoint, its permission model,
and — as `BaseAPI._permissions` is typed by the `PermissionSet` protocol — that model's
`get_permission()`: a dotted-path walk over a pydantic tree for ChurchTools, a flat membership test
for Immich. The payload shape is known where it is parsed, not in the client.

Every JSON answer goes through one primitive, `BaseAPI._validate(model, r)`, which raises; the
wrappers differ by what they do on failure, not by what they fetch: `_parse()` fails with a
`CliError` naming the endpoint, `_fetch()` adds the GET, `_fetch_required()` diagnoses URL and
token, `_fetch_version()` only warns. A call that degrades on an off-shape answer uses
`_validate()` directly and says why in a "Not `_parse()`" comment.

`ImmichAPI` asserts nothing: media upload and background download are independent optional
features. Its constructor makes no request and cannot fail, leaving both features off; `connect()`
contacts Immich and switches on each feature that is configured and permitted. Only URL and token
(`_fetch_required()`) can fail `connect()`, which `_handle_agenda()` therefore calls inside a
`guard()`; a failure while setting up one feature (tag or album lookup, tag creation) is caught
there and switches off just that feature, so their lookups use `_validate()`, not `_parse()`. So
`immich` is always an instance, and callers only ask its `upload_enabled` /
`backgrounds_enabled`. The upload is enabled by its tags — an empty `_upload_tag_ids` (none
configured or none usable) means nothing is uploaded, as no file may end up in Immich untagged.
Immich identifies its objects by UUID strings, typed by the `type UUID = str` alias in
`immich/__init__.py` in models and signatures alike, so they cannot be mistaken for other strings
like names.

**Server versions** follow the same pattern and live in `BaseAPI` as well: a client that needs
them fetches the version once in its constructor, `self._version = self._fetch_version(Model,
endpoint)`, and — as `BaseAPI._version` is typed by the `VersionInfo` protocol, next to
`PermissionSet` — its model supplies `get_version()`, turning the payload into a version string
(Immich: `major`/`minor`/`patch` of `/api/server/version`; ChurchTools: the `version` string of
the public `/api/info`). Only `BaseAPI` parses it into a `packaging.version.Version`:
`_fetch_version()` does so once and treats a string that does not parse like a failed request.
`_fetch_version()` logs the version at INFO, so the log file tells afterwards which server
versions a run talked to. A feature needing a newer server calls
`has_version(minimum, 'reason')` — log and skip like `has_permissions()`, an unknown version
counting as too old — against a named version string constant such as
`ImmichAPI.SEARCH_FILTER_VERSION = '3.2'`; `packaging` stays inside `BaseAPI`.

A ChurchTools `view *` permission is often a *list of ids*, not a boolean, so holding it does not
mean seeing every object — and the **element type names the axis those ids scope** (`CalendarID`,
`DomainID`, `ServiceGroupID`, `SongCategoryID`, each a commented `type` alias next to its model).
Whether a 403 on one object is a hole to absorb or an anomaly to let crash follows from those axes,
not from how coarse the list is: an event and its agenda are both scoped by `CalendarID`, so an
event that could be listed has a readable agenda and a 403 there means the permission changed
*during* the run — leave it to the traceback. A person on that event's service team is scoped by
`DomainID`, which the event says nothing about, so a 403 there is ordinary and takes the fallback
`get_person()` has. Name both axes before adding such a branch, and confirm what the server really
answers — a mocked 403 only proves what our code does with one. `SecurityLevel` is not an axis at
all: the levels gate *fields*, so an insufficient one yields a person with fields absent, never a
403, which is why the nickname warning fires after a successful parse.

**Agenda pipeline** (`churchtools/events.py`): `ChurchToolsEvent.download_agenda_items()` walks
event files and agenda items into `output_dir/{Songs,Files}`, feeds PDFs into `SongSheets` (chords
+ leads via reportlab/pypdf, "MISSING" watermark page for absent songs) and hands media files to
the `ImmichAPI` it is given, if its upload is enabled. It returns `(list[Item], SongSheets)` — the `list[Item]` is
the internal agenda representation shared with the SongBeamer writer, and *uploading* the sheets
is deliberately left to the caller, which does it as a guarded optional step.

**`AgendaItemType` lives in `configuration.py`**, next to `CalendarSubtitleField`, although the agenda
pipeline is what produces it: `SongBeamerColorConfig` is a
`RootModel[dict[AgendaItemType, SongBeamerColorItemConfig]]`, so the `[SongBeamer.Color]` TOML keys *are*
the `AgendaItemType` values (hence their capitalization), pydantic rejects a key that is no item type, and
`colors[item.type]` is a total, statically typed lookup. There is no second list of per-type fields
to keep in sync, so adding an `AgendaItemType` needs no other change. `Item` and `Person` stay in
`churchtools/events.py`.

**Song backgrounds** are the optional step after the download: `_handle_agenda()` calls
`SongBackgrounds(config, immich).add_missing()` (`songbeamer/sng.py`), which checks every
downloaded `.sng` for a `#BackgroundImage` header line and inserts one pointing at a random Immich
JPEG/PNG original of the album named `Immich.backgrounds_album`
(`ImmichAPI.download_random_background()`; every album of that name counts, own or shared). The
random search uses the structured `filter` of Immich 3.2 (`albumIds.any`, file name endings,
`trashedAt` — the filter does not exclude the trash on its own), and the feature is disabled on
older servers: they silently drop unknown fields and would return random assets of the whole
library. `sng.py` holds `SngFile`, the one place that decodes `.sng` content the way SongBeamer
does (UTF-8 with BOM, Windows ANSI without) and splits it into `header` (the leading `#Key=Value`
lines) and `body`. Song verification fills `Arrangement.sng_header` from it, so every `#Key` check
sees the header only, never a verse line starting with `#`. Undecodable bytes survive as
`surrogateescape`, so a file written back differs only in what was changed.

**SongBeamer output** (`songbeamer/__init__.py`) writes `Schedule.col`, a Delphi-style object text
format. The module docstring documents the grammar and the `'text'#252'more'` non-ASCII escaping;
`AgendaItem._encode`/`_decode` implement it (`_test_encode_decode` is a round-trip sanity helper).
Configured opening/closing/insert slides are authored as raw `item ... end` blocks in the TOML and
parsed back through `AgendaItem.parse`, so config content flows through the same encoder.

**PowerPoint** (`powerpoint/`): templates are driven by *shape names*, not indices — the ChurchTools
service name is the placeholder name in the services template, and the appointments template needs
tables named `Weekly Table` / `Irregular Table`. `powerpoint/__init__.py` holds `PowerPointBase`,
which loads the template and implements `save()`; a missing or unloadable template leaves `_prs` at
`None`, so both subclasses degrade to no-ops instead of failing. `services.py` monkey-patches
`python-pptx` to accept MPO JPEGs; the patch has a removal condition in its comment.

**Song verification** (`churchtools/song_verification.py`) uses a decorator registry:
`@SongChecks.register('CCLI')` on a `(Song, list[Arrangement]) -> list[str]` function. The key
doubles as the result-table column header and as the value accepted by `--execute_checks`, so adding
a check is a single registered function. A check that reads `Arrangement.sng_header` has to
say so with `needs_sng_header=True`, as `verify_songs()` downloads the `.sng` files only when an
active check asks for them; an undeclared read silently sees an empty list, so the declaration is
verified against what the checks actually read in `tests/test_song_verification.py`.

**Song usage statistics** (`churchtools/song_statistics.py`) counts song occurrences across the
events of a year range and emits them through a `BaseFormatter` ABC (`RichFormatter`,
`AsciiFormatter` on prettytable, `ExcelFormatter` on xlsxwriter, which requires `--output`). A new
format is an added `FormatType` value plus, unless prettytable already renders it, a formatter.

## Conventions

- **SPDX header required** on every source file (`ruff` `flake8-copyright` enforces
  `SPDX-FileCopyrightText:`).
- **Ruff with `select = ["ALL"]`**, line length 88, single quotes, LF endings. Only isort violations
  are auto-fixable — everything else is fixed by hand or suppressed with a targeted
  `# noqa: CODE (reason)`. Follow the existing per-line suppression style rather than widening the
  global ignore list — the `ignore` list in `pyproject.toml` is for rules rejected as a policy for
  the whole project, not for individual findings. `TRY400` is there deliberately: foreseen errors
  (a missing file, a rejected token, an unreachable host) are logged with `logger.error()` and no
  traceback, so the message has to carry the reason itself — pass the exception into it rather
  than dropping it.
- **pyright strict.** Untyped third-party surfaces are handled with narrow
  `# pyright: ignore[reportUnknownMemberType]` comments (Typer options are full of them) or local
  stubs under `typings/`.
- **Import style is module-level** (`import pathlib`, `pptx.shapes.placeholder`), not
  `from x import y`, except for internal `churchsong.*` symbols. Type-only imports go under
  `if typing.TYPE_CHECKING:`.
- **i18n:** `_()` is installed into builtins by `Configuration` (declared to ruff via
  `builtins = ["_"]`, and to pyright via `_: Callable[[str], str]` inside `TYPE_CHECKING` blocks).
  Catalogs are `.po` files loaded at runtime with polib — they are never compiled to `.mo`.
- **Errors reaching the user** are raised as `CliError` (alias of Click's `ClickException`) after
  logging; unexpected exceptions are logged with traceback in `main()` and re-raised.
- **Text from ChurchTools or from an exception must never reach rich's markup parser** — a song
  title or a server message containing `[/x]` raises `MarkupError` and takes the run down. There
  is no single mechanism; pick by the shape of the call: `markup=False` where the call owns the
  whole string (`console.print`; `rich.print` has no such parameter, so it becomes
  `rich.get_console().print`), `rich.text.Text(...)` cells where rich parses per cell
  (`Table.add_row`), and `rich.markup.escape()` only where a markup template has to survive
  around the untrusted part (`utils/progress.CustomTextColumn`) — it is the last resort, as it
  doubles a trailing backslash. Regression tests for the progress display need
  `monkeypatch.setenv('TTY_COMPATIBLE', '1')`, as rich renders nothing off a terminal and the
  test would pass vacuously.
- Long-running loops report progress through `utils/progress.Progress`.
