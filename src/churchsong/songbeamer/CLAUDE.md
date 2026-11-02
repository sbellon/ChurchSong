**Song backgrounds** (`sng.py`): `SongBackgrounds.add_missing()` inserts a
`#BackgroundImage` line pointing at a random image of the Immich `backgrounds_album`; an absolute
path to a missing file counts as none, a relative one is left to SongBeamer. The search needs
Immich 3.2's structured `filter` (which does not exclude the trash on its own); older servers
silently drop unknown fields, so the feature is off there. `SngFile` is the one place that decodes
`.sng` (UTF-8 with BOM, else Windows ANSI, `surrogateescape`) and splits `header` from `body`; `#Key`
checks see the header only.

**SongBeamer output** (`__init__.py`): the `Schedule.col` grammar and escaping are in the module
docstring; configured slides are parsed back through `AgendaItem.parse`.
