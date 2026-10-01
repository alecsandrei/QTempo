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
