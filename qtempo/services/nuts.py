from __future__ import annotations

import collections.abc as c
import json
from collections import UserList
from dataclasses import dataclass
from functools import partial

from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsFeedback,
    QgsFields,
    QgsJsonUtils,
    QgsNetworkAccessManager,
    QgsTask,
)
from qgis.PyQt.QtCore import QObject, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import QTableWidget

from ..enums import NutsURL
from ..exceptions import ServiceError
from ..utils import color_row, get_table_item

COUNTRY_CODE = 'RO'
SPATIAL_TYPE = 'region'
DEFAULT_SCALE = '03m'
DEFAULT_PROJECTION = '4326'

# The index is fetched once per session
CACHED_YEARS: list[str] = []
CACHED_UNITS: dict[str, Units] = {}


def request(url: str, feedback: QgsFeedback | None = None) -> bytes:
    """A blocking GET request, which can be used inside a QgsTask."""
    reply = QgsNetworkAccessManager.blockingGet(
        QNetworkRequest(QUrl(url)), feedback=feedback
    )
    if reply.error() != QNetworkReply.NetworkError.NoError:
        raise ServiceError(f'{reply.errorString()} ({url})')
    return reply.content().data()  # pyright: ignore[reportReturnType]


@dataclass(frozen=True, eq=True)
class Unit:
    """A GISCO NUTS file, e.g. RO111-region-03m-4326-2024.geojson."""

    id: str
    spatial_type: str
    scale: str | None
    projection: str
    year: str

    @classmethod
    def from_filename(cls, filename: str) -> Unit:
        id_, spatial_type, *rest = filename.removesuffix('.geojson').split('-')
        if spatial_type == 'label':
            # Label points have no scale, e.g. RO111-label-4326-2024.geojson
            projection, year = rest
            return cls(id_, spatial_type, None, projection, year)
        scale, projection, year = rest
        return cls(id_, spatial_type, scale, projection, year)

    def to_filename(self) -> str:
        parts = (
            self.id,
            self.spatial_type,
            self.scale,
            self.projection,
            self.year,
        )
        return '-'.join(part for part in parts if part is not None) + '.geojson'

    @property
    def url(self) -> str:
        return NutsURL.UNIT.value.format(filename=self.to_filename())


class Units(UserList[Unit]):
    @classmethod
    def from_json(
        cls,
        index: c.Mapping[str, c.Iterable[str]],
        country: str = COUNTRY_CODE,
    ) -> Units:
        units = cls()
        for nuts_id, filenames in index.items():
            if nuts_id[:2] != country:
                continue
            for filename in filenames:
                try:
                    units.append(Unit.from_filename(filename))
                except ValueError:
                    continue
        return units

    def filter(self, **filters: c.Collection[str | None]) -> Units:
        return Units(
            unit
            for unit in self
            if all(
                getattr(unit, name) in values
                for name, values in filters.items()
            )
        )

    def values(self, name: str) -> list[str]:
        return sorted(
            {
                getattr(unit, name)
                for unit in self
                if getattr(unit, name) is not None
            }
        )


def get_years(feedback: QgsFeedback | None = None) -> list[str]:
    """The NUTS years with a units index, newest first."""
    if not CACHED_YEARS:
        datasets = json.loads(request(NutsURL.DATASETS.value, feedback))
        CACHED_YEARS[:] = sorted(
            (
                name.removeprefix('nuts-')
                for name, details in datasets.items()
                if 'units' in details
            ),
            reverse=True,
        )
    return CACHED_YEARS


def get_units(year: str, feedback: QgsFeedback | None = None) -> Units:
    """The Romanian units of a NUTS year."""
    if year not in CACHED_UNITS:
        index = json.loads(
            request(NutsURL.UNITS.value.format(year=year), feedback)
        )
        CACHED_UNITS[year] = Units.from_json(index)
    return CACHED_UNITS[year]


