# ChangeLog

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
