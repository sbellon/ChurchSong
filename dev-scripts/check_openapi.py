#!/usr/bin/env -S uv run
#
# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

# Compares the ChurchTools API models against the OpenAPI description a ChurchTools
# instance publishes, so that an upstream change shows up here rather than as a
# failing run on a Sunday morning. Run from the repository, as it imports the models:
#
#     uv run dev-scripts/check_openapi.py
#     uv run dev-scripts/check_openapi.py https://example.church.tools
#     uv run dev-scripts/check_openapi.py openapi-ui.json
#
# Without an argument, the spec comes from ChurchTools' public demo instance. As
# ChurchTools is only offered as a hosted service, every instance runs the current
# version and serves the same spec, so no particular church needs to be asked.
#
# Every field a model reads, by its alias, is looked up in the response schema of the
# endpoint that parses it, and reported if the spec does not document it, marks it
# deprecated, lets it be null where the model requires a value, gives it another
# type, or allows enum values the model does not know. Fields the spec has and the
# models do not read are of no interest. Whether a field may be missing is not
# checked: the spec hardly ever lists its `required` fields, not even for `/info`.
# Exits with 1 if anything is reported that is not in KNOWN_DEVIATIONS.

import dataclasses
import datetime as dt
import enum
import json
import pathlib
import sys
import types
import typing

import pydantic
import requests

from churchsong.churchtools import (
    CalendarAppointmentsData,
    CalendarsData,
    EventAgendaData,
    EventFullData,
    EventsData,
    Info,
    PermissionsGlobalData,
    PersonsData,
    ServicesData,
    SongData,
    SongsData,
)

SPEC_PATH = '/system/runtime/swagger/openapi-ui.json'
DEFAULT_SOURCE = 'https://demo.church.tools'
REQUEST_TIMEOUT = 60

# The GET endpoints `ChurchToolsAPI` calls, as the spec spells their paths (relative
# to the `/api` server), and the model it parses the 200 answer with.
ENDPOINTS: dict[str, type[pydantic.BaseModel]] = {
    '/info': Info,
    '/permissions/global': PermissionsGlobalData,
    '/calendars': CalendarsData,
    '/calendars/appointments': CalendarAppointmentsData,
    '/events': EventsData,
    '/events/{eventId}': EventFullData,
    '/events/{eventId}/agenda': EventAgendaData,
    '/events/{eventId}/agenda/songs': SongsData,
    '/persons/{personId}': PersonsData,
    '/services': ServicesData,
    '/songs': SongsData,
    '/songs/{songId}': SongData,
}

# Where the spec is known to be wrong, keyed by the path a finding is reported under,
# with the reason we trust our model instead. An entry that no longer matches a
# finding is reported as stale, so this list cannot outlive the deviations in it.
KNOWN_DEVIATIONS: dict[str, str] = {
    '/events/{eventId}/agenda/songs.meta.pagination': (
        'optional in `SongsMeta`, which this endpoint shares with the paginated /songs'
    ),
}

type JsonSchema = dict[str, typing.Any]

JSON_TYPE_OF: dict[type, str] = {
    bool: 'boolean',
    int: 'integer',
    float: 'number',
    str: 'string',
    dt.datetime: 'string',
    dt.date: 'string',
}


@dataclasses.dataclass
class Node:
    """A schema with `$ref`, `allOf`, `oneOf` and `anyOf` resolved away."""

    types: set[str] = dataclasses.field(default_factory=set[str])
    properties: dict[str, JsonSchema] = dataclasses.field(
        default_factory=dict[str, JsonSchema]
    )
    items: list[JsonSchema] = dataclasses.field(default_factory=list[JsonSchema])
    enum: set[typing.Any] | None = None
    deprecated: bool = False

    @property
    def nullable(self) -> bool:
        return 'null' in self.types

    def add(self, other: Node, combinator: typing.Literal['allOf', 'anyOf']) -> None:
        self.types.update(other.types)
        # A property declared in both stands for both declarations, combined the way
        # their containers are: in every part of an `allOf`, in any of a `oneOf`.
        for key, schema in other.properties.items():
            self.properties[key] = (
                {combinator: [self.properties[key], schema]}
                if key in self.properties
                else schema
            )
        self.items.extend(other.items)


