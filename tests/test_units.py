from __future__ import annotations

import collections.abc as c

import pytest

from qtempo.enums import Level
from qtempo.units import TerritorialUnit, normalize, resolve_dimension

from .helpers import dimension

COUNTIES = ['Bihor', 'Bistrita-Nasaud', 'Cluj', 'Maramures', 'Arad']


def resolve(
    labels: c.Sequence[str], ro_labels: c.Sequence[str] | None = None
) -> dict[str, str | None] | None:
    """The NUTS codes of the labels, or None if they are not geographic."""
    options = dimension(1, 'Judete', labels)['options']
    ro_options = (
        options
        if ro_labels is None
        else dimension(1, 'Judete', ro_labels)['options']
    )
    units = resolve_dimension(options, ro_options)
    if units is None:
        return None
    return {
        label: unit.code if unit is not None else None
        for label, unit in units.items()
    }


def test_normalize_removes_the_region_prefix_and_separators() -> None:
    assert normalize('Regiunea BUCURESTI - ILFOV') == 'BUCURESTI-ILFOV'
    assert normalize('Bucureşti-Ilfov') == 'BUCURESTI-ILFOV'


def test_normalize_removes_cedilla_and_comma_below() -> None:
    cedilla = normalize('Bistriţa-Năsăud')
    comma_below = normalize('Bistrița-Năsăud')
    assert cedilla == comma_below == 'BISTRITA-NASAUD'


def test_normalize_keeps_the_municipality_prefix() -> None:
    assert normalize('Municipiul Arad') == 'MUNICIPIUL-ARAD'


def test_from_siruta_label() -> None:
    unit = TerritorialUnit.from_siruta_label('1017 Municipiul Alba Iulia')
    assert unit == TerritorialUnit(
        Level.LOCALITY, '1017', '1017 Municipiul Alba Iulia'
    )


def test_from_siruta_label_without_code() -> None:
    with pytest.raises(ValueError):
        TerritorialUnit.from_siruta_label('TOTAL')


def test_every_level_resolves() -> None:
    labels = ['TOTAL', 'MACROREGIUNEA UNU', 'Regiunea NORD-VEST', 'Bihor']
    options = dimension(1, 'Regiuni', labels)['options']
    units = resolve_dimension(options, options)
    assert units is not None
    assert [unit.level for unit in units.values() if unit is not None] == [
        Level.COUNTRY,
        Level.MACROREGION,
        Level.REGION,
        Level.COUNTY,
    ]


def test_counties() -> None:
    assert resolve(COUNTIES) == {
        'Bihor': 'RO111',
        'Bistrita-Nasaud': 'RO112',
        'Cluj': 'RO113',
        'Maramures': 'RO114',
        'Arad': 'RO421',
    }


def test_bucharest_without_the_ilfov_agricultural_sector() -> None:
    labels = ['Municipiul Bucuresti', 'Ilfov', 'Mun. Bucuresti -incl. SAI']
    assert resolve(labels) == {
        'Municipiul Bucuresti': 'RO321',
        'Ilfov': 'RO322',
        'Mun. Bucuresti -incl. SAI': None,
    }


def test_municipality_is_not_its_county() -> None:
    units = resolve([*COUNTIES, 'Municipiul Arad'])
    assert units is not None
    assert units['Arad'] == 'RO421'
    assert units['Municipiul Arad'] is None


def test_labels_with_the_same_code_are_unmapped() -> None:
    units = resolve([*COUNTIES, 'ARAD'])
    assert units is not None
    assert units['Arad'] is None
    assert units['ARAD'] is None
    assert units['Bihor'] == 'RO111'


def test_translated_labels_resolve_through_the_romanian_ones() -> None:
    units = resolve(
        ['NORTH - WEST', 'CENTRE', 'NORTH - EAST'],
        ['Regiunea NORD-VEST', 'Regiunea CENTRU', 'Regiunea NORD-EST'],
    )
    assert units == {
        'NORTH - WEST': 'RO11',
        'CENTRE': 'RO12',
        'NORTH - EAST': 'RO21',
    }


@pytest.mark.parametrize(
    'labels',
    [
        ['TOTAL'],
        ['TOTAL', 'Nivel national'],
        ['Anul 1990', 'Anul 2000'],
        ['Bihor', 'Cluj', 'Urban', 'Rural', 'Altele'],
    ],
)
def test_not_geographic(labels: list[str]) -> None:
    assert resolve(labels) is None


def test_geographic_share_threshold() -> None:
    units = resolve(['Bihor', 'Cluj', 'Alba', 'Urban', 'Rural'])
    assert units is not None
    assert units['Urban'] is None
