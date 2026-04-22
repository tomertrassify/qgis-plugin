def classFactory(iface):
    from .webmap_export_plugin import WebmapExportPlugin

    return WebmapExportPlugin(iface)
