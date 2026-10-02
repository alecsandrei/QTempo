from __future__ import annotations

import collections.abc as c
import json
import time
import typing as t

from qgis.PyQt.QtCore import QCoreApplication

from qtempo.matrix import Matrix


def square(x: float, y: float, **properties: t.Any) -> dict[str, t.Any]:
    """A GeoJSON feature with a unit square at (x, y)."""
    ring = [[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1], [x, y]]
    return {
        'type': 'Feature',
        'properties': properties,
        'geometry': {'type': 'Polygon', 'coordinates': [ring]},
    }


def feature_collection(*features: dict[str, t.Any]) -> str:
    return json.dumps({'type': 'FeatureCollection', 'features': features})


def dimension(
    code: int, label: str, options: c.Sequence[str]
) -> dict[str, t.Any]:
    """A TEMPO dimension. The nomItemIds depend only on the code and the
    position, so the same options in two languages share them."""
    return {
        'dimCode': code,
        'label': label,
        'options': [
            {
                'label': option,
                'nomItemId': code * 1000 + offset,
                'offset': offset,
                'parentId': None,
            }
            for offset, option in enumerate(options, start=1)
        ],
    }


def leaf_node(*dimensions: dict[str, t.Any]) -> t.Any:
    return {'dimensionsMap': list(dimensions)}


def request_body(**flags: int) -> t.Any:
    return {
        'matTime': 0,
        'matRegJ': 0,
        'nomJud': 0,
        'nomLoc': 0,
        'matSiruta': 0,
    } | flags


def pivot(columns: c.Sequence[str], *rows: c.Sequence[str]) -> bytes:
    """A TEMPO pivot response."""
    lines = [', '.join(columns), *(', '.join(row) for row in rows)]
    return '\n'.join(lines).encode('UTF-8')


def wait_until(condition: c.Callable[[], object], timeout: float = 10) -> None:
    """Processes events until the condition holds."""
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError('The condition was not met in time')
        QCoreApplication.processEvents()
        time.sleep(0.01)


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


def by_sex() -> Matrix:
    sexes = dimension(1, 'Sexe', ['Masculin', 'Total'])
    response = pivot(
        ['Sexe', 'Judete', 'Ani', 'Valoare'],
        *(
            [sex, 'Cluj', year, '1']
            for sex in ('Masculin', 'Total')
            for year in ('Anul 1990', 'Anul 2000')
        ),
    )
    return Matrix.from_response(
        response,
        request_body(matTime=3),
        leaf_node(sexes, dimension(2, 'Judete', ['Cluj']), YEARS),
    )


def long_values() -> Matrix:
    """Agricultural area by county, with values longer than the dialog is
    wide."""
    values = [
        f'{name} {"foarte " * 40}lunga' for name in ('Agricola', 'Arabila')
    ]
    response = pivot(
        ['Categorii', 'Judete', 'Ani', 'Valoare'],
        *([value, 'Cluj', 'Anul 2000', '1'] for value in values),
    )
    return Matrix.from_response(
        response,
        request_body(matTime=3),
        leaf_node(
            dimension(1, 'Categorii', values),
            dimension(2, 'Judete', ['Cluj']),
            YEARS,
        ),
    )


def many_options(count: int = 7) -> Matrix:
    """A table of Cluj with count options of two values each, the years
    included. The names of the options wrap."""
    dimensions = [
        dimension(
            code,
            f'Dimensiunea {code} cu un nume lung din mai multe cuvinte',
            ['Prima', 'A doua'],
        )
        for code in range(10, 9 + count)
    ]
    response = pivot(
        [
            *(dimension['label'] for dimension in dimensions),
            'Judete',
            'Ani',
            'Valoare',
        ],
        *(
            [*[option] * (count - 1), 'Cluj', year, '1']
            for option, year in (
                ('Prima', 'Anul 1990'),
                ('A doua', 'Anul 2000'),
            )
        ),
    )
    return Matrix.from_response(
        response,
        request_body(matTime=count + 1),
        leaf_node(*dimensions, dimension(2, 'Judete', ['Cluj']), YEARS),
    )


def not_geographic() -> Matrix:
    response = pivot(
        ['Categorii', 'Ani', 'Valoare'],
        ['Agricola', 'Anul 2000', '1'],
    )
    return Matrix.from_response(
        response, request_body(matTime=2), leaf_node(CATEGORIES, YEARS)
    )
