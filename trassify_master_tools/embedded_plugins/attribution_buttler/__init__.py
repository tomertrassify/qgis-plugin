def classFactory(iface):
    from .plugin import NextcloudFormPlugin

    return NextcloudFormPlugin(iface)
