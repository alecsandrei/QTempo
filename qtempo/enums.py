from __future__ import annotations

from enum import Enum, auto
from pathlib import Path
from urllib.parse import urljoin

from qgis.PyQt import QtCore

_PARENT_URL = 'http://statistici.insse.ro:8077/tempo-ins/'
_ASSETS_DIR = Path(__file__).parent.parent / 'assets'


class Asset(Enum):
    ICON = _ASSETS_DIR / 'icon.ico'
    DIALOG = _ASSETS_DIR / 'ui' / 'dialog.ui'


class URL(Enum):
    TABLE = urljoin(_PARENT_URL, 'pivot')
    DATASET = urljoin(_PARENT_URL, 'matrix/{code}/')
    TOC = urljoin(_PARENT_URL, 'context/')
    CONTEXT = urljoin(TOC, '{code}')


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
