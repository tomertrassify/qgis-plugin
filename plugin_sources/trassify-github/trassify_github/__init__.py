def classFactory(iface):
    from .trassify_github_plugin import TrassifyGithubPlugin

    return TrassifyGithubPlugin(iface)
