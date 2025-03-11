from __future__ import annotations

import typing as t
from abc import ABC, abstractmethod

if t.TYPE_CHECKING:
    from qgis.core import QgsVectorLayer

    from ..matrix import SIRUTA


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
    def get_layer(self, siruta: list[SIRUTA]) -> QgsVectorLayer: ...
