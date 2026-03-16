def classFactory(iface):
    from .quickrule_plugin import QuickrulePlugin

    return QuickrulePlugin(iface)
