# ChurchSong

## Introduction

Purpose of this tool is to download the event agenda from ChurchTool as well as the
names of the children's church staff, preparing a PowerPoint slide with the names
and portraits to be presented at the beginning of the event.

## Prerequisites

A recent Python 3.x is required as well as some additional Python packages which
can be installed via `py -3 -m pip install -r requirements.txt`.

## Configuration

### Ini file

You need to copy the `ChurchSong.ini.example` to `ChurchSong.ini` and adjust the
content accordingly.

### PowerPoint template

You need to prepare a PowerPoint template with a slide master which contains
placeholders for pictures and names for the team members. The ChurchTool's service
team name has to be put at the PowerPoint base placeholder via the Select Pane
(Alt-F10).

## Usage

To download the upcoming agenda you can just execute `ChurchSong.bat` without any
switches (or double-click it). To specify a starting date to look for the next event,
you can specify a `FROM_DATE` as positional parameter in the form `YYYY-MM-DD`.

If everything goes well, the agenda is downloaded into the `temp_dir`, the slide is
created from the template, SongBeamer's `Schedule.col` is adjusted and finally
SongBeamer itself is launched with the prepared `Schedule.col`.

You can keep the `temp_dir` as is (it is added to and overwritten in future
invocations), but there is also no harm in deleting the `temp_dir` as it is
automatically re-created.
