def classFactory(iface):
    from .plugin import CoordinatifyPlugin

    return CoordinatifyPlugin(iface)
