def classFactory(iface):
    from .plugin import MapSearchProPlugin

    return MapSearchProPlugin(iface)
