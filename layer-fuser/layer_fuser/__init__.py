def classFactory(iface):
    from .layer_fuser_plugin import LayerFuserPlugin

    return LayerFuserPlugin(iface)
