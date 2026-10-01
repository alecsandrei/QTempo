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
    SAI,
    YEARS,
    agr101a,
    by_sex,
    dimension,
    feature_collection,
    leaf_node,
    localities,
    not_geographic,
    pivot,
    request_body,
    square,
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


def agricultural(matrix: Matrix) -> Matrix:
    """The agricultural area, with one column per year."""
    return matrix.pivot({matrix.fields.get('Categorii'): 'Agricola'})


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


def test_values_are_numbers() -> None:
    assert agr101a()[agr101a().fields.value] == [
        182115.0,
        23787.0,
        158328.0,
        100.0,
        200.0,
    ]


def test_distinct_keeps_the_query_order() -> None:
    matrix = agr101a()
    assert matrix.distinct(matrix.fields.unit) == [
        SAI,
        'Municipiul Bucuresti',
        'Ilfov',
    ]


def test_pivot_keeps_bucharest_apart_from_the_agricultural_sector() -> None:
    pivoted = agricultural(agr101a())
    assert [field_.name for field_ in pivoted.fields] == [
        'Judete',
        'Anul 1990',
        'Anul 2000',
    ]
    assert codes(pivoted) == [None, 'RO321', 'RO322']
    assert pivoted.data == [
        [SAI, 182115.0, None],
        ['Municipiul Bucuresti', None, 23787.0],
        ['Ilfov', None, 158328.0],
    ]


def test_pivot_with_two_column_dimensions() -> None:
    pivoted = agr101a().pivot({})
    assert [field_.name for field_ in pivoted.fields] == [
        'Judete',
        'Agricola · Anul 1990',
        'Agricola · Anul 2000',
        'Arabila · Anul 2000',
    ]
    assert pivoted.data == [
        [SAI, 182115.0, None, None],
        ['Municipiul Bucuresti', None, 23787.0, 100.0],
        ['Ilfov', None, 158328.0, 200.0],
    ]


def test_default_fixed() -> None:
    matrix = agr101a()
    assert matrix.default_fixed() == {
        matrix.fields.get('Categorii'): 'Agricola'
    }


def test_default_fixed_prefers_the_total() -> None:
    matrix = by_sex()
    assert matrix.default_fixed() == {matrix.fields.get('Sexe'): 'Total'}


def test_pivot_with_every_dimension_fixed() -> None:
    matrix = localities()
    pivoted = matrix.pivot(matrix.default_fixed())
    assert [field_.name for field_ in pivoted.fields] == [
        'Localitati',
        'Valoare',
    ]
    assert codes(pivoted) == [None, '1017', '179132']


def test_default_fixed_keeps_the_single_values() -> None:
    matrix = localities()
    assert matrix.default_fixed() == {matrix.fields.get('Ani'): 'Anul 2000'}


def test_localities() -> None:
    matrix = localities()
    assert matrix.fields.unit.name == 'Localitati'
    assert codes(matrix) == [None, '1017', '179132']
    assert matrix.levels == [Level.LOCALITY]
    assert matrix.unresolved_labels == ['TOTAL']


def test_not_geographic() -> None:
    matrix = not_geographic()
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
    pivoted = agricultural(agr101a())
    geojson = feature_collection(
        square(0, 0, NUTS_ID='RO321', NAME_LATN='Bucureşti'),
        square(1, 0, NUTS_ID='RO322', NAME_LATN='Ilfov'),
        square(2, 0, NUTS_ID='RO111', NAME_LATN='Bihor'),
    )
    fields = QgsJsonUtils.stringToFields(geojson)
    features = QgsJsonUtils.stringToFeatureList(geojson, fields)
    layer = pivoted.join_boundaries(
        fields, features, 'NUTS_ID', 'AGR101A', 'EPSG:3844'
    )
    assert layer.crs().authid() == 'EPSG:3844'
    assert layer.fields().names() == [
        'NUTS_ID',
        'NAME_LATN',
        'Judete',
        'Anul 1990',
        'Anul 2000',
    ]
    assert values(layer, 'NUTS_ID') == {
        'RO321': ['RO321', 'Bucureşti', 'Municipiul Bucuresti', None, 23787.0],
        'RO322': ['RO322', 'Ilfov', 'Ilfov', None, 158328.0],
    }
    for feature in layer.getFeatures():
        assert QgsWkbTypes.isMultiType(feature.geometry().wkbType())


def test_join_boundaries_with_another_schema() -> None:
    pivoted = agricultural(agr101a())
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
    layer = pivoted.join_boundaries(fields, features, 'NUTS_ID', 'AGR101A')
    assert values(layer, 'NUTS_ID')['RO322'][:2] == ['RO322', None]


def test_to_float() -> None:
    assert to_float('23787') == 23787.0
    assert to_float(':') is None
    assert to_float(None) is None
