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

**Tests** live in `tests/` (pytest). Pure logic is tested directly; the ChurchTools/Immich HTTP
clients are tested with the `responses` library mocking `requests` at the adapter level —
endpoints are registered with realistic JSON, and `responses.RequestsMock` also fails the test on
any unexpected or unfired request (used to assert that e.g. missing permissions skip an upload).
`tests/conftest.py` provides `FakeConfiguration`, which validates a dict through the real config
model tree while bypassing `Configuration.__init__`'s file/logging/gettext side effects — reach for
it through the `make_config()` helper or the `config` / `mocked_responses` / `churchtools_api`
fixtures instead of constructing `Configuration` in tests. CLI commands are driven end-to-end with
Typer's `CliRunner` and `obj=make_config()` (`test_cli.py`), the TUI with Textual's `app.run_test()`
pilot (`test_interactivescreen.py`). Tests are held to the same ruff/pyright gates as the source (a
few relaxations in `[tool.ruff.lint.per-file-ignores]`). Full end-to-end behaviour (SongBeamer
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
- It also owns logging setup (stderr until the config is read, then a rotating file handler) and
  installs the gettext translation. The handlers go onto the `churchsong` root logger and
  `__init__` clears them first, so building a `Configuration` twice does not log everything
  twice. Nothing else takes a logger from the config: every module has its own
  `logger = logging.getLogger(__name__)`, propagation carries the records up to those handlers,
  and `%(name)s` in the formatter names the component in the log file. `utils/http.BaseAPI` is
  the exception - it is shared infrastructure and takes the logger to use from its subclass.

**Command surface** lives entirely in `__main__.py` (Typer app + `songs` and `self` sub-apps). With
no subcommand it launches the Textual TUI in `interactivescreen.py`, which returns a
`DownloadSelection` and feeds the same `_handle_agenda()` path as the `agenda` command —
`_handle_agenda` is the one place that orchestrates ChurchTools → PowerPoint → SongBeamer.
Everything optional in it — the Immich connector, the service team information, both slide decks,
the song sheet upload — runs inside `_OptionalSteps.guard()`, which logs the failure, records it
and lets the pipeline continue, so that no error in them can cost the run its `Schedule.col`;
`report()` then prints one console line per skipped step before the schedule is written and
SongBeamer is launched. A new optional step belongs in a `guard()` rather than in the bare
sequence, and anything it assigns to needs a value before the `with`, as the guard swallows the
exception. Date and year-range arguments are parsed by the `parser=` callables in `utils/date.py`.
The PyPI check in `Configuration.later_version_available` blocks, so only two places ask for it:
`self info`, where the answer is the output, and the TUI, which runs it in a Textual thread worker
and updates its header once the answer arrives - no command puts it on its critical path.
`self update` `exec`s `uv tool upgrade` in place, because it rewrites files that are currently in
use.

**HTTP clients** subclass `utils/http.BaseAPI`, which owns one `requests.Session` per instance
(connection reuse, closed via `atexit`) and provides `_get/_put/_post/_delete` wrappers that prefix
`self._base_url`, attach `self._headers`, log, and `raise_for_status()`. Auth headers are passed
per-request and deliberately *not* put on the session, so downloads from a foreign host can drop
them (`is_same_host()`). `ChurchToolsAPI` and `ImmichAPI` both subclass it.

`BaseAPI` stays service-agnostic: it defaults to normal `requests` cookie handling and only *offers*
`persist_cookies=False`, which blocks the session jar from storing and sending cookies (cookies
within a single redirect chain still work). Whether to use it is each client's decision, taken with
the reason next to the `super().__init__()` call — `ChurchToolsAPI` opts out because a login token
authenticates every request on its own, but ChurchTools still answers with a `ChurchToolsV2_*`
session cookie; sending that back switches it to session authentication, which then rejects every
state-changing request lacking a `CSRF-Token` header with a 401. `ImmichAPI` keeps the default. Add
service-specific HTTP behaviour this way rather than by putting it into `BaseAPI`.

**ChurchTools API models** (`churchtools/__init__.py`) are Pydantic models mirroring the JSON, with
camelCase aliases and `DeprecationAwareModel` as base — it inspects the `@deprecated` key ChurchTools
returns and emits `DeprecationWarning` when a model still uses a superseded field. Several models
carry `model_validator(mode='before')` shims for ChurchTools quirks (null titles, `normal` → `text`
item type, all-day appointment dates without timezone). When the upstream API changes, that is where
compatibility patches go — dated comments mark the existing ones.

**Permissions are two-tier**, in both clients. `ChurchToolsAPI.__init__` fetches
`/api/permissions/global` and `ImmichAPI.__init__` fetches `/api/api-keys/me` once, then
hard-assert what basic operation needs (raising `CliError`): the `churchservice:view*` set for
ChurchTools, `asset.upload` for Immich — the Immich one only ever costs the media upload, because
`_handle_agenda` constructs `ImmichAPI` inside a `guard()` and hands the download `None` if that
failed. Everything optional — appointment slides, nickname lookup, song sheet upload/delete, and
Immich's `tag.create`/`tag.read`/`tag.asset` — calls `has_permissions([...], 'reason')`, which logs
a warning and lets the caller skip that feature. Add new optional features this way rather than by
asserting. The fetch/assert/`has_permissions` trio is duplicated per client because the two
permission payloads have different shapes.

**Agenda pipeline** (`churchtools/events.py`): `ChurchToolsEvent.download_agenda_items()` walks event
files and agenda items, downloads `.sng` and attachments into `output_dir/{Songs,Files}`, feeds PDFs
into `SongSheets` (chords + leads, built with reportlab/pypdf, with a "MISSING" watermark page for
absent songs), and hands media files to the `ImmichAPI` it is given, if any. It returns the
`list[Item]` that is the internal agenda representation shared with the SongBeamer writer, plus the
`SongSheets` — uploading those back as event files is left to the caller, which does it as one of
its guarded optional steps.

**`ItemType` values must stay in sync with the field names of `SongBeamerColorConfig`** — the color
lookup is `getattr(colors, item.type.value)`, which is why both are capitalized.

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
a check is a single registered function. A check that reads `Arrangement.sng_file_content` has to
say so with `needs_sng_content=True`, as `verify_songs()` downloads the `.sng` files only when an
active check asks for them; an undeclared read silently sees an empty list, so the declaration is
verified against what the checks actually read in `tests/test_song_verification.py`.

**Song usage statistics** (`churchtools/song_statistics.py`) counts song occurrences across the
events of a year range and emits them through a `BaseFormatter` ABC: `RichFormatter` (console),
`AsciiFormatter` (prettytable, covering `text`/`html`/`json`/`csv`/`latex`/`mediawiki`) and
`ExcelFormatter` (xlsxwriter, which requires `--output`). A new format is an added `FormatType`
value plus, unless prettytable already renders it, a formatter.

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
- Long-running loops report progress through `utils/progress.Progress`.