def schema_types(schema: JsonSchema) -> set[str]:
    match schema.get('type'):
        case str() as single:
            found = {single}
        case list():
            found = set(typing.cast('list[str]', schema['type']))
        case _:
            found = set[str]()
    if schema.get('nullable'):  # OpenAPI 3.0 spelling of `null` in `type`
        found.add('null')
    return found


class Spec:
    def __init__(self, document: JsonSchema) -> None:
        self._document = document

    def response_schema(self, path: str) -> JsonSchema | None:
        try:
            answer = self._document['paths'][path]['get']['responses']['200']
            return answer['content']['application/json']['schema']
        except KeyError:
            return None

    def _deref(self, schema: JsonSchema) -> JsonSchema:
        while '$ref' in schema:
            target: typing.Any = self._document
            for key in schema['$ref'].removeprefix('#/').split('/'):
                target = target[key]
            # OpenAPI 3.1 allows keywords next to `$ref`, which apply on top.
            schema = {**target, **{k: v for k, v in schema.items() if k != '$ref'}}
        return schema

    def node(self, schema: JsonSchema) -> Node:
        schema = self._deref(schema)
        node = Node(
            types=schema_types(schema), deprecated=schema.get('deprecated', False)
        )
        node.properties.update(schema.get('properties', {}))
        if 'items' in schema:
            node.items.append(schema['items'])
        if 'enum' in schema:
            node.enum = set(schema['enum'])
        if 'const' in schema:
            node.enum = {schema['const']}
        # All of them hold: everything they declare adds up.
        for part in map(self.node, schema.get('allOf', [])):
            node.add(part, 'allOf')
            node.deprecated |= part.deprecated
        # Any one of them holds: an enum is closed only if every alternative closes it.
        alternatives = [
            self.node(s) for s in schema.get('oneOf', []) + schema.get('anyOf', [])
        ]
        for alternative in alternatives:
            node.add(alternative, 'anyOf')
        if alternatives and all(
            a.enum is not None or a.types == {'null'} for a in alternatives
        ):
            node.enum = set[typing.Any]().union(
                *(a.enum for a in alternatives if a.enum is not None)
            )
        return node


@dataclasses.dataclass
class Finding:
    path: str
    message: str


def unwrap(annotation: typing.Any) -> tuple[typing.Any, bool]:  # noqa: ANN401 (any annotation)
    """Strip type aliases and `None` off an annotation, telling whether it was there."""
    nullable = False
    while True:
        if isinstance(annotation, typing.TypeAliasType):
            annotation = annotation.__value__
        elif typing.get_origin(annotation) in {types.UnionType, typing.Union}:
            members = [a for a in typing.get_args(annotation) if a is not type(None)]
            nullable |= len(members) < len(typing.get_args(annotation))
            if len(members) != 1:
                return typing.Union[tuple(members)], nullable  # noqa: UP007 (runtime)
            annotation = members[0]
        else:
            return annotation, nullable


def compare_type(
    spec: Spec,
    annotation: typing.Any,  # noqa: ANN401 (any annotation)
    node: Node,
    path: str,
) -> typing.Iterator[Finding]:
    annotation, _ = unwrap(annotation)
    actual = node.types - {'null'}
    if isinstance(annotation, type) and issubclass(annotation, pydantic.BaseModel):
        if actual and 'object' not in actual:
            yield Finding(path, f'is {sorted(actual)} in the spec, not an object')
        else:
            yield from compare_model(spec, annotation, node, path)
    elif typing.get_origin(annotation) is list:
        if actual and 'array' not in actual:
            yield Finding(path, f'is {sorted(actual)} in the spec, not an array')
        (item_type,) = typing.get_args(annotation)
        for item in node.items:
            yield from compare_type(spec, item_type, spec.node(item), f'{path}[]')
    else:
        yield from compare_scalar(annotation, node, path)


