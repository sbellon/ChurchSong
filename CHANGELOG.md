# ChangeLog

## [0.5.10] - 2025-01-25

### Added
- if the API user has permissions to query a person's nickname, prefer this over firstname in PowerPoint slide

## [0.5.9] - 2025-01-19

### Fixed
- display error message if configuration file is invalid UTF-8

## [0.5.8] - 2025-01-19

### Changed
- for a person's name, prefer the information from the 'person' JSON element over the used name in the service

## [0.5.7] - 2025-01-14

### Changed
- make 'songs verify' only check next event agenda
- make 'songs verify YYYY-MM-DD' check a specific event agenda
- introduce 'songs verify --all' for whole song database

## [0.5.6] - 2025-01-12

### Changed
- refactored handling of datetime in argparse to always return timezone-aware objects

## [0.5.5] - 2025-01-12

### Added
- respect time in addition to date to support multiple events on the same day

## [0.5.4] - 2025-01-12

### Added
- YouTube links from ChurchTools agenda are converted to embedded YouTube links for SongBeamer

### Changed
- restructured folder layout and moved optional files into resources

## [0.5.3] - 2025-01-02

### Fixed
- 'self update' not working on Windows due to file being in use

## [0.5.2] - 2025-01-02

### Added
- clearer error message if configuration file config.toml cannot be found/read

## [0.5.1] - 2025-01-02

### Fixed
- missing LICENSE file
- possible batch file recursion

## [0.5.0] - 2025-01-02

### Added
- initial packaged version available from PyPI
