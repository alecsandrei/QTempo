from __future__ import annotations

import typing as t

from qgis.core import (
    QgsJsonUtils,
    QgsVariantUtils,
    QgsVectorLayer,
    QgsWkbTypes,
)

from qtempo.enums import Level
from qtempo.matrix import Matrix, to_float

from .helpers import (
    dimension,
    feature_collection,
    leaf_node,
    pivot,
    request_body,
    square,
)

CATEGORIES = dimension(1, 'Categorii', ['Agricola', 'Arabila'])
YEARS = dimension(3, 'Ani', ['Anul 1990', 'Anul 2000'])
SAI = 'Mun. Bucuresti -incl. SAI'


def agr101a() -> Matrix:
    """Agricultural area by county, where the 1990 value of Bucharest
    includes today's Ilfov."""
    counties = dimension(2, 'Judete', ['Municipiul Bucuresti', 'Ilfov', SAI])
    response = pivot(
        ['Categorii', 'Judete', 'Ani', 'Valoare'],
        ['Agricola', SAI, 'Anul 1990', '182115'],
        ['Agricola', 'Municipiul Bucuresti', 'Anul 2000', '23787'],
        ['Agricola', 'Ilfov', 'Anul 2000', '158328'],
        ['Arabila', 'Municipiul Bucuresti', 'Anul 2000', '100'],
        ['Arabila', 'Ilfov', 'Anul 2000', '200'],
    )
    return Matrix.from_response(
        response,
        request_body(matTime=3),
        leaf_node(CATEGORIES, counties, YEARS),
    )


def localities() -> Matrix:
    labels = [
        'TOTAL',
        '1017 Municipiul Alba Iulia',
        '179132 Municipiul Bucuresti',
    ]
    response = pivot(
        ['Localitati', 'Ani', 'Valoare'],
        *([label, 'Anul 2000', '1'] for label in labels),
    )
    return Matrix.from_response(
        response,
        request_body(matTime=2, nomLoc=1, matSiruta=1),
        leaf_node(dimension(1, 'Localitati', labels), YEARS),
    )


def mixed_levels() -> Matrix:
    labels = ['TOTAL', 'Regiunea NORD-VEST', 'Cluj', 'Bihor']
    response = pivot(
        ['Regiuni', 'Ani', 'Valoare'],
        *(
            [label, year, '1']
            for label in labels
            for year in ('Anul 1990', 'Anul 2000')
        ),
    )
    return Matrix.from_response(
        response,
        request_body(matTime=2, matRegJ=1),
        leaf_node(dimension(1, 'Regiuni', labels), YEARS),
    )


def codes(matrix: Matrix) -> list[str | None]:
    assert matrix.units is not None
    return [unit.code if unit is not None else None for unit in matrix.units]


def values(layer: QgsVectorLayer, key: str) -> dict[str, list[t.Any]]:
    """The attributes of each feature by its key, with None for NULL."""
    return {
        feature[key]: [
            None if QgsVariantUtils.isNull(value) else value
            for value in feature.attributes()
        ]
        for feature in layer.getFeatures()
    }


def test_geographic_dimension_without_flags() -> None:
    matrix = agr101a()
    assert matrix.fields.unit.name == 'Judete'
    assert codes(matrix) == [None, 'RO321', 'RO322', 'RO321', 'RO322']
    assert matrix.levels == [Level.COUNTY]


def test_unresolved_labels() -> None:
    assert agr101a().unresolved_labels == [SAI]


def test_group_by_keeps_bucharest_apart_from_the_agricultural_sector() -> None:
    matrix = agr101a()
    grouped = matrix.group_by(
        matrix.fields.get('Ani'),
        {matrix.fields.get('Categorii'): 'Agricola'},
    )
    assert [field_.name for field_ in grouped.fields] == [
        'Anul 1990',
        'Anul 2000',
    ]
    assert codes(grouped) == ['RO321', 'RO322']
    assert grouped.data == [[None, '23787'], [None, '158328']]


