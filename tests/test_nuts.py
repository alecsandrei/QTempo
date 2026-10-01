from __future__ import annotations

import json

import pytest
from qgis.core import QgsFeedback, QgsTask
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QTableWidget

from qtempo.enums import NutsURL
from qtempo.exceptions import ServiceError
from qtempo.services import nuts

from .helpers import feature_collection, square, wait_until

INDEX = {
    'RO111': [
        'RO111-region-03m-4326-2024.geojson',
        'RO111-region-60m-3035-2024.geojson',
        'RO111-label-4326-2024.geojson',
    ],
    'RO112': ['RO112-region-03m-4326-2024.geojson'],
    'RO113': ['RO113-region.geojson'],
    'BG311': ['BG311-region-03m-4326-2024.geojson'],
}
DATASETS = {
    'nuts-2021': {'units': 'nuts-2021-units.json'},
    'nuts-2024': {'units': 'nuts-2024-units.json'},
    'nuts-2003': {'files': 'nuts-2003-files.json'},
}


class Server:
    """Serves the GISCO files instead of the network."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.requested: list[str] = []

    def request(self, url: str, feedback: QgsFeedback | None = None) -> bytes:
        self.requested.append(url)
        if url not in self.files:
            raise ServiceError(f'Not found ({url})')
        return self.files[url]

    def add_unit(self, unit: nuts.Unit) -> None:
        self.files[unit.url] = feature_collection(
            square(0, 0, NUTS_ID=unit.id, LEVL_CODE=len(unit.id) - 2)
        ).encode()


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Server:
    server = Server()
    server.files[NutsURL.DATASETS.value] = json.dumps(DATASETS).encode()
    server.files[NutsURL.UNITS.value.format(year='2024')] = json.dumps(
        INDEX
    ).encode()
    monkeypatch.setattr(nuts, 'request', server.request)
    monkeypatch.setattr(nuts, 'CACHED_YEARS', [])
    monkeypatch.setattr(nuts, 'CACHED_UNITS', {})
    return server


def region(nuts_id: str) -> nuts.Unit:
    return nuts.Unit(nuts_id, 'region', '03m', '4326', '2024')


def test_unit_from_filename() -> None:
    filename = 'RO111-region-03m-4326-2024.geojson'
    unit = nuts.Unit.from_filename(filename)
    assert unit == region('RO111')
    assert unit.to_filename() == filename
    assert unit.url == (
        'https://gisco-services.ec.europa.eu/distribution/v2/nuts/'
        'distribution/RO111-region-03m-4326-2024.geojson'
    )


def test_label_unit_has_no_scale() -> None:
    filename = 'RO111-label-4326-2024.geojson'
    unit = nuts.Unit.from_filename(filename)
    assert unit == nuts.Unit('RO111', 'label', None, '4326', '2024')
    assert unit.to_filename() == filename


def test_units_from_json() -> None:
    units = nuts.Units.from_json(INDEX)
    assert [unit.to_filename() for unit in units] == [
        *INDEX['RO111'],
        *INDEX['RO112'],
    ]
    regions = units.filter(spatial_type=['region'], scale=['03m'])
    assert [unit.id for unit in regions] == ['RO111', 'RO112']
    assert units.values('scale') == ['03m', '60m']
    assert units.values('projection') == ['3035', '4326']


def test_get_years(server: Server) -> None:
    assert nuts.get_years() == ['2024', '2021']
    assert nuts.get_years() == ['2024', '2021']
    assert server.requested == [NutsURL.DATASETS.value]


def test_get_units(server: Server) -> None:
    assert nuts.get_units('2024') == nuts.Units.from_json(INDEX)
    assert nuts.get_units('2024') is nuts.CACHED_UNITS['2024']
    assert len(server.requested) == 1


def test_fetch_index_task_uses_the_latest_year(server: Server) -> None:
    task = nuts.FetchNutsIndexTask()
    assert task.run()
    assert task.year == '2024'
    assert task.years == ['2024', '2021']
    assert task.units == nuts.Units.from_json(INDEX)


def test_fetch_index_task_stores_the_error(server: Server) -> None:
    server.files.clear()
    task = nuts.FetchNutsIndexTask()
    assert not task.run()
    assert isinstance(task.exception, ServiceError)


def test_fetch_unit_task(server: Server) -> None:
    server.add_unit(region('RO111'))
    task = nuts.FetchUnitTask(region('RO111'))
    assert task.run()
    assert task.error is None
    assert 'NUTS_ID' in task.fields.names()
    assert [feature['NUTS_ID'] for feature in task.features] == ['RO111']


def test_fetch_unit_task_without_features(server: Server) -> None:
    server.files[region('RO111').url] = feature_collection().encode()
    task = nuts.FetchUnitTask(region('RO111'))
    assert task.run()
    assert task.error is not None
    assert task.error.startswith('No features')


def test_fetch_unit_task_stores_the_error(server: Server) -> None:
    task = nuts.FetchUnitTask(region('RO111'))
    assert task.run()
    assert task.error is not None
    assert task.error.startswith('Not found')


def test_boundary_downloader(server: Server) -> None:
    units = [region('RO111'), region('RO112'), region('RO113')]
    server.add_unit(units[0])
    server.add_unit(units[1])
    table = QTableWidget()
    downloader = nuts.BoundaryDownloader(units, table)
    received: list[nuts.Boundaries] = []
    downloader.finished.connect(received.append)
    downloader.start()
    # The URLs are readable while the download runs
    assert table.columnWidth(1) >= table.sizeHintForColumn(1)
    wait_until(lambda: received)

    [boundaries] = received
    assert sorted(feature['NUTS_ID'] for feature in boundaries.features) == [
        'RO111',
        'RO112',
    ]
    assert 'NUTS_ID' in boundaries.fields.names()
    assert list(boundaries.errors) == ['RO113']
    assert not downloader.is_running
    assert [table.item(row, 0).text() for row in range(3)] == [
        'RO111',
        'RO112',
        'RO113',
    ]
    assert table.item(2, 1).text() == units[2].url
    assert [table.item(row, 2).text() for row in range(3)] == [
        '',
        '',
        boundaries.errors['RO113'],
    ]


def test_boundary_downloader_without_units(server: Server) -> None:
    downloader = nuts.BoundaryDownloader([], QTableWidget())
    received: list[nuts.Boundaries] = []
    downloader.finished.connect(received.append)
    downloader.start()
    assert len(received) == 1
    assert received[0].features == []
    assert server.requested == []


def test_cancelled_boundary_downloader(server: Server) -> None:
    units = [region('RO111'), region('RO112')]
    for unit in units:
        server.add_unit(unit)
    downloader = nuts.BoundaryDownloader(units, QTableWidget())
    received: list[nuts.Boundaries] = []
    downloader.finished.connect(received.append)
    downloader.start()
    downloader.cancel()
    finished = {QgsTask.TaskStatus.Complete, QgsTask.TaskStatus.Terminated}
    wait_until(
        lambda: all(task.status() in finished for task in downloader.tasks)
    )
    QCoreApplication.processEvents()
    assert received == []
    assert not downloader.is_running
