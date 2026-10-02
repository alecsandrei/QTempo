from __future__ import annotations

from enum import Enum, auto
from pathlib import Path
from urllib.parse import urljoin

from qgis.PyQt import QtCore

_PARENT_URL = 'http://statistici.insse.ro:8077/tempo-ins/'
_ASSETS_DIR = Path(__file__).parent / 'assets'
GISCO_NUTS_URL = 'https://gisco-services.ec.europa.eu/distribution/v2/nuts/'


class Asset(Enum):
    ICON = _ASSETS_DIR / 'icon.ico'
    DIALOG = _ASSETS_DIR / 'ui' / 'dialog.ui'
    I18N = Path(__file__).parent / 'i18n'


class Setting(Enum):
    LANGUAGE = 'QTempo/language'
    GEOMETRY = 'QTempo/geometry'
    CATALOGUE_SPLITTER = 'QTempo/catalogueSplitter'
    MATRIX_SPLITTER = 'QTempo/matrixSplitter'


class URL(Enum):
    TABLE = urljoin(_PARENT_URL, 'pivot')
    DATASET = urljoin(_PARENT_URL, 'matrix/{code}/')
    TOC = urljoin(_PARENT_URL, 'context/')
    CONTEXT = urljoin(TOC, '{code}')


class NutsURL(Enum):
    DATASETS = urljoin(GISCO_NUTS_URL, 'datasets.json')
    UNITS = urljoin(GISCO_NUTS_URL, 'nuts-{year}-units.json')
    UNIT = urljoin(GISCO_NUTS_URL, 'distribution/{filename}')


class EnumZero(Enum):
    """An enum which generates values starting from 0 instead of 1 (default)."""

    @staticmethod
    def _generate_next_value_(name, start, count, last_values):
        if not last_values:
            return 0
        return last_values[-1] + 1


class Tabs(EnumZero):
    # TODO: Add test to make sure these are updated as in .ui file
    QUERY = auto()
    TABLE = auto()
    MAP = auto()


class Level(Enum):
    COUNTRY = 0
    MACROREGION = 1
    REGION = 2
    COUNTY = 3
    LOCALITY = 4

    @property
    def label(self) -> str:
        return {
            Level.COUNTRY: QtCore.QCoreApplication.translate(
                'Level', 'Country'
            ),
            Level.MACROREGION: QtCore.QCoreApplication.translate(
                'Level', 'Macroregions'
            ),
            Level.REGION: QtCore.QCoreApplication.translate('Level', 'Regions'),
            Level.COUNTY: QtCore.QCoreApplication.translate(
                'Level', 'Counties'
            ),
            Level.LOCALITY: QtCore.QCoreApplication.translate(
                'Level', 'Localities'
            ),
        }[self]

    @property
    def is_nuts(self) -> bool:
        return self is not Level.LOCALITY

    @classmethod
    def from_nuts_id(cls, nuts_id: str) -> Level:
        # RO is the country, RO1 a macroregion, RO11 a region, RO111 a county
        return cls(len(nuts_id) - 2)


class WidgetProperty(Enum):
    FIELD = 'field'
    DIMENSION = 'dimension'


class UserRole(Enum):
    @staticmethod
    def _generate_next_value_(name, start, count, last_values):
        if not last_values:
            return start + QtCore.Qt.ItemDataRole.UserRole
        return last_values[-1] + QtCore.Qt.ItemDataRole.UserRole


class QTreeWidgetItemRole(UserRole):
    NODE = auto()


class QListWidgetItemRole(UserRole):
    CONTEXT = auto()
    CHOICE = auto()
    SERVICE = auto()
    LEAF_NODE = auto()
    MATRIX = auto()
    PARENT_NODE = auto()
    LEAF_NODE_RO = auto()
    QUERY_SIGNATURE = auto()
