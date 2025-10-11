# ChangeLog

## Unreleased

### Changed
- calculate last updated timestamp on the PDF song sheets from the agenda
- updated external dependencies (pydantic)
- lock Python to 3.13 until all dependencies support 3.14

## 0.10.11 (2025-10-05)

### Added
- added table of contents with songs title and arrangement to song sheets

### Changed
- updated external dependencies (certifi, pydantic)

## 0.10.10 (2025-10-04)

### Added
- put last updated timestamp onto the PDF song sheets

## 0.10.9 (2025-10-04)

### Added
- song sheets can be disabled from interactive start menu (enabled by default)

### Changed
- implement own focus button styling (allows for unpinning textual again)
- updated external dependencies (textual, typer)

## 0.10.8 (2025-10-03)

### Added
- download PDF song sheets (chords and leads) and upload complete song sheets to event

## 0.10.7 (2025-09-20)

### Changed
- pin textual<6.1.0 for now due to some change in hover handling (regression in 0.10.6)
- updated external dependencies (click, pydantic, typer, xlsxwriter)

## 0.10.6 (2025-09-05)

### Fixed
- fixed broken handling of single quotes in SongBeamer agenda items

### Changed
- updated external dependencies (textual)

## 0.10.5 (2025-09-01)

### Fixed
- fixed broken SongBeamer encode/decode for multiple non-ascii characters in a row

### Changed
- updated external dependencies (certifi, click, platformdirs, requests, textual, typer)

## 0.10.4 (2025-08-03)

## Added
- option how many weeks ahead to put onto appointment slides (space permitting)

## 0.10.3 (2025-08-02)

### Added
- separate format string for multi-day events (in addition to all-day and regular)

### Fixed
- fixed swapped time format for all-day and regular events (introduced with 0.10.0)

### Changed
- updated external dependencies (click, rich, textual)

## 0.10.2 (2025-07-26)

### Fixed
- fixed casing of config file path being incorrect for case-sensitive file systems

## 0.10.1 (2025-07-19)

### Changed
- put only appointments on slides that are not marked as internal appointment
- updated external dependencies (certifi, textual, xlsxwriter)

## 0.10.0 (2025-06-15)

### Added
- introduced configuration of datetime formats for weekly and irregular appointments

### Changed
- renamed configuration sections [ChurchTools.Settings] to [ChurchTools] and
  [SongBeamer.Settings] to [SongBeamer]

## 0.9.3 (2025-06-15)

### Added
- introduced configurable subtitle priorities for weekly and irregular appointments

### Changed
- released pin on click<8.2.0 as typer 0.16.0 now supports typer >=8.2.0
- updated external dependencies (pydantic, requests, textual, typer)

## 0.9.2 (2025-05-12)

### Fixed
- hopefully fix pinning click<8.2.0

## 0.9.1 (2025-05-12)

### Fixed
- pin transitive external dependency click<8.2.0 as typer 0.15.3 does not support it

## 0.9.0 (2025-05-09)

### Added
- create appointments slide from a PowerPoint template based on ChurchTools calendars,
  divide into two slides for weekly appointments and irregular appointments
- validate input of 'songs verify --execute_checks' to be actual check names

### Changed
- use 'rich.table' for console output of 'songs verify' and 'songs usage'
- updated external dependencies (certifi, platformdirs, pydantic, textual, typer)

## 0.8.1 (2025-04-24)

### Fixed
- fixed local time timezone not taking summer time into account when specifying time

### Changed
- replaced 'openpyxl' with 'xlsxwriter' to reduce dependencies
- use 'rich.print' for console output
- use 'packaging.version' for version parsing in the "update available" check
- updated external dependencies (textual)

## 0.8.0 (2025-04-19)

### Added
- 'songs verify' now also checks whether "EN/DE" songs have a #TitleLang2 set

### Fixed
- interactive screen: make container with checkboxes and submit button scrollable
  in case terminal window is too small

### Changed
- 'songs verify' switches --exclude_tags, --include_tags, and --execute_checks now
  require comma-separation if multiple tags/checks are specified per option
- internal refactorings
  (use 'typer' for command-line parsing, use 'rich.progress' for progress bars)
- updated external dependencies

## 0.7.5 (2025-04-12)

### Changed
- minor style tweaks (use textual-dark theme, highlight available update)
- updated external dependencies (textual)

## 0.7.4 (2025-04-11)

### Changed
- reworked visuals for a simpler design language
- updated external dependencies (pydantic)

## 0.7.3 (2025-04-06)

### Changed
- optimized interactive screen

## 0.7.2 (2025-04-06)

### Changed
- improve visuals of checkboxes
- disable execute button in case nothing is selected

## 0.7.1 (2025-04-05)

