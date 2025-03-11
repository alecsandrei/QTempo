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


class GISCO(Service):
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
        return 'LAU_ID'

    @property
    def url(self) -> str:
        return 'https://gisco-services.ec.europa.eu/distribution/v2/lau/'

    @property
    def is_default(self) -> bool:
        return True

    def request(self, url: str) -> bytes:
        network = QgsNetworkAccessManager()
        request = QNetworkRequest(QUrl(url))
        return network.blockingGet(request).content().data()

    def request_datasets(self) -> dict[str, GISCO_T.DatasetDetails]:
        return t.cast(
            dict[str, GISCO_T.DatasetDetails],
            json.loads(self.request(urljoin(self.url, 'datasets.json'))),
        )

    def request_dataset_files(
        self, details: GISCO_T.DatasetDetails
    ) -> GISCO_T.DatasetFiles:
        return t.cast(
            GISCO_T.DatasetFiles,
            json.loads(self.request(urljoin(self.url, details['files']))),
        )

    @cache
    def get_most_recent_dataset(self) -> str:
        datasets = self.request_datasets()

        def sort_by_date(details: GISCO_T.DatasetDetails):
            return datetime.datetime.strptime(details['date'], '%d/%m/%Y')

        details = sorted(datasets.values(), key=sort_by_date)[-1]
        files = self.request_dataset_files(details)
        dataset_geojson_files = files['geojson']
        # we select the last key of the files
        # this corresponds to the 4326 CRS dataset
        key = list(dataset_geojson_files)[-1]
        return self.request(
            urljoin(self.url, dataset_geojson_files[key])
        ).decode(encoding='UTF-8')

    def get_layer(self, siruta: list[SIRUTA]) -> QgsVectorLayer:
        siruta_codes = [value.code for value in siruta]

        def keep_feature(feature: QgsFeature) -> bool:
            return (
                feature.attribute(self.siruta_field) in siruta_codes
                and feature.attribute('CNTR_CODE') == 'RO'
            )

        geojson = self.get_most_recent_dataset()
        layer = QgsVectorLayer('MultiPolygon', self.short_name, 'memory')
        fields = QgsJsonUtils.stringToFields(geojson)
        if all(field_.name() != self.siruta_field for field_ in fields):
            raise ServiceError(
                f'Failed to fetch data from {self.short_name}. The SIRUTA field {self.siruta_field!r} was not found..'
            )
        features = QgsJsonUtils.stringToFeatureList(geojson, fields)
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
