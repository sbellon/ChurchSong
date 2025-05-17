# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import typing

import rustshed

__all__ = ['Null', 'NullType', 'Option', 'Some']

T_co = typing.TypeVar('T_co', covariant=True)


class ConversionError(TypeError):
    def __init__(self) -> None:
        super().__init__('bool()/len() conversion not allowed for Option[T] instances')


class Some[T_co](rustshed.Some[T_co]):
    def __bool__(self) -> typing.NoReturn:
        raise ConversionError

    def __len__(self) -> typing.NoReturn:
        raise ConversionError


class NullType(rustshed.NullType):
    def __bool__(self) -> typing.NoReturn:
        raise ConversionError

    def __len__(self) -> typing.NoReturn:
        raise ConversionError


Null = NullType()

Option = Some[T_co] | NullType