def compare_scalar(
    annotation: typing.Any,  # noqa: ANN401 (any annotation)
    node: Node,
    path: str,
) -> typing.Iterator[Finding]:
    actual = node.types - {'null'}
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        known = {member.value for member in annotation}
        if node.enum is None:
            yield Finding(path, 'is not an enum in the spec, any value may come')
        elif unknown := node.enum - known - {None}:
            yield Finding(path, f'may be {sorted(unknown, key=str)}, unknown to us')
    elif expected := JSON_TYPE_OF.get(typing.cast('type', annotation)):
        # An integer is a number too, so a spec saying `integer` suits a `float`.
        if (
            actual
            and expected not in actual
            and not (expected == 'number' and 'integer' in actual)
        ):
            yield Finding(path, f'is {sorted(actual)} in the spec, not {expected}')
    else:
        yield Finding(path, f'has a type this script cannot compare: {annotation}')


def compare_model(
    spec: Spec, model: type[pydantic.BaseModel], node: Node, path: str
) -> typing.Iterator[Finding]:
    for name, field in model.model_fields.items():
        key = field.alias or name
        field_path = f'{path}.{key}'
        if key not in node.properties:
            yield Finding(field_path, 'is not documented in the spec')
            continue
        child = spec.node(node.properties[key])
        _, nullable = unwrap(field.annotation)
        if child.deprecated:
            yield Finding(field_path, 'is deprecated in the spec')
        if child.nullable and not nullable:
            yield Finding(field_path, 'may be null, but the model does not allow it')
        yield from compare_type(spec, field.annotation, child, field_path)


def load(source: str) -> JsonSchema:
    if source.startswith(('http://', 'https://')):
        r = requests.get(
            source.rstrip('/') + SPEC_PATH,
            headers={'Accept': 'application/json'},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    return json.loads(pathlib.Path(source).read_text(encoding='utf-8'))


def main() -> int:
    if len(sys.argv) > 2:  # noqa: PLR2004 (program name and an optional argument)
        print(f'usage: {sys.argv[0]} [BASE_URL|SPEC_FILE]', file=sys.stderr)  # noqa: T201
        return 2
    document = load(sys.argv[1] if len(sys.argv) == 2 else DEFAULT_SOURCE)  # noqa: PLR2004
    spec = Spec(document)
    findings: list[Finding] = []
    for endpoint, model in ENDPOINTS.items():
        schema = spec.response_schema(endpoint)
        if schema is None:
            findings.append(Finding(endpoint, 'has no documented 200 JSON answer'))
        else:
            findings += compare_model(spec, model, spec.node(schema), endpoint)

    unexpected = [f for f in findings if f.path not in KNOWN_DEVIATIONS]
    known = [f for f in findings if f.path in KNOWN_DEVIATIONS]
    stale = KNOWN_DEVIATIONS.keys() - {f.path for f in findings}
    for finding in unexpected:
        print(f'{finding.path} {finding.message}')  # noqa: T201
    for finding in known:
        print(  # noqa: T201
            f'{finding.path} {finding.message} '
            f'(known: {KNOWN_DEVIATIONS[finding.path]})'
        )
    for path in sorted(stale):
        print(f'{path} is in KNOWN_DEVIATIONS, but no longer deviates')  # noqa: T201
    version = document.get('info', {}).get('version', '?')
    print(  # noqa: T201
        f'{len(ENDPOINTS)} endpoints checked against spec version {version}: '
        f'{len(unexpected)} unexpected, {len(known)} known, {len(stale)} stale'
    )
    return 1 if unexpected or stale else 0


if __name__ == '__main__':
    sys.exit(main())
