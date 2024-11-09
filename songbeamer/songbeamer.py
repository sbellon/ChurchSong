import os
import subprocess
import sys

from configuration import Configuration


class SongBeamer:
    def __init__(self, config: Configuration) -> None:
        self._log = config.log
        self._temp_dir = config.temp_dir.resolve()
        self._schedule_filepath = self._temp_dir / 'Schedule.col'
        self._replacements = config.replacements

    def modify_and_save_agenda(self) -> None:
        self._log.info('Modifying SongBeamer schedule')
        with self._schedule_filepath.open(mode='r', encoding='utf-8') as fd:
            content = fd.read()
        for search, replace in self._replacements:
            content = content.replace(search, replace)
        with self._schedule_filepath.open(mode='w', encoding='utf-8') as fd:
            fd.write(content)

    def launch(self) -> None:
        self._log.info('Launching SongBeamer instance')
        if sys.platform == 'win32':
            subprocess.run(
                [os.environ.get('COMSPEC', 'cmd'), '/C', 'start Schedule.col'],
                check=True,
                cwd=self._temp_dir,
            )
        else:
            sys.stderr.write(
                f'Error: Starting SongBeamer not supported on {sys.platform}\n'
            )
            sys.exit(1)
