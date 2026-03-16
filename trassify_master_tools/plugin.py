from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import Qgis, QgsMessageLog

from .manifest import BUNDLED_PLUGINS


class TrassifyMasterToolsPlugin:
    MENU_TITLE = "Trassify Master Tools"
    STATUS_ACTION_TEXT = "Modulstatus anzeigen"
    LOAD_ACTION_PREFIX = "Modul laden: "
    LOG_TAG = "Trassify Master Tools"

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = Path(__file__).resolve().parent
        self.bundled_plugins_root = self.plugin_dir / "bundled_plugins"
        self.status_action = None
        self.loaded_plugins = []
        self.load_errors = []
        self.conflicts = []
        self.load_actions = {}
        self._bundled_plugins_root_str = str(self.bundled_plugins_root)
        self._registry_keys = []
        self._path_added = False

    def initGui(self):
        self._ensure_bundle_import_path()

        self.status_action = QAction(
            QIcon(str(self.plugin_dir / "icon.svg")),
            self.STATUS_ACTION_TEXT,
            self.iface.mainWindow(),
        )
        self.status_action.triggered.connect(self.show_status)
        self.iface.addPluginToMenu(self.MENU_TITLE, self.status_action)

        self._create_load_actions()
        self._refresh_conflicts()

        self.iface.messageBar().pushMessage(
            self.MENU_TITLE,
            "Master-Plugin aktiv. Module bei Bedarf ueber das Menue laden.",
            level=Qgis.Info,
            duration=5,
        )

    def unload(self):
        for spec, plugin in reversed(self.loaded_plugins):
            try:
                plugin.unload()
            except Exception:
                self._log_exception(spec["label"], "Fehler beim Entladen")

        self.loaded_plugins.clear()
        self.load_errors.clear()
        self._unregister_bundled_plugins()

        if self.status_action is not None:
            self.iface.removePluginMenu(self.MENU_TITLE, self.status_action)
            self.status_action.deleteLater()
            self.status_action = None

        for action in self.load_actions.values():
            self.iface.removePluginMenu(self.MENU_TITLE, action)
            action.deleteLater()
        self.load_actions.clear()
        self.conflicts.clear()

        if self._path_added and self._bundled_plugins_root_str in sys.path:
            sys.path.remove(self._bundled_plugins_root_str)
            self._path_added = False

    def show_status(self):
        self._refresh_conflicts()

        lines = [
            f"Geladen: {len(self.loaded_plugins)}/{len(BUNDLED_PLUGINS)}",
            "",
        ]

        if self.loaded_plugins:
            lines.append("Aktive Module:")
            for spec, _plugin in self.loaded_plugins:
                lines.append(f"- {spec['label']}")
            lines.append("")

        pending_modules = [
            spec["label"]
            for spec in BUNDLED_PLUGINS
            if not self._is_loaded(spec) and not self._has_conflict(spec)
        ]
        if pending_modules:
            lines.append("Noch nicht geladen:")
            for label in pending_modules:
                lines.append(f"- {label}")
            lines.append("")

        if self.conflicts:
            lines.append("Konflikte:")
            for spec, message in self.conflicts:
                lines.append(f"- {spec['label']}: {message}")
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

    def _ensure_bundle_import_path(self):
        if self._bundled_plugins_root_str not in sys.path:
            sys.path.insert(0, self._bundled_plugins_root_str)
            self._path_added = True

    def _create_load_actions(self):
        for spec in BUNDLED_PLUGINS:
            action = QAction(
                f"{self.LOAD_ACTION_PREFIX}{spec['label']}",
                self.iface.mainWindow(),
            )
            action.triggered.connect(
                lambda _checked=False, spec=spec: self._load_single_module(spec)
            )
            self.iface.addPluginToMenu(self.MENU_TITLE, action)
            self.load_actions[spec["key"]] = action

    def _load_single_module(self, spec):
        if self._is_loaded(spec):
            return True

        self._refresh_conflicts()
        conflict_message = self._get_conflict_message(spec)
        if conflict_message:
            self._record_error(spec, conflict_message)
            self.iface.messageBar().pushMessage(
                self.MENU_TITLE,
                f"{spec['label']} ist bereits extern aktiv.",
                level=Qgis.Warning,
                duration=6,
            )
            return False

        self._purge_bundled_package(spec["package"])
        plugin = None
        try:
            module = importlib.import_module(spec["package"])
            factory = getattr(module, "classFactory", None)
            if factory is None:
                raise AttributeError(
                    f"classFactory fehlt in Paket '{spec['package']}'"
                )

            plugin = factory(self.iface)
            self._register_bundled_plugin(spec["package"], plugin)
            plugin.initGui()
            self.loaded_plugins.append((spec, plugin))
            self._clear_error(spec)
            self._disable_load_action(spec)
            self.iface.messageBar().pushMessage(
                self.MENU_TITLE,
                f"{spec['label']} wurde geladen.",
                level=Qgis.Info,
                duration=4,
            )
            return True
        except Exception:
            self._unregister_bundled_plugin(spec["package"])
            self._purge_bundled_package(spec["package"])
            self._log_exception(spec["label"], "Fehler beim Laden")
            self._record_error(spec, self._short_exception_message())
            self.iface.messageBar().pushMessage(
                self.MENU_TITLE,
                f"{spec['label']} konnte nicht geladen werden.",
                level=Qgis.Warning,
                duration=6,
            )
            return False

    def _register_bundled_plugin(self, package_name, plugin):
        try:
            import qgis.utils as qgis_utils
        except Exception:
            return

        registry = getattr(qgis_utils, "plugins", None)
        if not isinstance(registry, dict):
            return

        registry_key = f"bundled:{package_name}"
        registry[registry_key] = plugin
        self._registry_keys.append(registry_key)

    def _unregister_bundled_plugin(self, package_name):
        registry_key = f"bundled:{package_name}"
        try:
            import qgis.utils as qgis_utils
        except Exception:
            return

        registry = getattr(qgis_utils, "plugins", None)
        if isinstance(registry, dict):
            registry.pop(registry_key, None)

        if registry_key in self._registry_keys:
            self._registry_keys.remove(registry_key)

    def _unregister_bundled_plugins(self):
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

    def _is_loaded(self, wanted_spec):
        return any(spec["key"] == wanted_spec["key"] for spec, _ in self.loaded_plugins)

    def _refresh_conflicts(self):
        self.conflicts = []

        for spec in BUNDLED_PLUGINS:
            action = self.load_actions.get(spec["key"])
            if self._is_loaded(spec):
                continue

            message = self._external_conflict_message(spec)
            if message is not None:
                self.conflicts.append((spec, message))
                if action is not None:
                    action.setEnabled(False)
                    action.setText(f"Extern aktiv: {spec['label']}")
                continue

            if action is not None:
                action.setEnabled(True)
                action.setText(f"{self.LOAD_ACTION_PREFIX}{spec['label']}")

    def _external_conflict_message(self, spec):
        package_name = spec["package"]

        try:
            import qgis.utils as qgis_utils
        except Exception:
            qgis_utils = None

        if qgis_utils is not None:
            registry = getattr(qgis_utils, "plugins", None)
            if isinstance(registry, dict) and package_name in registry:
                return "separat installiertes Plugin ist bereits in QGIS aktiv"

        module = sys.modules.get(package_name)
        if module is not None and not self._module_belongs_to_bundle(module):
            return "Paket ist bereits ausserhalb des Bundles importiert"

        return None

    def _has_conflict(self, wanted_spec):
        return any(spec["key"] == wanted_spec["key"] for spec, _ in self.conflicts)

    def _get_conflict_message(self, wanted_spec):
        for spec, message in self.conflicts:
            if spec["key"] == wanted_spec["key"]:
                return message
        return None

    def _record_error(self, spec, message):
        self.load_errors = [
            (existing_spec, existing_message)
            for existing_spec, existing_message in self.load_errors
            if existing_spec["key"] != spec["key"]
        ]
        self.load_errors.append((spec, message))

    def _clear_error(self, spec):
        self.load_errors = [
            (existing_spec, existing_message)
            for existing_spec, existing_message in self.load_errors
            if existing_spec["key"] != spec["key"]
        ]

    def _disable_load_action(self, spec):
        action = self.load_actions.get(spec["key"])
        if action is not None:
            action.setEnabled(False)
            action.setText(f"Geladen: {spec['label']}")

    def _purge_bundled_package(self, package_name):
        removable_modules = []
        prefix = f"{package_name}."

        for module_name, module in list(sys.modules.items()):
            if module_name != package_name and not module_name.startswith(prefix):
                continue
            if self._module_belongs_to_bundle(module):
                removable_modules.append(module_name)

        for module_name in removable_modules:
            sys.modules.pop(module_name, None)

    def _module_belongs_to_bundle(self, module):
        if module is None:
            return False

        candidate_paths = []
        module_file = getattr(module, "__file__", None)
        if module_file:
            candidate_paths.append(module_file)

        module_spec = getattr(module, "__spec__", None)
        spec_origin = getattr(module_spec, "origin", None)
        if spec_origin and spec_origin not in {"built-in", "frozen"}:
            candidate_paths.append(spec_origin)

        module_path = getattr(module, "__path__", None)
        if module_path:
            candidate_paths.extend(list(module_path))

        return any(self._path_belongs_to_bundle(path) for path in candidate_paths)

    def _path_belongs_to_bundle(self, value):
        try:
            Path(value).resolve().relative_to(self.bundled_plugins_root.resolve())
        except Exception:
            return False
        return True

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
