def classFactory(iface):
    from .custom_toolbar_manager import CustomToolbarManagerPlugin

    return CustomToolbarManagerPlugin(iface)
