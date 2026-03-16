from __future__ import annotations

import configparser
import importlib
import sys
import traceback
from pathlib import Path

from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QToolBar
from qgis.core import Qgis, QgsMessageLog

from .manifest import BACKGROUND_TOOL, BUNDLED_PLUGINS, INTERACTIVE_TOOL
from .overview_dialog import MasterOverviewDialog
from .settings_dialog import MasterSettingsDialog
from .shared_settings import (
    build_postgres_ogr_uri,
    has_saved_shared_settings,
    load_shared_settings,
    save_shared_settings,
    sync_attribution_butler_settings,
)


class TrassifyMasterToolsPlugin:
    MENU_TITLE = "Trassify Master Tools"
    OVERVIEW_ACTION_TEXT = "Master-Uebersicht oeffnen"
    LOAD_ACTION_PREFIX = "Modul laden: "
    TOOLBAR_OBJECT_NAME = "TrassifyMasterToolsToolbar"
    BUNDLE_MISSING_MESSAGE = (
        "Gebuendelte Module fehlen in diesem Quell-Checkout. "
        "Installiere das gebaute ZIP; ./trassify_master_tools/build_zip.sh erstellt es."
    )
    LOG_TAG = "Trassify Master Tools"
    TOOL_TYPE_LABELS = {
        INTERACTIVE_TOOL: "Normales Tool",
        BACKGROUND_TOOL: "Hintergrundtool",
    }

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = Path(__file__).resolve().parent
        self.bundled_plugins_root = self.plugin_dir / "bundled_plugins"
        self.interactive_bundled_root = self.bundled_plugins_root / INTERACTIVE_TOOL
        self.background_bundled_root = self.bundled_plugins_root / BACKGROUND_TOOL
        self.toolbar = None
        self._toolbar_created = False
        self.overview_action = None
        self.overview_dialog = None
        self.loaded_plugins = []
        self.load_errors = []
        self.conflicts = []
        self.load_actions = {}
        self._registry_keys = []
        self._added_import_paths = []
        self._module_metadata_cache = {}

    def initGui(self):
        if has_saved_shared_settings():
            self._sync_shared_settings()
        self._ensure_toolbar()

        self.overview_action = QAction(
            QIcon(str(self.plugin_dir / "icon.svg")),
            self.OVERVIEW_ACTION_TEXT,
            self.iface.mainWindow(),
        )
        self.overview_action.triggered.connect(self.show_overview)
        if self.toolbar is not None:
            self.toolbar.addAction(self.overview_action)

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
        background_summary = self._load_background_modules()
        self._refresh_conflicts()
        self._show_startup_message(background_summary)

    def unload(self):
        try:
            self._unload_impl()
        except BaseException as exc:
            self._log_unload_failure("Master-Plugin", exc)

    def _unload_impl(self):
        toolbar = self._find_master_toolbar()
        overview_dialog = self.overview_dialog
        overview_action = self.overview_action
        load_actions = list(self.load_actions.values())

        self.overview_dialog = None
        self.overview_action = None
        self.load_actions = {}
        self.toolbar = None
        toolbar_created = self._toolbar_created
        self._toolbar_created = False

        for spec, plugin in reversed(self.loaded_plugins):
            try:
                plugin.unload()
            except Exception:
                self._log_exception(spec["label"], "Fehler beim Entladen")

        self.loaded_plugins.clear()
        self.load_errors.clear()
        self._unregister_bundled_plugins()

        if self._is_qt_object_alive(overview_dialog):
            self._safe_qt_call(overview_dialog.close)
            self._safe_qt_call(overview_dialog.deleteLater)

        if self._is_qt_object_alive(toolbar) and self._is_qt_object_alive(overview_action):
            self._safe_qt_call(toolbar.removeAction, overview_action)
        if self._is_qt_object_alive(overview_action):
            self._safe_qt_call(overview_action.deleteLater)

        for action in load_actions:
            if self._is_qt_object_alive(action):
                self._safe_qt_call(self.iface.removePluginMenu, self.MENU_TITLE, action)
                self._safe_qt_call(action.deleteLater)
        self.conflicts.clear()

        if self._is_qt_object_alive(toolbar) and toolbar_created:
            self._safe_qt_call(self.iface.mainWindow().removeToolBar, toolbar)
            self._safe_qt_call(toolbar.deleteLater)

        for path_text in reversed(self._added_import_paths):
            if path_text in sys.path:
                sys.path.remove(path_text)
        self._added_import_paths.clear()

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

    def show_settings(self):
        dialog = MasterSettingsDialog(self, self.iface.mainWindow())
        if dialog.exec_() != dialog.Accepted:
            return

        settings = self.save_shared_settings(dialog.values())
        has_database_uri = bool(build_postgres_ogr_uri(settings))
        message = "Zentrale Einstellungen gespeichert."
        if has_database_uri:
            message += " Datenbank-URI fuer Master-Module ist verfuegbar."

        self.iface.messageBar().pushMessage(
            self.MENU_TITLE,
            message,
            level=Qgis.Success,
            duration=5,
        )

    def _ensure_bundle_import_path(self):
        for bundle_root in (
            self.background_bundled_root,
            self.interactive_bundled_root,
        ):
            if not bundle_root.is_dir():
                continue

            bundle_root_str = str(bundle_root)
            if bundle_root_str not in sys.path:
                sys.path.insert(0, bundle_root_str)
                self._added_import_paths.append(bundle_root_str)

    def _create_load_actions(self):
        for spec in self._interactive_specs():
            action = QAction(
                f"{self.LOAD_ACTION_PREFIX}{spec['label']}",
                self.iface.mainWindow(),
            )
            action.triggered.connect(
                lambda _checked=False, spec=spec: self._load_single_module(spec)
            )
            self.iface.addPluginToMenu(self.MENU_TITLE, action)
            self.load_actions[spec["key"]] = action

    def _load_background_modules(self):
        summary = {
            "loaded": [],
            "conflicts": [],
            "errors": [],
        }

        for spec in self._background_specs():
            if self._load_single_module(spec, announce=False):
                summary["loaded"].append(spec["label"])
                continue

            if self._get_conflict_message(spec):
                summary["conflicts"].append(spec["label"])
            else:
                summary["errors"].append(spec["label"])

        return summary

    def _show_startup_message(self, background_summary):
        message_parts = ["Master-Toolbar aktiv."]

        loaded_count = len(background_summary["loaded"])
        if loaded_count:
            message_parts.append(
                f"{loaded_count} Hintergrundtool(s) automatisch aktiv."
            )

        conflict_count = len(background_summary["conflicts"])
        if conflict_count:
            message_parts.append(
                f"{conflict_count} Hintergrundtool(s) blockiert."
            )

        error_count = len(background_summary["errors"])
        if error_count:
            message_parts.append(
                f"{error_count} Hintergrundtool(s) mit Fehler."
            )

        if not loaded_count and not conflict_count and not error_count:
            message_parts.append(
                "Einstellungen ueber die Uebersicht oeffnen."
            )

        self.iface.messageBar().pushMessage(
            self.MENU_TITLE,
            " ".join(message_parts),
            level=Qgis.Warning if conflict_count or error_count else Qgis.Info,
            duration=6 if conflict_count or error_count else 5,
        )

    def _load_single_module(self, spec, announce=True):
        if self._is_loaded(spec):
            return True

        self._refresh_conflicts()
        conflict_message = self._get_conflict_message(spec)
        if conflict_message:
            self._record_error(spec, conflict_message)
            if announce:
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
            self._inject_master_context(module)
            factory = getattr(module, "classFactory", None)
            if factory is None:
                raise AttributeError(
                    f"classFactory fehlt in Paket '{spec['package']}'"
                )

            plugin = factory(self.iface)
            self._inject_master_context(module, plugin)
            self._register_bundled_plugin(spec["package"], plugin)
            plugin.initGui()
            self._apply_shared_settings_to_plugin(spec, plugin, module)
            self.loaded_plugins.append((spec, plugin))
            self._clear_error(spec)
            self._disable_load_action(spec)
            if announce:
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
            if announce:
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
            metadata = self._get_module_metadata(spec)
            label = metadata.get("name") or spec["label"]
            description = metadata.get("description") or metadata.get("about") or ""
            about = metadata.get("about") or description
            detail = label
            status_code = "ready"
            status_text = "Bereit"
            tool_type = spec.get("tool_type", INTERACTIVE_TOOL)
            tool_type_label = self.TOOL_TYPE_LABELS.get(tool_type, "Tool")

            if self._is_loaded(spec):
                status_code = "loaded"
                status_text = "Geladen"
                if tool_type == BACKGROUND_TOOL:
                    status_text = "Im Hintergrund aktiv"
                    detail = f"{label} laeuft bereits im Hintergrund ueber das Master-Plugin."
                else:
                    detail = f"{label} ist bereits ueber das Master-Plugin aktiv."
            elif spec["key"] in conflict_by_key:
                status_code = "conflict"
                status_text = "Blockiert"
                detail = conflict_by_key[spec["key"]]
            elif spec["key"] in error_by_key:
                status_code = "error"
                status_text = "Fehler"
                detail = error_by_key[spec["key"]]
            else:
                if tool_type == BACKGROUND_TOOL:
                    detail = f"{label} wird beim Start automatisch als Hintergrundtool geladen."
                else:
                    detail = f"{label} kann jetzt ueber das Master-Plugin geladen werden."

            rows.append(
                {
                    "key": spec["key"],
                    "label": label,
                    "package": spec["package"],
                    "tool_type": tool_type,
                    "tool_type_label": tool_type_label,
                    "status_code": status_code,
                    "status_text": status_text,
                    "detail": detail,
                    "description": description,
                    "about": about,
                    "author": metadata.get("author") or "",
                    "version": metadata.get("version") or "",
                    "category": metadata.get("category") or "Plugins",
                    "tags": self._split_tags(metadata.get("tags")),
                    "homepage": metadata.get("homepage") or "",
                    "tracker": metadata.get("tracker") or "",
                    "repository": metadata.get("repository") or "",
                    "icon_path": self._resolve_module_icon_path(
                        spec, metadata.get("icon") or ""
                    ),
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

    def _log_unload_failure(self, label, exc):
        try:
            QgsMessageLog.logMessage(
                f"Fehler beim Entladen: {label}\n{type(exc).__name__}: {exc}",
                self.LOG_TAG,
                Qgis.Warning,
            )
        except Exception:
            pass

    def _short_exception_message(self):
        exc_type, exc_value, _tb = sys.exc_info()
        if exc_type is None:
            return "Unbekannter Fehler"
        if exc_value is None:
            return exc_type.__name__
        return f"{exc_type.__name__}: {exc_value}"

    def get_shared_settings(self):
        return self._enriched_shared_settings(load_shared_settings())

    def save_shared_settings(self, config):
        normalized = self._enriched_shared_settings(save_shared_settings(config))
        self._sync_shared_settings(normalized)
        self._apply_shared_settings_to_loaded_plugins(normalized)
        return normalized

    def _sync_shared_settings(self, config=None):
        settings = config or self.get_shared_settings()
        sync_attribution_butler_settings(settings)

    def _apply_shared_settings_to_loaded_plugins(self, settings):
        for spec, plugin in self.loaded_plugins:
            module = sys.modules.get(spec["package"])
            self._apply_shared_settings_to_plugin(spec, plugin, module, settings)

    def _apply_shared_settings_to_plugin(
        self,
        spec,
        plugin,
        module=None,
        settings=None,
    ):
        shared_settings = dict(settings or self.get_shared_settings())

        self._inject_master_context(module, plugin, shared_settings)

        for handler_name, argument_variants in (
            ("apply_master_settings", ((shared_settings,), ())),
            ("set_master_settings", ((shared_settings,), ())),
            ("set_master_context", ((self, shared_settings), (shared_settings,), (self,))),
            ("reload_master_settings", ((),)),
        ):
            handler = getattr(plugin, handler_name, None)
            if not callable(handler):
                continue

            for args in argument_variants:
                try:
                    handler(*args)
                    return
                except TypeError:
                    continue
                except Exception:
                    self._log_exception(
                        spec["label"],
                        f"Fehler beim Anwenden von Master-Settings via {handler_name}",
                    )
                    return

    def _inject_master_context(self, module=None, plugin=None, settings=None):
        shared_settings = dict(settings or self.get_shared_settings())

        if module is not None:
            try:
                setattr(module, "TRASSIFY_MASTER_PLUGIN", self)
                setattr(module, "TRASSIFY_MASTER_SETTINGS", shared_settings)
            except Exception:
                pass

        if plugin is not None:
            try:
                setattr(plugin, "trassify_master_plugin", self)
                setattr(plugin, "trassify_master_settings", shared_settings)
            except Exception:
                pass

    def _enriched_shared_settings(self, settings):
        enriched = dict(settings or {})
        enriched["database_ogr_uri"] = build_postgres_ogr_uri(enriched)
        return enriched

    def _ensure_toolbar(self):
        toolbar = self._find_master_toolbar()
        if toolbar is None:
            toolbar = self.iface.mainWindow().addToolBar(self.MENU_TITLE)
            toolbar.setObjectName(self.TOOLBAR_OBJECT_NAME)
            toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
            self._toolbar_created = True
        else:
            self._toolbar_created = False

        toolbar.setVisible(True)
        self.toolbar = toolbar

    def _get_module_metadata(self, spec):
        cached = self._module_metadata_cache.get(spec["key"])
        if cached is not None:
            return cached

        metadata = {}
        metadata_path = self._resolve_module_metadata_path(spec)
        if metadata_path is not None and metadata_path.is_file():
            parser = configparser.ConfigParser(interpolation=None)
            try:
                parser.read(metadata_path, encoding="utf-8")
            except UnicodeDecodeError:
                parser.read(metadata_path, encoding="latin-1")

            if parser.has_section("general"):
                metadata = {
                    key: value.strip()
                    for key, value in parser.items("general")
                }

        self._module_metadata_cache[spec["key"]] = metadata
        return metadata

    def _resolve_module_metadata_path(self, spec):
        for candidate_dir in self._module_directory_candidates(spec):
            candidate_path = candidate_dir / "metadata.txt"
            if candidate_path.is_file():
                return candidate_path
        return None

    def _resolve_module_icon_path(self, spec, icon_name):
        for candidate_dir in self._module_directory_candidates(spec):
            if icon_name:
                explicit_path = candidate_dir / icon_name
                if explicit_path.is_file():
                    return str(explicit_path)

            for fallback_name in ("icon.svg", "icon.png", "icon.ico"):
                fallback_path = candidate_dir / fallback_name
                if fallback_path.is_file():
                    return str(fallback_path)

        return str(self.plugin_dir / "icon.svg")

    def _module_directory_candidates(self, spec):
        yield self._bundled_plugin_dir(spec)

        source_root = self.plugin_dir.parent / "plugin_sources" / spec["source_path"]
        if source_root.is_dir():
            yield source_root

    def _bundled_plugin_dir(self, spec):
        return self.bundled_plugins_root / spec.get("tool_type", INTERACTIVE_TOOL) / spec["package"]

    def _interactive_specs(self):
        return [
            spec for spec in BUNDLED_PLUGINS
            if spec.get("tool_type", INTERACTIVE_TOOL) == INTERACTIVE_TOOL
        ]

    def _background_specs(self):
        return [
            spec for spec in BUNDLED_PLUGINS
            if spec.get("tool_type", INTERACTIVE_TOOL) == BACKGROUND_TOOL
        ]

    def _split_tags(self, raw_tags):
        if not raw_tags:
            return []

        return [
            tag.strip()
            for tag in raw_tags.replace(";", ",").split(",")
            if tag.strip()
        ]

    def _is_qt_object_alive(self, obj):
        if obj is None:
            return False
        try:
            return not sip.isdeleted(obj)
        except Exception:
            return False

    def _safe_qt_call(self, func, *args):
        try:
            return func(*args)
        except RuntimeError:
            return None
        except ReferenceError:
            return None

    def _find_master_toolbar(self):
        try:
            main_window = self.iface.mainWindow()
        except RuntimeError:
            return None
        except ReferenceError:
            return None

        if main_window is None:
            return None

        try:
            return main_window.findChild(QToolBar, self.TOOLBAR_OBJECT_NAME)
        except RuntimeError:
            return None
        except ReferenceError:
            return None
