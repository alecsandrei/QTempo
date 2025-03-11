from __future__ import annotations

from .qtempo.qtempo import QTempo


def classFactory(iface):
    return QTempo(iface)
