def classFactory(iface):
    from .plugin import ProjectStarterPlugin

    return ProjectStarterPlugin(iface)
