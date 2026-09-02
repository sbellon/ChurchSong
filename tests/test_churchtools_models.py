# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import datetime
import warnings

import pytest

from churchsong.churchtools import (
    CalendarAppointmentAppointment,
    EventAgendaItem,
    EventAgendaItemType,
    EventService,
    PermissionsGlobalData,
    Person,
)
from tests.conftest import make_global_permissions

AGENDA_ITEM_META = {'modifiedDate': '2026-08-16T10:00:00Z'}


def test_agenda_item_null_title_becomes_empty_string() -> None:
    item = EventAgendaItem.model_validate({'title': None, 'meta': AGENDA_ITEM_META})
    assert item.title == ''


def test_agenda_item_legacy_type_normal_maps_to_text() -> None:
    item = EventAgendaItem.model_validate(
        {'title': 'Notes', 'type': 'normal', 'meta': AGENDA_ITEM_META}
    )
    assert item.type is EventAgendaItemType.TEXT


def make_appointment_json(
    *, all_day: bool, calculated: dict[str, str] | None
) -> dict[str, object]:
    data: dict[str, object] = {
        'base': {
            'title': 'Prayer Meeting',
            'subtitle': None,
            'description': None,
            'image': None,
            'link': None,
            'isInternal': False,
            'startDate': '2026-08-16T10:00:00Z',
            'endDate': '2026-08-16T12:00:00Z',
            'allDay': all_day,
            'repeatId': 7,
            'repeatFrequency': 1,
            'address': None,
        },
    }
    if calculated is not None:
        data['calculated'] = calculated
    return data


def test_appointment_all_day_dates_get_time_and_timezone_attached() -> None:
    appointment = CalendarAppointmentAppointment.model_validate(
        make_appointment_json(
            all_day=True,
            calculated={'startDate': '2026-08-23', 'endDate': '2026-08-23'},
        )
    )
    start = appointment.base.start_date
    end = appointment.base.end_date
    assert start.tzinfo is not None
    assert start.date() == datetime.date(2026, 8, 23)
    assert start.time() == datetime.time.min
    assert end.date() == datetime.date(2026, 8, 23)
    assert end.time() == datetime.time.max


def test_appointment_calculated_dates_override_base_dates() -> None:
    appointment = CalendarAppointmentAppointment.model_validate(
        make_appointment_json(
            all_day=False,
            calculated={
                'startDate': '2026-08-23T10:00:00Z',
                'endDate': '2026-08-23T12:00:00Z',
            },
        )
    )
    assert appointment.base.start_date.day == 23
    assert appointment.base.end_date.day == 23


def test_appointment_without_calculated_dates_keeps_base_dates() -> None:
    appointment = CalendarAppointmentAppointment.model_validate(
        make_appointment_json(all_day=False, calculated=None)
    )
    assert appointment.base.start_date.day == 16
    assert appointment.base.end_date.day == 16


def test_event_service_prefers_person_domain_attributes_over_name() -> None:
    service = EventService.model_validate(
        {
            'personId': 5,
            'name': 'Fallback Name',
            'serviceId': 1,
            'person': {
                'title': 'Title Name',
                'domainAttributes': {'firstName': 'Jane', 'lastName': 'Doe'},
            },
        }
    )
    assert service.name == 'Jane Doe'


def test_event_service_falls_back_to_person_title() -> None:
    service = EventService.model_validate(
        {
            'personId': 5,
            'name': 'Fallback Name',
            'serviceId': 1,
            'person': {'title': 'Title Name', 'domainAttributes': {}},
        }
    )
    assert service.name == 'Title Name'


def test_deprecated_field_dict_form_emits_warning() -> None:
    with pytest.warns(DeprecationWarning, match="consider using 'givenName'"):
        Person.model_validate(
            {
                'firstName': 'Jane',
                'lastName': 'Doe',
                '@deprecated': {'firstName': 'givenName'},
            }
        )


def test_deprecated_field_string_form_emits_warning() -> None:
    with pytest.warns(DeprecationWarning, match="consider using 'givenName'"):
        Person.model_validate(
            {
                'firstName': 'Jane',
                'lastName': 'Doe',
                '@deprecated': 'firstName (now: givenName)',
            }
        )


def test_deprecation_of_unused_field_stays_silent() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        Person.model_validate(
            {
                'firstName': 'Jane',
                'lastName': 'Doe',
                '@deprecated': {'unusedField': 'newField'},
            }
        )


def test_get_permission_resolves_bools_lists_and_unknowns() -> None:
    permissions = PermissionsGlobalData.model_validate(make_global_permissions())
    assert permissions.get_permission('churchservice:view') is True
    assert permissions.get_permission('churchservice:view agenda') == [1]
    assert permissions.get_permission('churchdb:view alldata') == [1]
    assert permissions.get_permission('churchservice:does not exist') is False


def test_get_permission_empty_id_list_is_falsy() -> None:
    permissions = PermissionsGlobalData.model_validate(
        make_global_permissions(edit_events=False)
    )
    assert not permissions.get_permission('churchservice:edit events')


def test_get_permission_of_a_whole_group_is_falsy() -> None:
    permissions = PermissionsGlobalData.model_validate(make_global_permissions())
    # 'churchdb' addresses a group of permissions, not a single permission.
    assert permissions.get_permission('churchdb') is False
