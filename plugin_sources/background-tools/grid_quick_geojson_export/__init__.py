def classFactory(iface):
    from .plugin import GridQuickGeoJsonExportPlugin

    return GridQuickGeoJsonExportPlugin(iface)
