# -*- coding: utf-8 -*-


def classFactory(iface):
    from .verpacken_pro import ExportProPlugin

    return ExportProPlugin(iface)
