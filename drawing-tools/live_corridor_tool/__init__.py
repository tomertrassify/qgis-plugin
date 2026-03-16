# -*- coding: utf-8 -*-


def classFactory(iface):
    from .plugin import LiveCorridorPlugin

    return LiveCorridorPlugin(iface)