class FetchNutsIndexTask(QgsTask):
    """Fetches the NUTS years and the units of a year (by default the
    latest one)."""

    def __init__(self, year: str | None = None):
        super().__init__(
            'Fetching the GISCO NUTS index', QgsTask.Flag.CanCancel
        )
        self.year = year
        self.years: list[str] = []
        self.units = Units()
        self.exception: Exception | None = None
        self.feedback = QgsFeedback()

    def run(self) -> bool:
        try:
            self.years = get_years(self.feedback)
            if self.year is None:
                self.year = self.years[0]
            self.units = get_units(self.year, self.feedback)
        except Exception as e:
            self.exception = e
            return False
        return not self.isCanceled()

    def cancel(self) -> None:
        self.feedback.cancel()
        super().cancel()


class FetchUnitTask(QgsTask):
    """Fetches the boundary of a unit.

    Errors are stored in self.error instead of failing the task, so that
    the downloads of the other units continue.
    """

    def __init__(self, unit: Unit):
        super().__init__(
            f'Fetching {unit.to_filename()}', QgsTask.Flag.CanCancel
        )
        self.unit = unit
        self.fields = QgsFields()
        self.features: list[QgsFeature] = []
        self.error: str | None = None
        self.feedback = QgsFeedback()

    def run(self) -> bool:
        try:
            geojson = request(self.unit.url, self.feedback).decode('UTF-8')
            self.fields = QgsJsonUtils.stringToFields(geojson)
            self.features = QgsJsonUtils.stringToFeatureList(
                geojson, self.fields
            )
            if not self.features:
                raise ServiceError(f'No features in {self.unit.url}')
        except Exception as e:
            self.error = str(e)
        return not self.isCanceled()

    def cancel(self) -> None:
        self.feedback.cancel()
        super().cancel()


@dataclass
class Boundaries:
    fields: QgsFields
    features: list[QgsFeature]
    errors: dict[str, str]


class BoundaryDownloader(QObject):
    """Downloads the boundaries of units in parallel, with one task per
    unit, and shows the progress of each download in a table."""

    finished = pyqtSignal(object)
    HEADERS = ['ID', 'URL', 'Error']

    def __init__(
        self,
        units: c.Iterable[Unit],
        table: QTableWidget,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.units = list(units)
        self.table = table
        self.tasks: list[FetchUnitTask] = []
        self.done: set[int] = set()
        self.boundaries = Boundaries(QgsFields(), [], {})
        self.cancelled = False

    @property
    def is_running(self) -> bool:
        return not self.cancelled and len(self.done) < len(self.tasks)

    def start(self) -> None:
        self.table.clear()
        self.table.setColumnCount(len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setRowCount(len(self.units))
        manager = QgsApplication.taskManager()
        assert manager is not None
        for row, unit in enumerate(self.units):
            get_table_item(self.table, row, 0).setText(unit.id)
            get_table_item(self.table, row, 1).setText(unit.url)
            task = FetchUnitTask(unit)
            # Both signals are emitted from the main thread
            task.taskCompleted.connect(partial(self.handle_task, row))
            task.taskTerminated.connect(partial(self.handle_task, row))
            self.tasks.append(task)
            manager.addTask(task)
        self.table.resizeColumnsToContents()
        if not self.units:
            self.finished.emit(self.boundaries)

    def handle_task(self, row: int) -> None:
        if self.cancelled or row in self.done:
            return
        self.done.add(row)
        task = self.tasks[row]
        error = task.error
        if error is None and task.status() != QgsTask.TaskStatus.Complete:
            error = 'Cancelled'
        if error is None:
            if not self.boundaries.fields.count():
                self.boundaries.fields = task.fields
            self.boundaries.features.extend(task.features)
        else:
            self.boundaries.errors[task.unit.id] = error
        # The table is cleared when the data changes, while the download
        # carries on
        if row < self.table.rowCount():
            self.update_row(row, error)
        if len(self.done) == len(self.tasks):
            self.table.resizeColumnsToContents()
            self.finished.emit(self.boundaries)

    def update_row(self, row: int, error: str | None) -> None:
        if error is None:
            color = QColor('green')
        else:
            get_table_item(self.table, row, 2).setText(error)
            color = QColor('red')
        color.setAlpha(50)
        color_row(self.table, row, color)

    def cancel(self) -> None:
        self.cancelled = True
        for row, task in enumerate(self.tasks):
            if row not in self.done:
                task.cancel()
