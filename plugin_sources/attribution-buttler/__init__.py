import sys
import types

from . import form_handler as _form_handler


def _register_legacy_module_alias():
    legacy_pkg = sys.modules.get("nextcloud_form_plugin")
    if legacy_pkg is None:
        legacy_pkg = types.ModuleType("nextcloud_form_plugin")
        legacy_pkg.__path__ = []
        sys.modules["nextcloud_form_plugin"] = legacy_pkg

    setattr(legacy_pkg, "form_handler", _form_handler)
    sys.modules["nextcloud_form_plugin.form_handler"] = _form_handler


_register_legacy_module_alias()


def classFactory(iface):
    from .plugin import NextcloudFormPlugin

    return NextcloudFormPlugin(iface)
