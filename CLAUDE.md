# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`ChurchSong` is a CLI tool that pulls the next event agenda from a [ChurchTools](https://church.tools)
instance and turns it into what the service needs: a SongBeamer `Schedule.col`, PowerPoint slides
(service staff, upcoming appointments), PDF song sheets uploaded back to ChurchTools, and optional
media upload to [Immich](https://immich.app/). It also verifies the ChurchTools song database and
produces song usage statistics.

Runtime target is **Windows** (SongBeamer launching is win32-only); development happens on Linux
too. Requires **Python >= 3.14** (PEP 695 generics, PEP 758 `except A, B:`).

## Commands

[uv](https://docs.astral.sh/uv/) only; there is no `pip`/`venv` path.

```sh
uv sync
uv run ChurchSong --help
uv run ChurchSong agenda 2026-08-16
uv run ChurchSong songs verify all --execute_checks CCLI,Tags
uv run ChurchSong songs usage 2024-2026 --format rich
```

Quality gates (CI: `.github/workflows/code-quality.yml`; all but lockfile/build also run as the
pre-commit hook — `uv run pre-commit install` once, `git commit --no-verify` for red WIP):

```sh
uv lock --check
uv run ruff check .
uv run ruff format --check .    # drop --check to apply
uv run pyright --project .
uv run pytest
uv run typos --force-exclude
uv build
```

**Tests** (`tests/`): HTTP is mocked with `responses`, whose `RequestsMock` fails on any unexpected
*or unfired* request — that is how "a missing permission skips the upload" is asserted. Build
configurations with `tests/conftest.py`'s `make_config()`, never by constructing `Configuration`.
CLI commands run through Typer's `CliRunner` with `obj=make_config()`, the TUI through Textual's
`app.run_test()`.

After touching any `_('...')` string, run `./dev-scripts/translate.py`.

**OpenAPI check:** `uv run dev-scripts/check_openapi.py [instance-url | spec-file]` (default: the
public demo instance; also runs Fridays 16:00 UTC in `openapi-check.yml`) compares the ChurchTools
models with the published spec and exits 1 on findings not in its `KNOWN_DEVIATIONS`. The spec is
not the truth — it has declared fields non-null that the server sent as `null` — so confirm a
finding against real answers before changing a model, and record spec errors in
`KNOWN_DEVIATIONS` with the reason. A new endpoint needs an entry in its `ENDPOINTS` list (or in
`WRITE_ONLY_ENDPOINTS` of `tests/test_check_openapi.py` if no answer is read); the tests enforce it.

**Releases** use `bump-my-version`, which turns `## Unreleased` in `CHANGELOG.md` into the new
version — so add user-visible changes under `## Unreleased` as part of the change itself.

## Architecture

**Configuration** (`configuration.py`) is a frozen Pydantic tree loaded from TOML (path: `ChurchSong
self info`), built once in `main()` and threaded everywhere as Typer's `ctx.obj`. TOML sections are
PascalCase aliases, `${ENVVAR}` is expanded before validation, and it installs gettext and owns the
logging handlers. Every module uses its own `logging.getLogger(__name__)`; only `BaseAPI` takes its
logger from the subclass.

**Commands** live in `__main__.py`. Without a subcommand the Textual TUI runs and hands a
`DownloadSelection` to `_handle_agenda()`, the one orchestrator of ChurchTools → PowerPoint →
SongBeamer. Every optional step goes inside `_OptionalSteps.guard()`, so no failure can cost the
run its `Schedule.col`; anything assigned inside needs a value *before* the `with`, as the guard
swallows the exception and pyright does not flag the unbound case. The blocking PyPI check
(`later_version_available`) is asked only in `self info` and the TUI's worker thread — keep it off
every command's critical path.

**HTTP clients** subclass `utils/http.BaseAPI` (one `requests.Session`, `_get/_put/_post/_delete`).
Auth headers go per request, never on the session, so foreign-host downloads can drop them.
`BaseAPI` stays service-agnostic: service-specific behaviour (e.g. `persist_cookies`) is chosen at
the subclass's `super().__init__()` with a comment giving the reason.

- Every JSON answer goes through `BaseAPI._validate()`. `_parse()` fails with a `CliError` naming
  the endpoint, `_fetch()` adds the GET, `_fetch_required()` diagnoses URL and token,
  `_fetch_version()` only warns. A call that degrades on an off-shape answer uses `_validate()`
  directly and says why in a "Not `_parse()`" comment.
- **Permissions are two-tier**: a constructor hard-asserts what basic operation needs
  (`CliError`); every optional feature is a `Feature` constant on its client (permissions and
  an optional minimum server version, an unknown version counting as too old), gated by
  `has_feature(X)`, which logs and lets the caller skip; `missing_requirements(X)` gives the
  reasons without logging. `packaging` stays inside `BaseAPI`.
- `ImmichAPI` asserts nothing: its constructor makes no request, `connect()` (called inside a
  `guard()`) switches on each configured and permitted feature, and a failure setting up one
  feature switches off just that one. `connect()` only reads; `create_missing_tags()`, in the
  same `guard()`, creates the upload tags it did not find. Callers only ask `upload_enabled` /
  `backgrounds_enabled`.
  No file may end up in Immich untagged. Immich UUIDs are typed by `type UUID = str`.

**ChurchTools models** (`churchtools/__init__.py`) use camelCase aliases and the
`DeprecationAwareModel` base (a `DeprecationWarning` for development, not a log entry). ChurchTools
is hosted-only, so a quirk shim (`model_validator(mode='before')`, dated comment) adapts to what
the API answers *now*; one for a superseded answer is removed, not kept.

A ChurchTools `view *` permission is often a list of ids, and the id's type alias (`CalendarID`,
`DomainID`, `ServiceGroupID`, `SongCategoryID`) names the axis it scopes. Whether a 403 is a hole
to absorb or an anomaly to let crash follows from those axes: event and agenda are both scoped by
`CalendarID`, so a 403 on the agenda of a listed event means the permission changed mid-run (let
it crash); a service-team person is scoped by `DomainID`, so a 403 there is ordinary and takes
`get_person()`'s fallback. Name both axes before adding such a branch, and confirm what the real
server answers. `SecurityLevel` gates *fields*, never yields a 403.

**Agenda pipeline** (`churchtools/events.py`): `download_agenda_items()` returns
`(list[Item], SongSheets)`; uploading the sheets is the caller's guarded step. `AgendaItemType`
lives in `configuration.py` because the `[SongBeamer.Color]` TOML keys *are* its values — adding a
type needs no other change.

**Song backgrounds** (`songbeamer/sng.py`): `SongBackgrounds.add_missing()` inserts a
`#BackgroundImage` line pointing at a random image of the Immich `backgrounds_album`; an absolute
path to a missing file counts as none, a relative one is left to SongBeamer. The search needs
Immich 3.2's structured `filter` (which does not exclude the trash on its own); older servers
silently drop unknown fields, so the feature is off there. `SngFile` is the one place that decodes
`.sng` (UTF-8 with BOM, else Windows ANSI, `surrogateescape`) and splits `header` from `body`; `#Key`
checks see the header only.

**SongBeamer output** (`songbeamer/__init__.py`): the `Schedule.col` grammar and escaping are in the
module docstring; configured slides are parsed back through `AgendaItem.parse`.

**PowerPoint** (`powerpoint/`): templates are driven by *shape names* (the service name is the
placeholder name; tables `Weekly Table` / `Irregular Table`). A missing template leaves `_prs` at
`None` and the classes become no-ops.

**Song verification**: `@SongChecks.register('KEY')`, the key doubling as column header and
`--execute_checks` value. A check reading `Arrangement.sng_header` must declare
`needs_sng_header=True` (verified by a test). **Song statistics**: a new format is a `FormatType`
value plus, unless prettytable renders it, a `BaseFormatter`.

## Conventions

- **Attribution** of commits and pull requests is a single `Assisted-By: Claude <model>` line — no
  `Co-Authored-By`, no session link, no "Generated with" footer.
- **SPDX header** on every source file; the `spdx-headers` pre-commit hook adds it or extends the
  year range, then stops the commit so the files can be reviewed and staged.
- **Ruff `select = ["ALL"]`**, line length 88, single quotes, LF. Fix by hand or with a targeted
  `# noqa: CODE (reason)`; the global `ignore` list is only for project-wide policy. `TRY400` is
  ignored deliberately: foreseen errors are logged with `logger.error()` without traceback, so the
  message must include the exception.
- **pyright strict**: narrow `# pyright: ignore[reportUnknownMemberType]` comments or stubs in
  `typings/`.
- **Imports** are module-level (`import pathlib`), except internal `churchsong.*` symbols;
  type-only imports go under `if typing.TYPE_CHECKING:`.
- **i18n**: `_()` is a builtin installed by `Configuration` (pyright: `_: Callable[[str], str]`
  under `TYPE_CHECKING`); `.po` catalogs are loaded with polib, never compiled to `.mo`.
- **User-facing errors** are logged, then raised as `CliError`.
- **Untrusted text** (from ChurchTools or an exception) must never reach rich's markup parser:
  `markup=False` where the call owns the string (`rich.get_console().print`, not `rich.print`),
  `rich.text.Text` cells in tables, `rich.markup.escape()` only as a last resort. Progress-display
  tests need `monkeypatch.setenv('TTY_COMPATIBLE', '1')`, or they pass vacuously.
- Long-running loops report progress through `utils/progress.Progress`.
