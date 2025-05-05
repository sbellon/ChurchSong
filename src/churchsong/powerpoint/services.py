# SPDX-FileCopyrightText: 2024-2025 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import os
import typing

import pptx
import pptx.shapes
import pptx.shapes.placeholder

from churchsong.churchtools.events import Person
from churchsong.configuration import Configuration
from churchsong.powerpoint import PowerPointBase


class PowerPointServices(PowerPointBase):
    def __init__(self, config: Configuration) -> None:
        super().__init__(config, config.services_template_pptx, config.output_dir)
        self._portraits_dir = config.services_portraits_dir

    def create(self, service_leads: dict[str, set[Person]]) -> None:
        self._log.info('Creating PowerPoint services slide')
        if self._prs.core_properties.revision == 1:  # pyright: ignore[reportUnknownMemberType]
            # Presentation is the fallback created one, just skip everything
            return
        slide_layout = self._prs.slide_layouts[0]
        slide = self._prs.slides.add_slide(slide_layout)
        for ph in slide.placeholders:
            base_placeholder = typing.cast(
                'pptx.shapes.placeholder.BasePlaceholder',
                getattr(ph, '_base_placeholder', None),
            )
            service_name = base_placeholder.name
            sorted_persons = sorted(
                service_leads[service_name], key=lambda p: p.fullname
            )
            person_fullnames = ' + '.join(p.fullname for p in sorted_persons)
            person_shortnames = ' + '.join(p.shortname for p in sorted_persons)
            match ph:
                case pptx.shapes.placeholder.PicturePlaceholder():
                    self._log.debug(
                        'Replacing image placeholder %s with %s',
                        service_name,
                        person_fullnames,
                    )
                    try:
                        ph.insert_picture(  # pyright: ignore[reportUnknownMemberType]
                            os.fspath(self._portraits_dir / f'{person_fullnames}.jpeg')
                        )
                    except FileNotFoundError as e:
                        self._log.error(f'Cannot embed portrait picture: {e}')
                        no_persons = ' + '.join(
                            sorted(p.fullname for p in service_leads[str(None)])
                        )
                        ph.insert_picture(  # pyright: ignore[reportUnknownMemberType]
                            os.fspath(self._portraits_dir / f'{no_persons}.jpeg')
                        )
                case pptx.shapes.placeholder.SlidePlaceholder() if ph.has_text_frame:
                    self._log.debug(
                        'Replacing text placeholder %s with %s',
                        service_name,
                        person_shortnames,
                    )
                    ph.text_frame.paragraphs[0].text = person_shortnames
                case _:
                    self._log.warning(
                        'Skipping unsupported placeholder type %s',
                        ph.placeholder_format.type,
                    )
        _ = service_leads.pop(str(None), None)
