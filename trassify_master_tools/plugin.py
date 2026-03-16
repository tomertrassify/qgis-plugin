from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import Qgis, QgsMessageLog

from .manifest import EMBEDDED_PLUGINS


class TrassifyMasterToolsPlugin:
    MENU_TITLE = "Trassify Master Tools"
    STATUS_ACTION_TEXT = "Modulstatus anzeigen"
    LOG_TAG = "Trassify Master Tools"

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = Path(__file__).resolve().parent
        self.embedded_root = self.plugin_dir / "embedded_plugins"
        self.status_action = None
        self.loaded_plugins = []
        self.load_errors = []
        self._embedded_root_str = str(self.embedded_root)
        self._registry_keys = []
        self._path_added = False

    def initGui(self):
        self._ensure_embedded_import_path()

        self.status_action = QAction(
            QIcon(str(self.plugin_dir / "icon.svg")),
            self.STATUS_ACTION_TEXT,
            self.iface.mainWindow(),
        )
        self.status_action.triggered.connect(self.show_status)
        self.iface.addPluginToMenu(self.MENU_TITLE, self.status_action)

        self._load_embedded_plugins()

        if self.load_errors:
            summary = (
                f"{len(self.load_errors)} von {len(EMBEDDED_PLUGINS)} Modulen "
                "konnten nicht geladen werden."
            )
            self.iface.messageBar().pushMessage(
                self.MENU_TITLE,
                summary,
                level=Qgis.Warning,
                duration=8,
            )
        else:
            self.iface.messageBar().pushMessage(
                self.MENU_TITLE,
                f"{len(self.loaded_plugins)} Module geladen.",
                level=Qgis.Info,
                duration=4,
            )

    def unload(self):
        for spec, plugin in reversed(self.loaded_plugins):
            try:
                plugin.unload()
            except Exception:
                self._log_exception(spec["label"], "Fehler beim Entladen")

        self.loaded_plugins.clear()
        self.load_errors.clear()
        self._unregister_embedded_plugins()

        if self.status_action is not None:
            self.iface.removePluginMenu(self.MENU_TITLE, self.status_action)
            self.status_action.deleteLater()
            self.status_action = None

        self._cleanup_embedded_modules()

        if self._path_added and self._embedded_root_str in sys.path:
            sys.path.remove(self._embedded_root_str)
            self._path_added = False

    def show_status(self):
        lines = [
            f"Geladen: {len(self.loaded_plugins)}/{len(EMBEDDED_PLUGINS)}",
            "",
        ]

        if self.loaded_plugins:
            lines.append("Aktive Module:")
            for spec, _plugin in self.loaded_plugins:
                lines.append(f"- {spec['label']}")
            lines.append("")

        if self.load_errors:
            lines.append("Fehler:")
            for spec, message in self.load_errors:
                lines.append(f"- {spec['label']}: {message}")

        QMessageBox.information(
            self.iface.mainWindow(),
            self.MENU_TITLE,
            "\n".join(lines).strip(),
        )

    def _ensure_embedded_import_path(self):
        if self._embedded_root_str not in sys.path:
            sys.path.insert(0, self._embedded_root_str)
            self._path_added = True

    def _load_embedded_plugins(self):
        for spec in EMBEDDED_PLUGINS:
            plugin = None

            try:
                module = importlib.import_module(spec["package"])
                factory = getattr(module, "classFactory", None)
                if factory is None:
                    raise AttributeError(
                        f"classFactory fehlt in Paket '{spec['package']}'"
                    )

                plugin = factory(self.iface)
                self._register_embedded_plugin(spec["package"], plugin)
                plugin.initGui()
                self.loaded_plugins.append((spec, plugin))
            except Exception:
                if plugin is not None:
                    try:
                        plugin.unload()
                    except Exception:
                        pass

                self._unregister_embedded_plugin(spec["package"])
                self._log_exception(spec["label"], "Fehler beim Laden")
                self.load_errors.append((spec, self._short_exception_message()))

    def _register_embedded_plugin(self, package_name, plugin):
        try:
            import qgis.utils as qgis_utils
        except Exception:
            return

        registry = getattr(qgis_utils, "plugins", None)
        if not isinstance(registry, dict):
            return

        registry_key = f"embedded:{package_name}"
        registry[registry_key] = plugin
        self._registry_keys.append(registry_key)

    def _unregister_embedded_plugin(self, package_name):
        registry_key = f"embedded:{package_name}"
        try:
            import qgis.utils as qgis_utils
        except Exception:
            return

        registry = getattr(qgis_utils, "plugins", None)
        if isinstance(registry, dict):
            registry.pop(registry_key, None)

        if registry_key in self._registry_keys:
            self._registry_keys.remove(registry_key)

    def _unregister_embedded_plugins(self):
        try:
            import qgis.utils as qgis_utils
        except Exception:
            self._registry_keys.clear()
            return

        registry = getattr(qgis_utils, "plugins", None)
        if isinstance(registry, dict):
            for key in self._registry_keys:
                registry.pop(key, None)

        self._registry_keys.clear()

    def _cleanup_embedded_modules(self):
        for module_name, module in list(sys.modules.items()):
            module_file = getattr(module, "__file__", None)
            if not module_file:
                continue

            try:
                module_path = Path(module_file).resolve()
            except OSError:
                continue

            if self._is_within_embedded_root(module_path):
                del sys.modules[module_name]

    def _is_within_embedded_root(self, path):
        try:
            path.relative_to(self.embedded_root)
            return True
        except ValueError:
            return False

    def _log_exception(self, label, prefix):
        message = traceback.format_exc().rstrip()
        QgsMessageLog.logMessage(
            f"{prefix}: {label}\n{message}",
            self.LOG_TAG,
            Qgis.Critical,
        )

    def _short_exception_message(self):
        exc_type, exc_value, _tb = sys.exc_info()
        if exc_type is None:
            return "Unbekannter Fehler"
        if exc_value is None:
            return exc_type.__name__
        return f"{exc_type.__name__}: {exc_value}"
