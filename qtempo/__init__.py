from __future__ import annotations

from .qtempo import QTempo


def classFactory(iface):
    return QTempo(iface)
