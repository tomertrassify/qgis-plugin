from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import Qgis, QgsMessageLog

from .manifest import BUNDLED_PLUGINS
from .overview_dialog import MasterOverviewDialog


class TrassifyMasterToolsPlugin:
    MENU_TITLE = "Trassify Master Tools"
    OVERVIEW_ACTION_TEXT = "Master-Uebersicht oeffnen"
    LOAD_ACTION_PREFIX = "Modul laden: "
    BUNDLE_MISSING_MESSAGE = (
        "Gebuendelte Module fehlen in diesem Quell-Checkout. "
        "Installiere das gebaute ZIP; ./trassify_master_tools/build_zip.sh erstellt es."
    )
    LOG_TAG = "Trassify Master Tools"

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = Path(__file__).resolve().parent
        self.bundled_plugins_root = self.plugin_dir / "bundled_plugins"
        self.overview_action = None
        self.overview_dialog = None
        self.loaded_plugins = []
        self.load_errors = []
        self.conflicts = []
        self.load_actions = {}
        self._bundled_plugins_root_str = str(self.bundled_plugins_root)
        self._registry_keys = []
        self._path_added = False

    def initGui(self):
        self.overview_action = QAction(
            QIcon(str(self.plugin_dir / "icon.svg")),
            self.OVERVIEW_ACTION_TEXT,
            self.iface.mainWindow(),
        )
        self.overview_action.triggered.connect(self.show_overview)
        self.iface.addToolBarIcon(self.overview_action)
        self.iface.addPluginToMenu(self.MENU_TITLE, self.overview_action)

        if not self.bundled_plugins_root.is_dir():
            self.iface.messageBar().pushMessage(
                self.MENU_TITLE,
                self.BUNDLE_MISSING_MESSAGE,
                level=Qgis.Warning,
                duration=8,
            )
            return

        self._ensure_bundle_import_path()
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

        if self.overview_dialog is not None:
            self.overview_dialog.close()
            self.overview_dialog.deleteLater()
            self.overview_dialog = None

        if self.overview_action is not None:
            self.iface.removeToolBarIcon(self.overview_action)
            self.iface.removePluginMenu(self.MENU_TITLE, self.overview_action)
            self.overview_action.deleteLater()
            self.overview_action = None

        for action in self.load_actions.values():
            self.iface.removePluginMenu(self.MENU_TITLE, action)
            action.deleteLater()
        self.load_actions.clear()
        self.conflicts.clear()

        if self._path_added and self._bundled_plugins_root_str in sys.path:
            sys.path.remove(self._bundled_plugins_root_str)
            self._path_added = False

    def show_overview(self):
        if not self.bundled_plugins_root.is_dir():
            QMessageBox.information(
                self.iface.mainWindow(),
                self.MENU_TITLE,
                self.BUNDLE_MISSING_MESSAGE,
            )
            return

        if self.overview_dialog is None:
            self.overview_dialog = MasterOverviewDialog(
                self, self.iface.mainWindow()
            )
        else:
            self.overview_dialog.refresh()

        self.overview_dialog.show()
        self.overview_dialog.raise_()
        self.overview_dialog.activateWindow()

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
            self._refresh_overview_dialog()
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
            self._refresh_overview_dialog()
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
            self._refresh_overview_dialog()
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

    def _refresh_overview_dialog(self):
        if self.overview_dialog is not None:
            self.overview_dialog.refresh()

    def get_module_rows(self):
        self._refresh_conflicts()

        error_by_key = {
            spec["key"]: message for spec, message in self.load_errors
        }
        conflict_by_key = {
            spec["key"]: message for spec, message in self.conflicts
        }

        rows = []
        for spec in BUNDLED_PLUGINS:
            detail = spec["label"]
            status_code = "ready"
            status_text = "Bereit"

            if self._is_loaded(spec):
                status_code = "loaded"
                status_text = "Geladen"
                detail = f"{spec['label']} ist bereits ueber das Master-Plugin aktiv."
            elif spec["key"] in conflict_by_key:
                status_code = "conflict"
                status_text = "Blockiert"
                detail = conflict_by_key[spec["key"]]
            elif spec["key"] in error_by_key:
                status_code = "error"
                status_text = "Fehler"
                detail = error_by_key[spec["key"]]
            else:
                detail = f"{spec['label']} kann jetzt ueber das Master-Plugin geladen werden."

            rows.append(
                {
                    "key": spec["key"],
                    "label": spec["label"],
                    "package": spec["package"],
                    "status_code": status_code,
                    "status_text": status_text,
                    "detail": detail,
                }
            )

        return rows

    def load_module_by_key(self, key):
        for spec in BUNDLED_PLUGINS:
            if spec["key"] == key:
                return self._load_single_module(spec)
        return False

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
