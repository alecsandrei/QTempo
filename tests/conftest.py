from __future__ import annotations

import collections.abc as c

import pytest
from qgis.core import QgsSettings

from qtempo.enums import Setting


@pytest.fixture(autouse=True)
def english() -> c.Iterator[None]:
    """Opens the dialogs in English, whatever the locale or the language
    saved by an earlier run."""
    settings = QgsSettings()
    settings.setValue(Setting.LANGUAGE.value, 'en')
    yield
    settings.remove(Setting.LANGUAGE.value)


@pytest.fixture(autouse=True)
def default_layout() -> c.Iterator[None]:
    """Opens the dialogs with the default size and splitters, which closing
    a dialog saves."""
    layout = (
        Setting.GEOMETRY,
        Setting.CATALOGUE_SPLITTER,
        Setting.MATRIX_SPLITTER,
    )
    settings = QgsSettings()
    for setting in layout:
        settings.remove(setting.value)
    yield
    for setting in layout:
        settings.remove(setting.value)
