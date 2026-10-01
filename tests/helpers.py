from __future__ import annotations

import collections.abc as c
import json
import time
import typing as t

from qgis.PyQt.QtCore import QCoreApplication


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