### Fixed
- fixed SongBeamer crash if a song contained apostrophe character (')

### Changed
- moved "SongBeamer already running notice" from config file to localization
- updated external dependencies (lxml)

## 0.7.0 (2025-04-05)

### Added
- display interactive selection screen what parts to download when starting without
  subcommand
- introduce localization and use it for the interactive selection screen
- improve output of stack traces
- updated external dependencies (pydantic)

## 0.6.3 (2025-03-29)

### Changed
- optimized loading of song tags for 'songs verify all'
- enforce alphabetical sorting in 'songs verify all' output
- updated external dependencies (platformdirs, prettytable, pydantic)

## 0.6.2 (2025-03-23)

### Changed
- do not use old ChurchTools AJAX API to fetch song tags any more, use new API instead

### Fixed
- fixed default output format 'text' for 'songs usage' crashing

## 0.6.1 (2025-03-17)

### Changed
- 'songs verify' only reports missing .sng file for the default arrangement from now on

## 0.6.0 (2025-03-14)

### Added
- when creating SongBeamer agenda, fall back to default arrangement of a song if an
  arrangement does not have a .sng file
- SongBeamer Schedule.col is created from scratch and not downloaded from ChurchTools
- new config options SongBeamer.Color.{Header,Normal,Song,Link,File} for color control
  of agenda items (consistent to already existing SongBeamer.Color.Service)

### Changed
- do not use ChurchTools' SongBeamer export but download .sng files individually (this
  change is required to realize the default arrangement fallback)
- 'songs verify --all' has been changed to 'songs verify all' to avoid specifying
  '--all' together with a date 'YYYY-MM-DD'
- 'songs verify' only checks default arrangements of songs unless '--all_arrangements'
  is specified
- updated external dependencies (prettytable)

### Removed
- config option SongBeamer.Color.Replacements is ignored from now on

## 0.5.21 (2025-02-22)

### Fixed
- fixed invalid SongBeamer Schedule.col file in case a caption was completely empty

## 0.5.20 (2025-02-14)

### Fixed
- 'songs usage -YYYY' syntax was not working as expected

### Changed
- adjust column width to cell with maximum content
- updated external dependencies

## 0.5.19 (2025-02-10)

### Fixed
- fixed broken xlsx output

## 0.5.18 (2025-02-10)

### Fixed
- fixed broken files for html, json, and latex

## 0.5.17 (2025-02-10)

### Added
- added output formats html, json, csv, and latex in addition to text and xlsx

### Fixed
- make song counts in Excel an integer instead of a string

## 0.5.16 (2025-02-10)

### Added
- command 'songs usage' to calculate and output song usage statistics per given year range

### Changed
- updated external dependencies

## 0.5.15 (2025-02-08)

### Added
- check for multiple songs with the same CCLI number (should rather be arrangements)

### Changed
- cover even more cases of wrongly configured URL/token and emit better error message

## 0.5.14 (2025-02-01)

### Fixed
- fixed crash if song has no duration set

### Changed
- safe-guard single usage of old ChurchTools AJAX API to fetch song tags
- better error messages (e.g. if SongBeamer cannot be started, or URL/token are not configured correctly)
- updated external dependencies

## 0.5.13 (2025-01-31)

### Changed
- remove hint how to update in 'self version' (leave it there in update notice)

## 0.5.12 (2025-01-31)

### Added
- update notice if a later version is available at PyPI

### Changed
- updated external dependencies

## 0.5.11 (2025-01-28)

### Fixed
- fallback image for missing portraits on PowerPoint slide not working (regression introduced in 0.5.10)
- do not try to query person's nickname if service person is external (regression introduced in 0.5.10)

## 0.5.10 (2025-01-25)

### Added
- if the API user has permissions to query a person's nickname, prefer this over firstname in PowerPoint slide

## 0.5.9 (2025-01-19)

### Fixed
- display error message if configuration file is invalid UTF-8

## 0.5.8 (2025-01-19)

### Changed
- for a person's name, prefer the information from the 'person' JSON element over the used name in the service

## 0.5.7 (2025-01-14)

### Changed
- make 'songs verify' only check next event agenda
- make 'songs verify YYYY-MM-DD' check a specific event agenda
- introduce 'songs verify --all' for whole song database

## 0.5.6 (2025-01-12)

### Changed
- refactored handling of datetime in argparse to always return timezone-aware objects

## 0.5.5 (2025-01-12)

### Added
- respect time in addition to date to support multiple events on the same day

## 0.5.4 (2025-01-12)

### Added
- YouTube links from ChurchTools agenda are converted to embedded YouTube links for SongBeamer

## 0.5.3 (2025-01-02)

### Fixed
- 'self update' not working on Windows due to file being in use

## 0.5.2 (2025-01-02)

### Added
- clearer error message if configuration file config.toml cannot be found/read

## 0.5.1 (2025-01-02)

### Fixed
- missing LICENSE file
- possible batch file recursion

## 0.5.0 (2025-01-02)

### Added
- initial packaged version available from PyPI
