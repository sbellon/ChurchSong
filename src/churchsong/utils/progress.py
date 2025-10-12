# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import contextlib
import typing

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Task,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.progress import Progress as _Progress
from rich.progress_bar import ProgressBar
from rich.table import Column
from rich.text import Text
from rich.theme import Theme

if typing.TYPE_CHECKING:
    from rich.console import JustifyMethod
    from rich.highlighter import Highlighter
    from rich.style import StyleType


class CustomTextColumn(TextColumn):
    def __init__(  # noqa: PLR0913
        self,
        text_format: str,
        max_description_length: int | None = None,
        style: StyleType = 'none',
        justify: JustifyMethod = 'left',
        markup: bool = True,
        highlighter: Highlighter | None = None,
        table_column: Column | None = None,
    ) -> None:
        super().__init__(text_format, style, justify, markup, highlighter, table_column)
        self._dynamic_length = max_description_length is None
        self._locked_length = max_description_length

    def render(self, task: Task) -> Text:
        if self._dynamic_length and self._locked_length is None:
            self._locked_length = len(task.description)

            # Optional: dynamically update the column width
            if self._table_column:
                self._table_column.min_width = self._locked_length

        desc = task.description
        if self._locked_length is not None and len(desc) > self._locked_length:
            desc = desc[: self._locked_length - 1] + '…'

        text = self.text_format.format(task=task).replace(task.description, desc, 1)
        return (
            Text.from_markup(text)
            if self.markup
            else Text(text, style=self.style, justify=self.justify)
        )


class CustomBarColumn(BarColumn):
    def render(self, task: Task) -> ProgressBar:
        return ProgressBar(
            total=None if task.total is None else max(0, task.total),
            completed=max(0, task.completed),
            width=None if self.bar_width is None else max(1, self.bar_width),
            pulse=not task.started or task.total is None,
            animation_time=task.get_time(),
            style=self.style,
            complete_style=self.complete_style,
            finished_style=self.finished_style,
            pulse_style=self.pulse_style,
        )


class CustomTimeElapsedColumn(TimeElapsedColumn):
    def render(self, task: Task) -> Text:
        elapsed = task.finished_time if task.finished else task.elapsed
        if elapsed is None:
            return Text('-s', style='progress.elapsed')
        return Text(f'{max(0, int(elapsed))}s', style='progress.elapsed')


class CustomTimeRemainingColumn(TimeRemainingColumn):
    def render(self, task: Task) -> Text:
        if self.elapsed_when_finished and task.finished:
            task_time = task.finished_time
            style = 'progress.elapsed'
        else:
            task_time = task.time_remaining
            style = 'progress.remaining'

        if task.total is None:
            return Text('', style=style)

        if task_time is None:
            return Text('(~?s)', style=style)

        return Text(f'(~{task_time}s)', style=style)


class Progress(_Progress):
    def __init__(self, description: str, total: int | None) -> None:
        super().__init__(
            CustomTextColumn(
                '[progress.description]{task.description}', table_column=Column()
            ),
            CustomBarColumn(bar_width=None, table_column=Column(ratio=2)),
            MofNCompleteColumn(),
            TaskProgressColumn(
                text_format='[progress.percentage][{task.percentage:>3.0f}%]'
            ),
            CustomTimeElapsedColumn(),
            CustomTimeRemainingColumn(),
            console=Console(
                theme=Theme(
                    {
                        'progress.description': 'white',
                        'progress.download': 'white',
                        'progress.percentage': 'white',
                        'progress.elapsed': 'white',
                        'progress.remaining': 'white',
                        #'bar.back': 'black',
                        'bar.complete': 'green',
                        #'bar.finished': 'bright_green',
                        #'bar.remaining': 'grey23',
                        'bar.pulse': 'green',
                    }
                )
            ),
            transient=True,
            expand=True,
        )
        self._task = self.add_task(description=description, total=total)

    @contextlib.contextmanager
    def do_progress[T](
        self, item: T, description: str | None = None
    ) -> typing.Generator[T]:
        self.update(self._task, description=description)
        try:
            yield item
        finally:
            self.advance(self._task)

    def iterate[T](self, items: typing.Iterable[T]) -> typing.Generator[T]:
        for item in items:
            with self.do_progress(item) as i:
                yield i
