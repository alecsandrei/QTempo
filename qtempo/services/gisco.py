from __future__ import annotations

import datetime
import json
import typing as t
from functools import cache
from urllib.parse import urljoin

from qgis.core import (
    QgsFeature,
    QgsJsonUtils,
    QgsNetworkAccessManager,
    QgsVectorLayer,
    edit,
)
from qgis.PyQt.QtCore import (
    QUrl,
)
from qgis.PyQt.QtNetwork import QNetworkRequest

from .._typing import GISCO as GISCO_T
from ..exceptions import ServiceError
from .abc import Service

if t.TYPE_CHECKING:
    from ..matrix import SIRUTA


def request(url: str) -> bytes:
    network = QgsNetworkAccessManager()
    request = QNetworkRequest(QUrl(url))
    return network.blockingGet(request).content().data()


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


class GISCOLAU(Service):
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

    def get_layer(self, siruta: list[SIRUTA]) -> QgsVectorLayer:
        siruta_codes = [value.code for value in siruta]

        def keep_feature(feature: QgsFeature) -> bool:
            return (
                feature.attribute(self.siruta_field) in siruta_codes
                and feature.attribute('CNTR_CODE') == 'RO'
            )

        geojson = get_most_recent_dataset(self.url)
        layer = QgsVectorLayer('MultiPolygon', self.short_name, 'memory')
        fields = QgsJsonUtils.stringToFields(geojson)
        if all(field_.name() != self.siruta_field for field_ in fields):
            raise ServiceError(
                f'Failed to fetch data from {self.short_name}. The SIRUTA field {self.siruta_field!r} was not found.'
            )
        features = QgsJsonUtils.stringToFeatureList(geojson, fields)
        for feature in features:
            feature.setAttribute(
                self.siruta_field,
                self.process_siruta_value(feature.attribute(self.siruta_field)),
            )
        if not features:
            raise ServiceError(
                f'Failed to fetch data from {self.short_name}. No features were returned. Try again later.'
            )
        provider = layer.dataProvider()
        assert provider is not None
        provider.addAttributes(fields)
        layer.updateFields()
        with edit(layer):
            layer.addFeatures(filter(keep_feature, features))
        return layer


class GISCOCommunes(Service):
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

    def get_layer(self, siruta: list[SIRUTA]) -> QgsVectorLayer:
        siruta_codes = [value.code for value in siruta]

        def keep_feature(feature: QgsFeature) -> bool:
            return (
                feature.attribute(self.siruta_field) in siruta_codes
                and feature.attribute('CNTR_CODE') == 'RO'
            )

        geojson = get_most_recent_dataset(self.url)
        layer = QgsVectorLayer('MultiPolygon', self.short_name, 'memory')
        fields = QgsJsonUtils.stringToFields(geojson)
        if all(field_.name() != self.siruta_field for field_ in fields):
            raise ServiceError(
                f'Failed to fetch data from {self.short_name}. The SIRUTA field {self.siruta_field!r} was not found.'
            )
        features = QgsJsonUtils.stringToFeatureList(geojson, fields)
        for feature in features:
            feature.setAttribute(
                self.siruta_field,
                feature.attribute(self.siruta_field),
            )
        if not features:
            raise ServiceError(
                f'Failed to fetch data from {self.short_name}. No features were returned. Try again later.'
            )
        provider = layer.dataProvider()
        assert provider is not None
        provider.addAttributes(fields)
        layer.updateFields()
        with edit(layer):
            layer.addFeatures(filter(keep_feature, features))
        return layer