def test_localities() -> None:
    matrix = localities()
    assert matrix.fields.unit.name == 'Localitati'
    assert codes(matrix) == [None, '1017', '179132']
    assert matrix.levels == [Level.LOCALITY]
    assert matrix.unresolved_labels == ['TOTAL']


def test_not_geographic() -> None:
    response = pivot(
        ['Categorii', 'Ani', 'Valoare'],
        ['Agricola', 'Anul 2000', '1'],
    )
    matrix = Matrix.from_response(
        response, request_body(matTime=2), leaf_node(CATEGORIES, YEARS)
    )
    assert not matrix.has_units
    assert matrix.levels == []
    assert matrix.unresolved_labels == []


def test_levels() -> None:
    matrix = mixed_levels()
    assert matrix.levels == [Level.COUNTRY, Level.REGION, Level.COUNTY]
    counties = matrix.filter_level(Level.COUNTY)
    assert codes(counties) == ['RO113', 'RO113', 'RO111', 'RO111']
    assert [unit.code for unit in matrix.get_units(Level.COUNTY)] == [
        'RO111',
        'RO113',
    ]


def test_as_table_adds_the_codes() -> None:
    layer = agr101a().as_table('AGR101A')
    assert layer.fields().names()[-1] == 'NUTS_ID'
    assert [
        None if QgsVariantUtils.isNull(code) else code
        for code in (feature['NUTS_ID'] for feature in layer.getFeatures())
    ] == [None, 'RO321', 'RO322', 'RO321', 'RO322']


def test_as_table_adds_the_siruta_codes() -> None:
    layer = localities().as_table('POP107D')
    assert layer.fields().names()[-1] == 'SIRUTA'


def test_join_boundaries() -> None:
    matrix = agr101a()
    grouped = matrix.group_by(
        matrix.fields.get('Ani'),
        {matrix.fields.get('Categorii'): 'Agricola'},
    )
    geojson = feature_collection(
        square(0, 0, NUTS_ID='RO321', NAME_LATN='Bucureşti'),
        square(1, 0, NUTS_ID='RO322', NAME_LATN='Ilfov'),
        square(2, 0, NUTS_ID='RO111', NAME_LATN='Bihor'),
    )
    fields = QgsJsonUtils.stringToFields(geojson)
    features = QgsJsonUtils.stringToFeatureList(geojson, fields)
    layer = grouped.join_boundaries(
        fields, features, 'NUTS_ID', 'AGR101A', 'EPSG:3844'
    )
    assert layer.crs().authid() == 'EPSG:3844'
    assert layer.fields().names() == [
        'NUTS_ID',
        'NAME_LATN',
        'Anul 1990',
        'Anul 2000',
    ]
    assert values(layer, 'NUTS_ID') == {
        'RO321': ['RO321', 'Bucureşti', None, 23787.0],
        'RO322': ['RO322', 'Ilfov', None, 158328.0],
    }
    for feature in layer.getFeatures():
        assert QgsWkbTypes.isMultiType(feature.geometry().wkbType())


def test_join_boundaries_with_another_schema() -> None:
    matrix = agr101a()
    grouped = matrix.group_by(
        matrix.fields.get('Ani'),
        {matrix.fields.get('Categorii'): 'Agricola'},
    )
    geojson = feature_collection(
        square(0, 0, NUTS_ID='RO321', NAME_LATN='Bucureşti')
    )
    fields = QgsJsonUtils.stringToFields(geojson)
    other = feature_collection(square(1, 0, NUTS_ID='RO322'))
    features = [
        *QgsJsonUtils.stringToFeatureList(geojson, fields),
        *QgsJsonUtils.stringToFeatureList(
            other, QgsJsonUtils.stringToFields(other)
        ),
    ]
    layer = grouped.join_boundaries(fields, features, 'NUTS_ID', 'AGR101A')
    assert values(layer, 'NUTS_ID')['RO322'][:2] == ['RO322', None]


def test_to_float() -> None:
    assert to_float('23787') == 23787.0
    assert to_float(':') is None
    assert to_float(None) is None
