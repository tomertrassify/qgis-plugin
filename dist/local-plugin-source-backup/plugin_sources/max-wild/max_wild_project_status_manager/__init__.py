def classFactory(iface):
    from .plugin import ProjectStatusManagerPlugin

    return ProjectStatusManagerPlugin(iface)
