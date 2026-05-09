from __future__ import annotations

import configparser
import importlib
import json
import re
import shutil
import sys
import tempfile
import traceback
import urllib.request
import xml.etree.ElementTree as ET
from itertools import zip_longest
from pathlib import Path
from zipfile import ZipFile

import qgis.utils as qgis_utils
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QSettings, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QToolBar
from qgis.core import Qgis, QgsApplication, QgsMessageLog

from .manifest import BACKGROUND_TOOL, BUNDLED_PLUGINS, INTERACTIVE_TOOL
from .overview_dialog import MasterOverviewDialog
from .settings_dialog import MasterSettingsDialog
from .shared_settings import (
    build_postgres_ogr_uri,
    has_saved_shared_settings,
    load_favorite_module_keys,
    load_shared_settings,
    save_favorite_module_keys,
    save_shared_settings,
    sync_attribution_butler_settings,
)


class TrassifyMasterToolsPlugin:
    MENU_TITLE = "Trassify Master Tools"
    OVERVIEW_ACTION_TEXT = "Master-Uebersicht oeffnen"
    TOOLBAR_OBJECT_NAME = "TrassifyMasterToolsToolbar"
    LOG_TAG = "Trassify Master Tools"
    TOOL_TYPE_LABELS = {
        INTERACTIVE_TOOL: "Normales Tool",
        BACKGROUND_TOOL: "Hintergrundtool",
    }
    CATALOG_RELATIVE_PATH = Path("catalog") / "plugins.json"
    CATALOG_USER_AGENT = "TrassifyMasterTools/2.0"
    DEFAULT_OPEN_METHOD_CANDIDATES = ("show_overview", "run", "show_dialog")
    PACKAGE_OPEN_METHOD_CANDIDATES = {
        "quickrule": ("run_quickrule", "run"),
    }

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = Path(__file__).resolve().parent
        self.toolbar = None
        self._toolbar_created = False
        self.overview_action = None
        self.overview_dialog = None
        self.module_action_errors: dict[str, str] = {}
        self.catalog_entries: list[dict] = []
        self.catalog_entries_by_key: dict[str, dict] = {}
        self.remote_catalog_by_zip_name: dict[str, dict] = {}
        self.catalog_plugins_xml_url = ""
        self.catalog_refresh_error = ""
        stored_favorite_keys = load_favorite_module_keys()
        self.favorite_module_keys = self._sanitize_favorite_module_keys(
            stored_favorite_keys
        )
        if self.favorite_module_keys != stored_favorite_keys:
            self.favorite_module_keys = save_favorite_module_keys(
                self.favorite_module_keys
            )
        self._unloaded = False

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
        self.iface.addPluginToMenu(self.MENU_TITLE, self.overview_action)
        if self.toolbar is not None:
            self.toolbar.addAction(self.overview_action)

        self._load_catalog_snapshot()
        self.refresh_catalog(announce=False)
        self._show_startup_message()

    def unload(self):
        if self._unloaded:
            return

        self._unloaded = True

        toolbar = self._find_master_toolbar() or self.toolbar

        if self._is_qt_object_alive(self.overview_dialog):
            self._safe_qt_call(self.overview_dialog.close)
            self._safe_qt_call(self.overview_dialog.deleteLater)

        if self._is_qt_object_alive(self.overview_action):
            self._safe_qt_call(self.iface.removePluginMenu, self.MENU_TITLE, self.overview_action)
            if self._is_qt_object_alive(toolbar):
                self._safe_qt_call(toolbar.removeAction, self.overview_action)
            self._safe_qt_call(self.overview_action.deleteLater)

        if self._is_qt_object_alive(toolbar) and self._toolbar_created:
            self._safe_qt_call(self.iface.mainWindow().removeToolBar, toolbar)
            self._safe_qt_call(toolbar.deleteLater)

    def show_overview(self):
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
            message += " Datenbank-URI fuer kompatible Plugins ist verfuegbar."

        self.iface.messageBar().pushMessage(
            self.MENU_TITLE,
            message,
            level=Qgis.Success,
            duration=5,
        )

    def refresh_catalog(self, announce=True):
        self._load_catalog_snapshot()
        self._refresh_remote_catalog()
        self._refresh_ui_state()

        if announce:
            if self.catalog_refresh_error:
                self.iface.messageBar().pushMessage(
                    self.MENU_TITLE,
                    "Katalog aktualisiert, Online-Index ist derzeit nicht erreichbar.",
                    level=Qgis.Warning,
                    duration=6,
                )
            else:
                self.iface.messageBar().pushMessage(
                    self.MENU_TITLE,
                    "Katalog aktualisiert.",
                    level=Qgis.Info,
                    duration=4,
                )

    def get_shared_settings(self):
        return self._enriched_shared_settings(load_shared_settings())

    def save_shared_settings(self, config):
        normalized = self._enriched_shared_settings(save_shared_settings(config))
        self._sync_shared_settings(normalized)
        return normalized

    def is_favorite(self, key):
        return key in self.favorite_module_keys

    def toggle_favorite_by_key(self, key):
        favorite_keys = self._sanitize_favorite_module_keys(self.favorite_module_keys)
        valid_keys = {spec["key"] for spec in BUNDLED_PLUGINS}
        if key not in valid_keys:
            return False

        if key in favorite_keys:
            favorite_keys = [
                favorite_key
                for favorite_key in favorite_keys
                if favorite_key != key
            ]
        else:
            favorite_keys.append(key)

        self.favorite_module_keys = save_favorite_module_keys(favorite_keys)
        self._refresh_ui_state()
        return key in self.favorite_module_keys

    def get_module_rows(self):
        self._refresh_available_plugins()
        return sorted(
            (self._build_module_row(spec) for spec in BUNDLED_PLUGINS),
            key=lambda row: row["label"].lower(),
        )

    def get_primary_action_label(self, row):
        status_code = row["status_code"]
        if status_code == "available":
            return "Installieren"
        if status_code == "installed":
            return "Aktivieren"
        if status_code == "active":
            return "Deaktivieren"
        if status_code == "update":
            return "Aktualisieren"
        if status_code == "error":
            return "Erneut versuchen"
        return ""

    def can_run_primary_action(self, row):
        return row["status_code"] in {"available", "installed", "active", "update", "error"}

    def get_secondary_action_label(self, row):
        return "Entfernen" if row.get("can_uninstall") else ""

    def can_run_secondary_action(self, row):
        return bool(row.get("can_uninstall"))

    def get_open_action_label(self, row):
        return "Oeffnen" if row.get("can_open") else ""

    def can_open_module(self, row):
        return bool(row.get("can_open"))

    def load_module_by_key(self, key):
        return self.run_primary_action_by_key(key)

    def open_module_by_key(self, key):
        spec = self._spec_by_key(key)
        if spec is None:
            return False

        row = self._build_module_row(spec)
        if not row.get("can_open"):
            return False

        return self._open_installed_module(spec)

    def run_primary_action_by_key(self, key):
        spec = self._spec_by_key(key)
        if spec is None:
            return False

        row = self._build_module_row(spec)
        status_code = row["status_code"]

        if status_code in {"available", "error"}:
            return self._install_or_update_module(spec, activate_after_install=True)
        if status_code == "installed":
            return self._activate_installed_module(spec)
        if status_code == "active":
            return self._deactivate_installed_module(spec)
        if status_code == "update":
            return self._install_or_update_module(
                spec,
                activate_after_install=row["is_active"],
            )

        return False

    def run_secondary_action_by_key(self, key):
        spec = self._spec_by_key(key)
        if spec is None:
            return False

        row = self._build_module_row(spec)
        if not row.get("can_uninstall"):
            return False

        question = QMessageBox.question(
            self.iface.mainWindow(),
            self.MENU_TITLE,
            f"{row['label']} wirklich aus dem lokalen QGIS-Profil entfernen?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if question != QMessageBox.Yes:
            return False

        return self._uninstall_managed_module(spec)

    def _build_module_row(self, spec):
        catalog_entry = self._catalog_entry(spec)
        metadata = catalog_entry.get("metadata", {})
        local_info = self._inspect_local_plugin(spec)

        label = metadata.get("name") or spec["label"]
        description = metadata.get("description") or metadata.get("about") or ""
        about = metadata.get("about") or description
        is_experimental = self._metadata_bool(metadata, "experimental")
        release_state_label = "Experimental" if is_experimental else "Nutzbar"
        release_state_note = (
            "Dieses Plugin ist bereits nutzbar."
            if not is_experimental
            else "Dieses Plugin ist noch als Experimental markiert."
        )
        catalog_version = (
            catalog_entry.get("remote_version")
            or metadata.get("version")
            or ""
        )
        installed_version = local_info["installed_version"]
        update_available = (
            local_info["can_manage"]
            and bool(installed_version and catalog_version)
            and self._compare_versions(installed_version, catalog_version) < 0
        )

        status_code = "available"
        status_text = "Nicht installiert"
        detail = (
            f"{label} ist noch nicht installiert und wird erst bei Bedarf heruntergeladen."
        )
        management_text = (
            "Noch nicht installiert. Bei Bedarf wird das Plugin in das lokale QGIS-Profil geladen."
        )

        if local_info["is_installed"]:
            if update_available:
                status_code = "update"
                status_text = "Update verfuegbar"
                detail = (
                    f"Installiert: {installed_version or '?'} | "
                    f"Verfuegbar: {catalog_version or '?'}."
                )
                if local_info["is_active"]:
                    detail += " Das Plugin ist aktuell in QGIS aktiv."
            elif local_info["is_active"]:
                status_code = "active"
                status_text = "Aktiv"
                detail = (
                    f"{label} ist installiert und aktuell in QGIS aktiv."
                )
            else:
                status_code = "installed"
                status_text = "Installiert"
                detail = (
                    f"{label} ist installiert, aber aktuell nicht aktiv."
                )

            if local_info["can_manage"]:
                detail += " Die Installation liegt im lokalen QGIS-Profil und kann hier aktualisiert oder entfernt werden."
                management_text = (
                    "Im lokalen QGIS-Profil installiert. Dieses Plugin kann hier installiert, aktualisiert, aktiviert und entfernt werden."
                )
            else:
                detail += " Die Installation liegt ausserhalb des lokalen QGIS-Profils und wird hier nur angezeigt."
                management_text = (
                    "Ausserhalb des lokalen QGIS-Profils installiert. Aktivieren und Deaktivieren bleiben moeglich, "
                    "Datei-Updates und Entfernen sind hier deaktiviert."
                )

        error_message = self.module_action_errors.get(spec["key"], "").strip()
        if error_message:
            if not local_info["is_installed"]:
                status_code = "error"
                status_text = "Fehler"
                detail = error_message
            else:
                detail = f"{detail} Letzter Fehler: {error_message}"

        version_text = catalog_version or "-"
        if installed_version and installed_version != catalog_version:
            version_text = f"{installed_version} -> {catalog_version or '?'}"
        elif installed_version:
            version_text = installed_version

        can_open = self._can_open_installed_module(spec, local_info)

        return {
            "key": spec["key"],
            "label": label,
            "package": spec["package"],
            "tool_type": spec.get("tool_type", INTERACTIVE_TOOL),
            "tool_type_label": self.TOOL_TYPE_LABELS.get(
                spec.get("tool_type", INTERACTIVE_TOOL),
                "Tool",
            ),
            "status_code": status_code,
            "status_text": status_text,
            "detail": detail,
            "description": description,
            "about": about,
            "author": metadata.get("author") or "",
            "version": version_text,
            "release_state_label": release_state_label,
            "release_state_note": release_state_note,
            "is_experimental": is_experimental,
            "category": metadata.get("category") or "Plugins",
            "tags": self._split_tags(metadata.get("tags")),
            "homepage": metadata.get("homepage") or "",
            "tracker": metadata.get("tracker") or "",
            "repository": metadata.get("repository") or "",
            "is_favorite": self.is_favorite(spec["key"]),
            "icon_path": self._resolve_module_icon_path(spec, catalog_entry),
            "plugin_dir": local_info["plugin_dir"],
            "is_active": local_info["is_active"],
            "is_installed": local_info["is_installed"],
            "is_managed": local_info["can_manage"],
            "installed_version": installed_version,
            "catalog_version": catalog_version,
            "download_url": catalog_entry.get("download_url", ""),
            "can_open": can_open,
            "can_uninstall": local_info["can_manage"],
            "management_text": management_text,
        }

    def _load_catalog_snapshot(self):
        snapshot_path = self.plugin_dir / self.CATALOG_RELATIVE_PATH
        if snapshot_path.is_file():
            try:
                payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
                modules = payload.get("modules") or []
                self.catalog_plugins_xml_url = str(payload.get("plugins_xml_url") or "").strip()
                self.catalog_entries = [
                    self._normalized_catalog_entry(entry)
                    for entry in modules
                ]
                self.catalog_entries_by_key = {
                    entry["key"]: entry for entry in self.catalog_entries
                }
                return
            except Exception:
                QgsMessageLog.logMessage(
                    f"Katalog-Snapshot konnte nicht gelesen werden:\n{traceback.format_exc().rstrip()}",
                    self.LOG_TAG,
                    Qgis.Warning,
                )

        self.catalog_entries = self._build_dev_catalog_entries()
        self.catalog_entries_by_key = {
            entry["key"]: entry for entry in self.catalog_entries
        }
        if self.catalog_entries:
            self.catalog_plugins_xml_url = str(
                self.catalog_entries[0].get("plugins_xml_url") or ""
            ).strip()

    def _build_dev_catalog_entries(self):
        raw_base_url = self._resolve_raw_base_url_from_metadata()
        plugins_xml_url = f"{raw_base_url}/plugins.xml" if raw_base_url else ""
        entries = []

        for spec in BUNDLED_PLUGINS:
            metadata = self._get_module_metadata(spec)
            entries.append(
                {
                    "key": spec["key"],
                    "label": spec["label"],
                    "package": spec["package"],
                    "source_path": spec["source_path"],
                    "tool_type": spec.get("tool_type", INTERACTIVE_TOOL),
                    "zip_name": f"{spec['package']}.zip",
                    "download_url": (
                        f"{raw_base_url}/{spec['package']}.zip" if raw_base_url else ""
                    ),
                    "plugins_xml_url": plugins_xml_url,
                    "icon_relative_path": "",
                    "icon_url": "",
                    "metadata": metadata,
                }
            )

        return entries

    def _normalized_catalog_entry(self, entry):
        return {
            "key": str(entry.get("key") or "").strip(),
            "label": str(entry.get("label") or "").strip(),
            "package": str(entry.get("package") or "").strip(),
            "source_path": str(entry.get("source_path") or "").strip(),
            "tool_type": str(entry.get("tool_type") or INTERACTIVE_TOOL).strip(),
            "zip_name": str(entry.get("zip_name") or "").strip(),
            "download_url": str(entry.get("download_url") or "").strip(),
            "plugins_xml_url": str(entry.get("plugins_xml_url") or "").strip(),
            "icon_relative_path": str(entry.get("icon_relative_path") or "").strip(),
            "icon_url": str(entry.get("icon_url") or "").strip(),
            "metadata": dict(entry.get("metadata") or {}),
        }

    def _catalog_entry(self, spec):
        entry = dict(self.catalog_entries_by_key.get(spec["key"]) or {})
        metadata = dict(entry.get("metadata") or {})
        if not metadata:
            metadata = self._get_module_metadata(spec)
            entry["metadata"] = metadata

        remote_entry = self.remote_catalog_by_zip_name.get(entry.get("zip_name", ""))
        if remote_entry:
            entry["download_url"] = remote_entry.get("download_url") or entry.get("download_url", "")
            entry["remote_version"] = remote_entry.get("version", "")
            entry["remote_icon_url"] = remote_entry.get("icon", "")
        else:
            entry["remote_version"] = ""
            entry["remote_icon_url"] = ""

        return entry

    def _refresh_remote_catalog(self):
        url = str(self.catalog_plugins_xml_url or "").strip()
        if not url:
            self.remote_catalog_by_zip_name = {}
            self.catalog_refresh_error = ""
            return

        request = urllib.request.Request(
            url,
            headers={"User-Agent": self.CATALOG_USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = response.read()
            self.remote_catalog_by_zip_name = self._parse_remote_plugins_xml(payload)
            self.catalog_refresh_error = ""
        except Exception as exc:
            self.catalog_refresh_error = f"{type(exc).__name__}: {exc}"

    def _parse_remote_plugins_xml(self, payload: bytes):
        root = ET.fromstring(payload)
        entries = {}

        for plugin_element in root.findall("pyqgis_plugin"):
            file_name = self._xml_text(plugin_element, "file_name")
            if not file_name:
                continue

            entries[file_name] = {
                "version": self._xml_text(plugin_element, "version"),
                "download_url": self._xml_text(plugin_element, "download_url"),
                "icon": self._xml_text(plugin_element, "icon"),
                "name": plugin_element.attrib.get("name", ""),
            }

        return entries

    def _inspect_local_plugin(self, spec):
        plugin_dir = self._find_installed_plugin_dir(spec["package"])
        can_manage = self._can_manage_plugin_dir(plugin_dir)

        active_plugins = getattr(qgis_utils, "active_plugins", []) or []
        is_active = spec["package"] in active_plugins
        if not is_active:
            checker = getattr(qgis_utils, "isPluginLoaded", None)
            if callable(checker):
                try:
                    is_active = bool(checker(spec["package"]))
                except Exception:
                    is_active = False

        installed_version = ""
        if plugin_dir is not None:
            installed_version = self._metadata_value(plugin_dir / "metadata.txt", "version")

        return {
            "plugin_dir": plugin_dir,
            "is_installed": plugin_dir is not None,
            "can_manage": can_manage,
            "is_active": is_active,
            "installed_version": installed_version,
        }

    def _install_or_update_module(self, spec, activate_after_install):
        row = self._build_module_row(spec)
        if row["is_installed"] and not row["is_managed"]:
            self._record_error(
                spec,
                "Plugin liegt ausserhalb des lokalen QGIS-Profils und wird hier nicht ueberschrieben.",
            )
            self._refresh_ui_state()
            return False

        download_url = row.get("download_url", "").strip()
        if not download_url:
            self._record_error(spec, "Keine Download-URL fuer dieses Plugin verfuegbar.")
            self._refresh_ui_state()
            return False

        was_active = bool(row["is_active"])

        try:
            if was_active:
                self._deactivate_installed_module(spec, announce=False)

            with tempfile.TemporaryDirectory(prefix="trassify-master-") as temp_dir_text:
                temp_dir = Path(temp_dir_text)
                archive_path = temp_dir / "plugin.zip"
                extract_root = temp_dir / "extract"

                self._download_archive(download_url, archive_path)
                extracted_plugin_dir = self._extract_plugin_archive(
                    archive_path,
                    spec["package"],
                    extract_root,
                )
                self._replace_plugin_dir(
                    self._target_plugin_dir(spec["package"], row.get("plugin_dir")),
                    extracted_plugin_dir,
                )

            self._set_plugin_enabled_setting(spec["package"], activate_after_install)
            self._refresh_available_plugins()
            self._purge_plugin_module_cache(spec["package"])
            self._clear_error(spec)

            if activate_after_install:
                if not self._activate_installed_module(spec, announce=False):
                    raise RuntimeError("Plugin wurde installiert, konnte aber nicht aktiviert werden.")

            action_label = "aktualisiert" if row["is_installed"] else "installiert"
            message = f"{row['label']} wurde {action_label}."
            if activate_after_install:
                message += " Das Plugin ist jetzt aktiv."

            self.iface.messageBar().pushMessage(
                self.MENU_TITLE,
                message,
                level=Qgis.Success,
                duration=5,
            )
            self._refresh_ui_state()
            return True
        except Exception as exc:
            if was_active:
                self._set_plugin_enabled_setting(spec["package"], True)
                self._activate_installed_module(spec, announce=False)

            self._record_error(spec, f"{type(exc).__name__}: {exc}")
            self.iface.messageBar().pushMessage(
                self.MENU_TITLE,
                f"{row['label']} konnte nicht installiert werden.",
                level=Qgis.Warning,
                duration=6,
            )
            self._refresh_ui_state()
            return False

    def _activate_installed_module(self, spec, announce=True):
        row = self._build_module_row(spec)
        if row["is_active"]:
            return True
        if not row["is_installed"]:
            return False

        try:
            self._set_plugin_enabled_setting(spec["package"], True)
            self._refresh_available_plugins()
            self._purge_plugin_module_cache(spec["package"])

            if not qgis_utils.loadPlugin(spec["package"]):
                raise RuntimeError("loadPlugin() hat False geliefert.")
            if not qgis_utils.startPlugin(spec["package"]):
                raise RuntimeError("startPlugin() hat False geliefert.")

            self._clear_error(spec)
            if announce:
                self.iface.messageBar().pushMessage(
                    self.MENU_TITLE,
                    f"{row['label']} ist jetzt aktiv.",
                    level=Qgis.Info,
                    duration=4,
                )
            self._refresh_ui_state()
            return True
        except Exception as exc:
            self._record_error(spec, f"{type(exc).__name__}: {exc}")
            if announce:
                self.iface.messageBar().pushMessage(
                    self.MENU_TITLE,
                    f"{row['label']} konnte nicht aktiviert werden.",
                    level=Qgis.Warning,
                    duration=6,
                )
            self._refresh_ui_state()
            return False

    def _deactivate_installed_module(self, spec, announce=True):
        row = self._build_module_row(spec)
        if not row["is_active"]:
            self._set_plugin_enabled_setting(spec["package"], False)
            self._refresh_ui_state()
            return True

        try:
            self._set_plugin_enabled_setting(spec["package"], False)
            if not qgis_utils.unloadPlugin(spec["package"]):
                raise RuntimeError("unloadPlugin() hat False geliefert.")
            self._clear_error(spec)
            if announce:
                self.iface.messageBar().pushMessage(
                    self.MENU_TITLE,
                    f"{row['label']} wurde deaktiviert.",
                    level=Qgis.Info,
                    duration=4,
                )
            self._refresh_ui_state()
            return True
        except Exception as exc:
            self._record_error(spec, f"{type(exc).__name__}: {exc}")
            self._set_plugin_enabled_setting(spec["package"], True)
            if announce:
                self.iface.messageBar().pushMessage(
                    self.MENU_TITLE,
                    f"{row['label']} konnte nicht deaktiviert werden.",
                    level=Qgis.Warning,
                    duration=6,
                )
            self._refresh_ui_state()
            return False

    def _uninstall_managed_module(self, spec):
        row = self._build_module_row(spec)
        if not row["can_uninstall"]:
            return False

        try:
            if row["is_active"]:
                self._deactivate_installed_module(spec, announce=False)

            plugin_dir = self._target_plugin_dir(spec["package"], row.get("plugin_dir"))
            if plugin_dir.is_dir():
                shutil.rmtree(plugin_dir)

            self._set_plugin_enabled_setting(spec["package"], False)
            self._purge_plugin_module_cache(spec["package"])
            self._refresh_available_plugins()
            self._clear_error(spec)

            self.iface.messageBar().pushMessage(
                self.MENU_TITLE,
                f"{row['label']} wurde aus dem lokalen Profil entfernt.",
                level=Qgis.Info,
                duration=5,
            )
            self._refresh_ui_state()
            return True
        except Exception as exc:
            self._record_error(spec, f"{type(exc).__name__}: {exc}")
            self.iface.messageBar().pushMessage(
                self.MENU_TITLE,
                f"{row['label']} konnte nicht entfernt werden.",
                level=Qgis.Warning,
                duration=6,
            )
            self._refresh_ui_state()
            return False

    def _open_installed_module(self, spec):
        row = self._build_module_row(spec)
        if not row["is_installed"]:
            return False

        if not row["is_active"]:
            if not self._activate_installed_module(spec, announce=False):
                self.iface.messageBar().pushMessage(
                    self.MENU_TITLE,
                    f"{row['label']} konnte nicht geoeffnet werden, weil das Plugin nicht aktiviert werden konnte.",
                    level=Qgis.Warning,
                    duration=6,
                )
                return False
            row = self._build_module_row(spec)

        plugin_instance = self._loaded_plugin_instance(spec["package"])
        open_method_name = self._resolve_plugin_open_method_name(spec, plugin_instance)
        if plugin_instance is None or not open_method_name:
            self._record_error(spec, "Fuer dieses Plugin ist kein direkter Oeffnen-Einstiegspunkt verfuegbar.")
            self.iface.messageBar().pushMessage(
                self.MENU_TITLE,
                f"{row['label']} bietet derzeit kein direktes Oeffnen aus dem Mastertool an.",
                level=Qgis.Info,
                duration=5,
            )
            self._refresh_ui_state()
            return False

        try:
            getattr(plugin_instance, open_method_name)()
            self._clear_error(spec)
            self._refresh_ui_state()
            return True
        except Exception as exc:
            self._record_error(spec, f"{type(exc).__name__}: {exc}")
            self.iface.messageBar().pushMessage(
                self.MENU_TITLE,
                f"{row['label']} konnte nicht geoeffnet werden.",
                level=Qgis.Warning,
                duration=6,
            )
            self._refresh_ui_state()
            return False

    def _download_archive(self, download_url, destination_path):
        request = urllib.request.Request(
            download_url,
            headers={"User-Agent": self.CATALOG_USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            destination_path.write_bytes(response.read())

    def _extract_plugin_archive(self, archive_path, package_name, extract_root):
        extract_root.mkdir(parents=True, exist_ok=True)

        with ZipFile(archive_path) as archive:
            top_level_entries = []
            for member_name in archive.namelist():
                member_path = Path(member_name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise RuntimeError("ZIP enthaelt ungueltige Pfade.")
                if member_path.parts:
                    top_level_entries.append(member_path.parts[0])

            archive.extractall(extract_root)

        candidate = extract_root / package_name
        if candidate.is_dir():
            return candidate

        unique_roots = [
            entry
            for entry in sorted(set(top_level_entries))
            if entry and entry != "__MACOSX"
        ]
        if len(unique_roots) == 1:
            fallback_candidate = extract_root / unique_roots[0]
            if fallback_candidate.is_dir():
                return fallback_candidate

        raise RuntimeError(
            f"ZIP enthaelt kein Plugin-Verzeichnis fuer {package_name}."
        )

    def _replace_plugin_dir(self, target_dir, source_dir):
        target_dir = Path(target_dir)
        plugins_dir = target_dir.parent
        package_name = target_dir.name
        plugins_dir.mkdir(parents=True, exist_ok=True)

        staged_dir = plugins_dir / f".{package_name}.staged"
        backup_dir = plugins_dir / f".{package_name}.backup"

        shutil.rmtree(staged_dir, ignore_errors=True)
        shutil.rmtree(backup_dir, ignore_errors=True)
        shutil.copytree(source_dir, staged_dir)

        try:
            if target_dir.exists():
                target_dir.replace(backup_dir)
            staged_dir.replace(target_dir)
            shutil.rmtree(backup_dir, ignore_errors=True)
        except Exception:
            shutil.rmtree(staged_dir, ignore_errors=True)
            if backup_dir.exists() and not target_dir.exists():
                backup_dir.replace(target_dir)
            raise

    def _set_plugin_enabled_setting(self, package_name, enabled):
        settings = QSettings()
        settings.setValue(f"PythonPlugins/{package_name}", bool(enabled))

    def _managed_plugins_dir(self):
        home_plugin_path = getattr(qgis_utils, "HOME_PLUGIN_PATH", None)
        if home_plugin_path:
            return Path(home_plugin_path)
        return Path(QgsApplication.qgisSettingsDirPath()) / "python" / "plugins"

    def _target_plugin_dir(self, package_name, plugin_dir=None):
        if self._can_manage_plugin_dir(plugin_dir):
            return Path(plugin_dir)
        return self._managed_plugins_dir() / package_name

    def _can_manage_plugin_dir(self, plugin_dir):
        if plugin_dir is None:
            return False

        plugin_parent = self._normalized_path(Path(plugin_dir).parent)
        if plugin_parent is None:
            return False

        manageable_paths = self._manageable_plugin_dirs()
        return any(self._same_path(plugin_parent, path) for path in manageable_paths)

    def _find_installed_plugin_dir(self, package_name):
        plugin_paths = [str(self._managed_plugins_dir())]
        plugin_paths.extend(list(getattr(qgis_utils, "plugin_paths", []) or []))
        if not plugin_paths:
            plugin_paths = [str(self._managed_plugins_dir())]

        seen_paths = set()
        for plugin_path in plugin_paths:
            normalized_path = str(plugin_path or "").strip()
            if not normalized_path or normalized_path in seen_paths:
                continue
            seen_paths.add(normalized_path)
            candidate = Path(plugin_path) / package_name
            if candidate.is_dir():
                return candidate
        return None

    def _loaded_plugin_instance(self, package_name):
        plugins = getattr(qgis_utils, "plugins", {}) or {}
        return plugins.get(package_name)

    def _can_open_installed_module(self, spec, local_info):
        if not local_info.get("is_installed"):
            return False

        plugin_instance = self._loaded_plugin_instance(spec["package"])
        if self._resolve_plugin_open_method_name(spec, plugin_instance):
            return True

        plugin_dir = local_info.get("plugin_dir")
        if plugin_dir is None:
            return False

        return self._plugin_dir_appears_openable(spec, plugin_dir)

    def _plugin_dir_appears_openable(self, spec, plugin_dir):
        try:
            candidate_names = tuple(self._plugin_open_method_candidates(spec))
            if not candidate_names:
                return False

            for python_path in sorted(Path(plugin_dir).glob("*.py")):
                try:
                    content = python_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    content = python_path.read_text(encoding="latin-1")
                for method_name in candidate_names:
                    if f"def {method_name}(" in content:
                        return True
            return False
        except Exception:
            return False

    def _plugin_open_method_candidates(self, spec):
        package_name = spec["package"]
        package_candidates = self.PACKAGE_OPEN_METHOD_CANDIDATES.get(package_name, ())
        if package_candidates:
            return package_candidates
        return self.DEFAULT_OPEN_METHOD_CANDIDATES

    def _resolve_plugin_open_method_name(self, spec, plugin_instance):
        if plugin_instance is None:
            return ""

        for method_name in self._plugin_open_method_candidates(spec):
            candidate = getattr(plugin_instance, method_name, None)
            if callable(candidate):
                return method_name
        return ""

    def _manageable_plugin_dirs(self):
        settings_root = self._normalized_path(QgsApplication.qgisSettingsDirPath())
        candidates = []
        raw_paths = [self._managed_plugins_dir()]
        raw_paths.extend(list(getattr(qgis_utils, "plugin_paths", []) or []))

        for raw_path in raw_paths:
            normalized_path = self._normalized_path(raw_path)
            if normalized_path is None:
                continue
            if settings_root is not None and not self._is_same_or_descendant(normalized_path, settings_root):
                continue
            if any(self._same_path(normalized_path, existing) for existing in candidates):
                continue
            candidates.append(normalized_path)

        managed_dir = self._normalized_path(self._managed_plugins_dir())
        if managed_dir is not None and not any(
            self._same_path(managed_dir, existing) for existing in candidates
        ):
            candidates.insert(0, managed_dir)

        return candidates

    def _refresh_available_plugins(self):
        updater = getattr(qgis_utils, "updateAvailablePlugins", None)
        if callable(updater):
            try:
                updater()
            except Exception:
                pass

    def _purge_plugin_module_cache(self, package_name):
        removable_names = [
            module_name
            for module_name in list(sys.modules)
            if module_name == package_name or module_name.startswith(f"{package_name}.")
        ]
        for module_name in removable_names:
            sys.modules.pop(module_name, None)
        importlib.invalidate_caches()

    def _record_error(self, spec, message):
        self.module_action_errors[spec["key"]] = str(message or "").strip()

    def _clear_error(self, spec):
        self.module_action_errors.pop(spec["key"], None)

    def _show_startup_message(self):
        message = "Master-Katalog aktiv."
        if self.catalog_refresh_error:
            message += " Online-Index derzeit nicht erreichbar, lokaler Snapshot wird verwendet."

        self.iface.messageBar().pushMessage(
            self.MENU_TITLE,
            message,
            level=Qgis.Warning if self.catalog_refresh_error else Qgis.Info,
            duration=6 if self.catalog_refresh_error else 4,
        )

    def _refresh_overview_dialog(self):
        if self.overview_dialog is not None:
            self.overview_dialog.refresh()

    def _refresh_ui_state(self):
        self._refresh_overview_dialog()

    def _sync_shared_settings(self, config=None):
        settings = config or self.get_shared_settings()
        sync_attribution_butler_settings(settings)

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

    def _spec_by_key(self, key):
        for spec in BUNDLED_PLUGINS:
            if spec["key"] == key:
                return spec
        return None

    def _get_module_metadata(self, spec):
        metadata_path = (
            self.plugin_dir.parent
            / "plugin_sources"
            / spec["source_path"]
            / "metadata.txt"
        )
        if metadata_path.is_file():
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str
            for encoding in ("utf-8", "latin-1"):
                try:
                    with metadata_path.open(encoding=encoding) as handle:
                        parser.read_file(handle)
                    break
                except UnicodeDecodeError:
                    parser = configparser.ConfigParser(interpolation=None)
                    parser.optionxform = str
                    continue
            if parser.has_section("general"):
                return {
                    key: value.strip()
                    for key, value in parser.items("general")
                }
        return {}

    def _resolve_module_icon_path(self, spec, catalog_entry):
        icon_relative_path = str(catalog_entry.get("icon_relative_path") or "").strip()
        if icon_relative_path:
            candidate = self.plugin_dir / "catalog" / icon_relative_path
            if candidate.is_file():
                return str(candidate)

        source_dir = self.plugin_dir.parent / "plugin_sources" / spec["source_path"]
        metadata = catalog_entry.get("metadata", {})
        explicit_icon = source_dir / str(metadata.get("icon") or "").strip()
        if explicit_icon.is_file():
            return str(explicit_icon)

        for fallback_name in ("icon.svg", "icon.png", "icon.ico"):
            fallback_icon = source_dir / fallback_name
            if fallback_icon.is_file():
                return str(fallback_icon)

        return str(self.plugin_dir / "icon.svg")

    def _resolve_raw_base_url_from_metadata(self):
        metadata = self._master_metadata()
        repository_url = (
            metadata.get("repository")
            or metadata.get("homepage")
            or ""
        )
        match = re.search(
            r"github\.com[:/](?P<slug>[^/]+/[^/.]+)(?:\.git)?/?$",
            str(repository_url),
        )
        if not match:
            return ""
        return f"https://raw.githubusercontent.com/{match.group('slug')}/main"

    def _master_metadata(self):
        metadata_path = self.plugin_dir / "metadata.txt"
        if not metadata_path.is_file():
            return {}

        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        with metadata_path.open(encoding="utf-8") as handle:
            parser.read_file(handle)
        if not parser.has_section("general"):
            return {}
        return {
            key: value.strip()
            for key, value in parser.items("general")
        }

    def _metadata_value(self, metadata_path, key):
        if not metadata_path.is_file():
            return ""

        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        for encoding in ("utf-8", "latin-1"):
            try:
                with metadata_path.open(encoding=encoding) as handle:
                    parser.read_file(handle)
                break
            except UnicodeDecodeError:
                parser = configparser.ConfigParser(interpolation=None)
                parser.optionxform = str
                continue

        if not parser.has_section("general"):
            return ""

        try:
            return parser.get("general", key).strip()
        except Exception:
            return ""

    def _sanitize_favorite_module_keys(self, keys):
        valid_keys = {spec["key"] for spec in BUNDLED_PLUGINS}
        normalized = []
        seen = set()

        for key in keys:
            text = str(key or "").strip()
            if not text or text not in valid_keys or text in seen:
                continue
            normalized.append(text)
            seen.add(text)

        return normalized

    def _split_tags(self, raw_tags):
        if not raw_tags:
            return []

        return [
            tag.strip()
            for tag in str(raw_tags).replace(";", ",").split(",")
            if tag.strip()
        ]

    def _metadata_bool(self, metadata, key):
        value = str((metadata or {}).get(key, "")).strip().lower()
        return value in {"1", "true", "yes", "on"}

    def _compare_versions(self, left, right):
        left_key = self._version_key(left)
        right_key = self._version_key(right)

        for left_part, right_part in zip_longest(left_key, right_key, fillvalue=(0, 0)):
            if left_part < right_part:
                return -1
            if left_part > right_part:
                return 1
        return 0

    def _version_key(self, value):
        tokens = re.findall(r"\d+|[A-Za-z]+", str(value or ""))
        if not tokens:
            return [(0, 0)]

        key = []
        for token in tokens:
            if token.isdigit():
                key.append((0, int(token)))
            else:
                key.append((1, token.lower()))
        return key

    def _xml_text(self, element, tag_name):
        child = element.find(tag_name)
        if child is None or child.text is None:
            return ""
        return child.text.strip()

    def _normalized_path(self, path):
        if path is None:
            return None
        try:
            return Path(path).expanduser().resolve()
        except Exception:
            try:
                return Path(path).expanduser()
            except Exception:
                return None

    def _same_path(self, left, right):
        left_path = self._normalized_path(left)
        right_path = self._normalized_path(right)
        if left_path is None or right_path is None:
            return False
        return left_path == right_path

    def _is_same_or_descendant(self, path, parent):
        normalized_path = self._normalized_path(path)
        normalized_parent = self._normalized_path(parent)
        if normalized_path is None or normalized_parent is None:
            return False

        try:
            normalized_path.relative_to(normalized_parent)
            return True
        except ValueError:
            return False

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
