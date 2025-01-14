# ChurchSong

## Introduction

The main purpose of this tool is to download the event agenda from ChurchTool as well
as the names of the service staff, preparing a PowerPoint slide with the names and
portraits to be presented at the beginning of the event.

Additionally, the SongBeamer agenda can be modified by placing slides at the opening
or closing, or after specific keywords. Colors of the SongBeamer captions can also be
changed.

The ChurchTools song database can also be checked for consistency regarding metadata
as well as present .sng files to contain a background image.

## Prerequisites

Python package manager [uv](https://docs.astral.sh/uv/) must be installed and
accessible via PATH. Easiest way is to follow the steps listed as
[Standalone Installer](https://docs.astral.sh/uv/getting-started/installation/).

## Installation

Simply install ChurchSong by executing `uv install ChurchSong`. Tool `ChurchSong` is
then available from the command line.

You may place the files `ChurchSong.bat` and `ChurchSong.ico` from the `resources`
folder somewhere for convenience as you can just double-click it to load the upcoming
agenda and start SongBeamer.

## Configuration

### Config file

You need to copy the `resources/config.toml.example` to
`%LOCALAPPDATA%\ChurchSong\config.toml` and adjust the content accordingly.

### PowerPoint template

You need to prepare a PowerPoint template with a slide master which contains
placeholders for pictures and names for the team members. The ChurchTool's service
team name has to be put at the PowerPoint base placeholder via the Select Pane
(Alt-F10).

## Usage

### SongBeamer agenda download

To download the upcoming agenda you can just execute `ChurchSong` without any switches
(e.g., double-click it) or use the command `agenda`. To specify a starting date to
look for the next event, you can specify additional command line arguments
`agenda FROM_DATE` as positional parameter with `FROM_DATE` in an ISO date format
(e.g., `YYYY-MM-DD`, `YYYY-MM-DDT10:00:00`, or `YYYY-MM-DDT10:00:00+01:00`).

If everything goes well, the agenda is downloaded into the `temp_dir`, the slide is
created from the template, SongBeamer's `Schedule.col` is adjusted and finally
SongBeamer itself is launched with the prepared `Schedule.col`.

You can keep the `temp_dir` as is (it is added to and overwritten in future
invocations), but there is also no harm in deleting the `temp_dir` as it is
automatically re-created.

### ChurchTools song verification

With the additional command family `songs verify` you can check the songs for specific
properties like CCLI number, song name, tags, arrangement source, duration and a
SongBeamer `.sng` file with the `#BackgroundImage` property set.

Without any further argument, `songs verify` checks the songs for the next agenda that
would appear when just using `agenda` command.

With `songs verify FROM_DATE` you can select to only check the songs of the next event
agenda after `FROM_DATE` (like `agenda FROM_DATE`, `FROM_DATE` can be an ISO date
format, e.g., `YYYY-MM-DD`, `YYYY-MM-DDT10:00:00`, or `YYYY-MM-DDT10:00:00+01:00`).

You can check the whole ChurchTools songs database by using `songs verify --all`.

By using command options `--exclude_tags` and/or `--include_tags` you can filter out
songs with specific tags or only include songs with specific tags in the check.
