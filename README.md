# ChurchSong

## Introduction

Purpose of this tool is to download the event agenda from ChurchTool as well as the
names of the service staff, preparing a PowerPoint slide with the names
and portraits to be presented at the beginning of the event.

## Prerequisites

Python package manager [uv](https://docs.astral.sh/uv/) must be placed in subfolder
`bin` or be accessible via PATH.

## Configuration

### Ini file

You need to copy the `ChurchSong.toml.example` to `ChurchSong.toml` and adjust the
content accordingly.

### PowerPoint template

You need to prepare a PowerPoint template with a slide master which contains
placeholders for pictures and names for the team members. The ChurchTool's service
team name has to be put at the PowerPoint base placeholder via the Select Pane
(Alt-F10).

## Usage

### SongBeamer agenda download

To download the upcoming agenda you can just execute `ChurchSong.bat` without any
switches (or double-click it). To specify a starting date to look for the next event,
you can specify additional command line arguments `agenda FROM_DATE` as positional
parameter with `FROM_DATE` in the form `YYYY-MM-DD`.

If everything goes well, the agenda is downloaded into the `temp_dir`, the slide is
created from the template, SongBeamer's `Schedule.col` is adjusted and finally
SongBeamer itself is launched with the prepared `Schedule.col`.

You can keep the `temp_dir` as is (it is added to and overwritten in future
invocations), but there is also no harm in deleting the `temp_dir` as it is
automatically re-created.

### ChurchTools song verification

With the additional command `songs verify` you can check the songs in the
ChurchTools song database for specific properties like CCLI number, song name, tags,
arrangement source, duration and a SongBeamer `.sng` file with the `#BackgroundImage`
property set.

Using command options `--exclude_tags` and/or `--include_tags` you can filter out
songs with specific tags or only include songs with specific tags in the check.
