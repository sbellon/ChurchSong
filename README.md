# ChurchSong

## Introduction

The main purpose of this tool is to download the event agenda from ChurchTool as well
as the names of the service staff, preparing a PowerPoint slide with the names and
portraits to be presented at the beginning of the event.

Additionally, the SongBeamer agenda can be modified by placing slides at the opening
or closing, or after specific keywords. Colors of the SongBeamer captions can also be
configured.

The ChurchTools song database can also be checked for consistency regarding metadata
as well as present .sng files to contain a background image.

Finally, you can create song usage statistics in various output formats for chosen
time periods.

## Installation

### Automatic installation

A simple installation method (including a generic configuration template that you still
have to configure for your needs) is to execute the following in a `cmd.exe` shell:

```
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/sbellon/ChurchSong/refs/heads/main/resources/install.ps1 | iex"
```

A shortcut will be installed on the desktop and command `ChurchSong` will be available
from the command line.

### Manual installation

If you do not want to use this method, you will have to do a manual install.

The recommendation is to use Python package manager [uv](https://docs.astral.sh/uv/)
which you have to install first and make it accessible via PATH. This can be done by
following the steps listed at
[Standalone Installer](https://docs.astral.sh/uv/getting-started/installation/).

Afterwards you have to execute `uv install ChurchSong` to install ChurchSong itself.

You may put the files `ChurchSong.bat` and `ChurchSong.ico` from `resources` folder
somewhere for convenience as you can just double-click it to load the upcoming agenda
and start SongBeamer.

Command `ChurchSong` will be available from the command line afterwards.

### Updating

Once installed via `uv` you can update to the latest release version by executing
`ChurchSong self update` from the command line.

## Configuration

### Config file

You can check the location of your configuration files by executing
`ChurchSong self info` from the command line. Typically, on Windows, the location of
the configuration file will be `%LOCALAPPDATA%\ChurchSong\config.toml`.

You need to adjust the content of `%LOCALAPPDATA%\ChurchSong\config.toml` for your
needs (at least `base_url` and `login_token`).

If you used the simple installation method above, the template was copied there for
you, if you did a manual install you have to copy `resources/config.toml.example`
there for yourself.

### PowerPoint templates

Depending on configuration you can have two PowerPoint slides created. If you have
questions regarding how to create those templates, please get in contact with me.

#### Service slide

You can prepare a PowerPoint template with a slide master which contains placeholders
for pictures and names for the team members. The ChurchTool's service team name has to
be put at the PowerPoint base placeholder via the Select Pane (Alt-F10).

#### Appointment slide

You can prepare a PowerPoint template with two actual slides containing a table with
two columns each. One of the tables needs to be named `Weekly Table` and the other
needs to be named `Irregular Table` (use the Select Pane with Alt-F10). Appointments
will be added to those tables depending on whether they are weekly recurring or not.

## Usage

### SongBeamer agenda download

To download the upcoming agenda you can just execute `ChurchSong` without any switches
(e.g., double-click it) to use an interactive menu where you can select the desired
parts to download (default is all) and then execute the agenda download.

Or you can bypass the interactive menu and use the command `agenda`. To specify a
starting date to look for the next event, you can specify additional command line
arguments `agenda DATE` as positional parameter with `DATE` in an ISO date format
(e.g., `YYYY-MM-DD`, `YYYY-MM-DDT10:00:00`, or `YYYY-MM-DDT10:00:00+01:00`).

If everything goes well, the agenda is downloaded into the `output_dir`, the slides
are created from the templates, a `Schedule.col` for SongBeamer is created and finally
SongBeamer itself is launched with the prepared `Schedule.col`.

You can keep the `output_dir` as is (it is added to and overwritten in future
invocations), but there is also no harm in deleting the `output_dir` as it is
automatically re-created.

### ChurchTools song verification

With the additional command family `songs verify` you can check the songs for specific
properties like CCLI number, song name, tags, arrangement source, duration, a
SongBeamer `.sng` file with the `#BackgroundImage` property set, and consistency of
`#LangCount` property and e.g. a tag `EN/DE`.

Without any further argument, `songs verify` checks the songs for the next agenda that
would appear when just using `agenda` command.

With `songs verify DATE` you can select to only check the songs of the next event
agenda after `DATE` (like `agenda DATE`, `DATE` can be an ISO date format, e.g.,
`YYYY-MM-DD`, `YYYY-MM-DDT10:00:00`, or `YYYY-MM-DDT10:00:00+01:00`).

You can check the whole ChurchTools songs database by using `songs verify all`.

Only the default arrangements of the songs are verified, unless you also specify
`--all_arrangements` in which case all arrangements are checked for.

By using command options `--exclude_tags` and/or `--include_tags` you can filter out
songs with specific tags or only include songs with specific tags in the check.

With option `--execute_checks` you can define which verification checks to execute.

### Song usage statistics

If you are interested in how many times what song has been performed in a specific
year or in specific years, you can use `songs usage` to create output in various
formats (currently supporting `rich`, `text`, `html`, `json`, `csv`, `latex`,
`mediawiki`, and `xlsx`) by specifying the format with `--format`.

Output format `xlsx` requires to specify an output file using `--output`. This is
optional for all other output formats.

The time period for the statistics can be specified using either `YYYY`, `-YYYY`,
`YYYY-`, or `YYYY-YYYY`.
