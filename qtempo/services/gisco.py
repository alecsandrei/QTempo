from __future__ import annotations

import collections.abc as c
import datetime
import json
import typing as t
from functools import cache
from urllib.parse import urljoin

from qgis.core import (
    QgsFeature,
    QgsFields,
    QgsJsonUtils,
    QgsNetworkAccessManager,
)
from qgis.PyQt.QtCore import (
    QUrl,
)
from qgis.PyQt.QtNetwork import QNetworkRequest

from .._typing import GISCO as GISCO_T
from ..exceptions import ServiceError
from .abc import Service

if t.TYPE_CHECKING:
    from ..units import TerritorialUnit


def request(url: str) -> bytes:
    network = QgsNetworkAccessManager()
    request = QNetworkRequest(QUrl(url))
    return network.blockingGet(request).content().data()  # pyright: ignore[reportReturnType]


def request_datasets(url: str) -> dict[str, GISCO_T.DatasetDetails]:
    return t.cast(
        dict[str, GISCO_T.DatasetDetails],
        json.loads(request(urljoin(url, 'datasets.json'))),
    )


def request_dataset_files(
    url: str, details: GISCO_T.DatasetDetails
) -> GISCO_T.DatasetFiles:
    return t.cast(
        GISCO_T.DatasetFiles,
        json.loads(request(urljoin(url, details['files']))),
    )


@cache
def get_most_recent_dataset(url: str) -> str:
    datasets = request_datasets(url)

    def sort_by_date(details: GISCO_T.DatasetDetails):
        return datetime.datetime.strptime(details['date'], '%d/%m/%Y')

    details = sorted(datasets.values(), key=sort_by_date)[-1]
    files = request_dataset_files(url, details)
    dataset_geojson_files = files['geojson']
    # we select the last key of the files
    # this corresponds to the 4326 CRS dataset
    key = list(dataset_geojson_files)[-1]
    return request(urljoin(url, dataset_geojson_files[key])).decode(
        encoding='UTF-8'
    )


class GISCOService(Service):
    def process_siruta_value(self, siruta: str) -> str:
        return siruta

    def get_features(
        self, units: c.Collection[TerritorialUnit]
    ) -> tuple[QgsFields, list[QgsFeature]]:
        codes = {unit.code for unit in units}
        geojson = get_most_recent_dataset(self.url)
        fields = QgsJsonUtils.stringToFields(geojson)
        if self.siruta_field not in fields.names():
            raise ServiceError(
                f'Failed to fetch data from {self.short_name}. The SIRUTA field {self.siruta_field!r} was not found.'
            )
        features = QgsJsonUtils.stringToFeatureList(geojson, fields)
        if not features:
            raise ServiceError(
                f'Failed to fetch data from {self.short_name}. No features were returned. Try again later.'
            )
        kept = []
        for feature in features:
            if feature.attribute('CNTR_CODE') != 'RO':
                continue
            code = self.process_siruta_value(
                str(feature.attribute(self.siruta_field))
            )
            if code in codes:
                feature.setAttribute(self.siruta_field, code)
                kept.append(feature)
        return fields, kept


class GISCOLAU(GISCOService):
    @property
    def full_name(self) -> str:
        return (
            'Geographic Information System of the Commission (GISCO) - LAU data'
        )

    @property
    def short_name(self) -> str:
        return 'GISCO'

    @property
    def siruta_field(self) -> str:
        return 'GISCO_ID'

    @property
    def url(self) -> str:
        return 'https://gisco-services.ec.europa.eu/distribution/v2/lau/'

    @property
    def is_default(self) -> bool:
        return True

    def process_siruta_value(self, siruta: str) -> str:
        # Schema, as of 22 july 2025, is RO_98505
        return siruta.split('_')[-1]


class GISCOCommunes(GISCOService):
    @property
    def full_name(self) -> str:
        return (
            'Geographic Information System of the Commission (GISCO) - Communes'
        )

    @property
    def short_name(self) -> str:
        return 'GISCO'

    @property
    def siruta_field(self) -> str:
        return 'NSI_CODE'

    @property
    def url(self) -> str:
        return 'https://gisco-services.ec.europa.eu/distribution/v2/communes/'

    @property
    def is_default(self) -> bool:
        return False
