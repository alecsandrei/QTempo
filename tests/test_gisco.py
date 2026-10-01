from __future__ import annotations

import pytest

from qtempo.enums import Level
from qtempo.exceptions import ServiceError
from qtempo.services import GISCOLAU, GISCOCommunes, gisco
from qtempo.units import TerritorialUnit

from .helpers import feature_collection, square

UNITS = [TerritorialUnit(Level.LOCALITY, '1017', '1017 Municipiul Alba Iulia')]


def serve(monkeypatch: pytest.MonkeyPatch, geojson: str) -> None:
    monkeypatch.setattr(gisco, 'get_most_recent_dataset', lambda url: geojson)


def test_lau_keeps_the_requested_romanian_localities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(
        monkeypatch,
        feature_collection(
            square(0, 0, GISCO_ID='RO_1017', CNTR_CODE='RO'),
            square(1, 0, GISCO_ID='RO_179132', CNTR_CODE='RO'),
            square(2, 0, GISCO_ID='BG_1017', CNTR_CODE='BG'),
        ),
    )
    fields, features = GISCOLAU().get_features(UNITS)
    assert 'GISCO_ID' in fields.names()
    assert [feature['GISCO_ID'] for feature in features] == ['1017']


def test_communes_match_the_nsi_code(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(
        monkeypatch,
        feature_collection(
            square(0, 0, NSI_CODE='1017', CNTR_CODE='RO'),
            square(1, 0, NSI_CODE='179132', CNTR_CODE='RO'),
        ),
    )
    fields, features = GISCOCommunes().get_features(UNITS)
    assert [feature['NSI_CODE'] for feature in features] == ['1017']


@pytest.mark.parametrize(
    'geojson',
    [
        feature_collection(square(0, 0, LAU_ID='1017', CNTR_CODE='RO')),
        feature_collection(),
    ],
)
def test_lau_errors(monkeypatch: pytest.MonkeyPatch, geojson: str) -> None:
    serve(monkeypatch, geojson)
    with pytest.raises(ServiceError):
        GISCOLAU().get_features(UNITS)
