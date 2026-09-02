# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

from rich.progress import Task, TaskID
from rich.table import Column

from churchsong.utils.progress import (
    CustomTextColumn,
    CustomTimeElapsedColumn,
    CustomTimeRemainingColumn,
)


def make_task(
    description: str = 'Downloading',
    *,
    total: float | None = 10,
    finished_time: float | None = None,
) -> Task:
    return Task(
        id=TaskID(0),
        description=description,
        total=total,
        completed=0.0,
        _get_time=lambda: 0.0,
        finished_time=finished_time,
    )


def test_description_is_truncated_to_the_length_of_the_first_one() -> None:
    column = CustomTextColumn('{task.description}', table_column=Column())
    # The first rendered description locks the column width ...
    assert str(column.render(make_task('Downloading'))) == 'Downloading'
    # ... so that a longer one afterwards does not widen the progress bar.
    assert str(column.render(make_task('Downloading: A song'))) == 'Downloadin…'


def test_elapsed_time_of_a_task_that_never_started() -> None:
    assert str(CustomTimeElapsedColumn().render(make_task())) == '-s'


def test_elapsed_time_is_rendered_as_whole_seconds() -> None:
    assert str(CustomTimeElapsedColumn().render(make_task(finished_time=3.7))) == '3s'


def test_remaining_time_of_a_finished_task_is_shown_as_elapsed() -> None:
    column = CustomTimeRemainingColumn(elapsed_when_finished=True)
    text = column.render(make_task(finished_time=3.0))
    assert text.style == 'progress.elapsed'


def test_remaining_time_without_a_total_stays_empty() -> None:
    text = CustomTimeRemainingColumn().render(make_task(total=None))
    assert str(text) == ''
