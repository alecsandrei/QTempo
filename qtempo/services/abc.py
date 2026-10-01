from __future__ import annotations

import collections.abc as c
import typing as t
from abc import ABC, abstractmethod

if t.TYPE_CHECKING:
    from qgis.core import QgsFeature, QgsFields

    from ..units import TerritorialUnit


class Service(ABC):
    @property
    @abstractmethod
    def full_name(self) -> str: ...

    @property
    @abstractmethod
    def short_name(self) -> str: ...

    @property
    @abstractmethod
    def url(self) -> str: ...

    @property
    @abstractmethod
    def siruta_field(self) -> str: ...

    @property
    @abstractmethod
    def is_default(self) -> bool: ...

    @abstractmethod
    def get_features(
        self, units: c.Collection[TerritorialUnit]
    ) -> tuple[QgsFields, list[QgsFeature]]:
        """Returns the boundaries of the units, with the SIRUTA code in
        siruta_field. Runs inside a QgsTask, so it must not create layers."""
