from __future__ import annotations

import collections.abc as c
import typing as t
from urllib.parse import urlencode

from qgis.core import (
    QgsJsonUtils,
    QgsNetworkAccessManager,
    QgsVectorLayer,
    edit,
)
from qgis.PyQt.QtCore import (
    QUrl,
)
from qgis.PyQt.QtNetwork import QNetworkRequest

from ..exceptions import ServiceError
from .abc import Service

if t.TYPE_CHECKING:
    from qgis.core import QgsNetworkReplyContent

    from ..matrix import SIRUTA


class ANCPI(Service):
    @property
    def full_name(self) -> str:
        return 'Agenția Națională de Cadastru și Publicitate Imobiliară (ANCPI)'

    @property
    def short_name(self) -> str:
        return 'ANCPI'

    @property
    def siruta_field(self) -> str:
        return 'natCode'

    @property
    def url(self) -> str:
        return 'https://geoportal.ancpi.ro/maps/rest/services/Administrativ/Administrativ_download/MapServer/5/query'

    @property
    def is_default(self) -> bool:
        return False

    def handle_reply(self, reply: QgsNetworkReplyContent) -> QgsVectorLayer:
        geojson = reply.content().data().decode(encoding='UTF-8')
        layer = QgsVectorLayer('MultiPolygon', self.short_name, 'memory')
        fields = QgsJsonUtils.stringToFields(geojson)
        features = QgsJsonUtils.stringToFeatureList(geojson, fields)
        if not features:
            raise ServiceError(
                f'Failed to fetch data from {self.short_name}. No features were returned. Try again later.'
            )
        if all(field_.name() != self.siruta_field for field_ in fields):
            raise ServiceError(
                f'Failed to fetch data from {self.short_name}. The SIRUTA field {self.siruta_field!r} was not found.'
            )
        provider = layer.dataProvider()
        assert provider is not None
        provider.addAttributes(fields)
        layer.updateFields()
        with edit(layer):
            layer.addFeatures(features)
        return layer

    def get_layer(self, siruta: list[SIRUTA]) -> QgsVectorLayer:
        return self.handle_reply(
            self.request_data(self.construct_request_data(siruta))
        )

    def construct_request_data(self, siruta: c.Sequence[SIRUTA]) -> bytes:
        if len(siruta) == 1:
            where = f"{self.siruta_field} = '{siruta[0].code}'"
        else:
            where = f'{self.siruta_field} in {tuple(value.code for value in siruta)}'
        return urlencode(
            {
                'f': 'geojson',
                'where': where,
                'outFields': f'{self.siruta_field},name',
            }
        ).encode(encoding='UTF-8')

    def request_data(self, data: bytes) -> QgsNetworkReplyContent:
        request = QNetworkRequest(QUrl(self.url))
        request.setHeader(
            QNetworkRequest.KnownHeaders.ContentTypeHeader,
            'application/x-www-form-urlencoded',
        )
        manager = QgsNetworkAccessManager()
        return manager.blockingPost(request, data=data)
