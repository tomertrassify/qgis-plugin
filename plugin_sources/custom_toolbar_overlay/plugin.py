# -*- coding: utf-8 -*-

from datetime import datetime
import json
import os
import re

from qgis.PyQt import sip
from qgis.PyQt.QtCore import (
    QByteArray,
    QCoreApplication,
    QEvent,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QTimer,
)
from qgis.PyQt.QtGui import QAction, QIcon, QImage, QKeySequence, QPainter, QPixmap
from qgis.PyQt.QtSvg import QSvgRenderer
from qgis.PyQt.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QToolBar,
    QToolButton,
    QWidget,
    QWidgetAction,
)

from .overlay import ToolbarOverlayDialog


def clean_ui_text(value):
    text = str(value or "")
    text = text.replace("&", " ")
    text = text.replace("...", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


class StaticProxyAction(QAction):
    def __init__(
        self,
        source_action,
        parent=None,
        text_override=None,
        state_widget=None,
        state_widget_resolver=None,
    ):
        super().__init__(parent)
        self._source_action = source_action
        self._text_override = clean_ui_text(text_override)
        self._state_widget = state_widget
        self._state_widget_resolver = state_widget_resolver

        self.triggered.connect(self._trigger_source_action)
        if self._source_action is not None:
            self._source_action.changed.connect(self._sync_state_from_source)
            try:
                self._source_action.toggled.connect(self._sync_checked_state)
            except Exception:
                pass
            try:
                self._source_action.destroyed.connect(self._handle_source_destroyed)
            except Exception:
                pass
        if self._state_widget is not None:
            try:
                self._state_widget.installEventFilter(self)
            except Exception:
                self._state_widget = None
            else:
                try:
                    self._state_widget.destroyed.connect(
                        self._handle_state_widget_destroyed
                    )
                except Exception:
                    pass
        self._apply_snapshot_from_source()

    def _apply_snapshot_from_source(self):
        if self._source_action is None:
            self.setEnabled(False)
            return

        try:
            label = self._text_override or clean_ui_text(
                self._source_action.iconText()
                or self._source_action.text()
                or self._source_action.toolTip()
                or self._source_action.statusTip()
                or self._source_action.objectName()
            )
            tooltip = clean_ui_text(
                self._source_action.toolTip()
                or self._source_action.text()
                or label
            )
            status_tip = clean_ui_text(
                self._source_action.statusTip()
                or self._source_action.toolTip()
                or self._source_action.text()
                or label
            )

            self.setCheckable(bool(self._source_action.isCheckable()))
            self.setChecked(bool(self._source_action.isChecked()))
            self.setEnabled(self._effective_source_enabled())
            self.setIcon(self._effective_source_icon())
            self.setText(label)
            self.setIconText(label)
            self.setToolTip(tooltip)
            self.setStatusTip(status_tip)
        except RuntimeError:
            self._handle_source_destroyed()

    def _sync_state_from_source(self):
        self._apply_snapshot_from_source()

    def _sync_checked_state(self, checked):
        if self._source_action is None:
            return
        try:
            if self.isCheckable():
                self.setChecked(bool(checked))
        except RuntimeError:
            self._handle_source_destroyed()

    def _trigger_source_action(self, checked=False):
        del checked
        if self._source_action is None:
            return
        try:
            if not self._effective_source_enabled():
                return
            self._source_action.trigger()
            if self.isCheckable():
                self.setChecked(bool(self._source_action.isChecked()))
        except RuntimeError:
            self._handle_source_destroyed()

    def _effective_source_enabled(self):
        if self._source_action is None:
            return False
        try:
            if not self._source_action.isEnabled():
                return False
        except RuntimeError:
            self._handle_source_destroyed()
            return False

        state_widget = self._resolved_state_widget()
        if state_widget is None:
            return True
        try:
            return bool(state_widget.isEnabled())
        except RuntimeError:
            self._handle_state_widget_destroyed()
            return True

    def _effective_source_icon(self):
        state_widget = self._resolved_state_widget()
        if isinstance(state_widget, QToolButton):
            try:
                icon = state_widget.icon()
            except RuntimeError:
                self._handle_state_widget_destroyed()
                icon = QIcon()
            except Exception:
                icon = QIcon()
            if not icon.isNull():
                return icon

        if self._source_action is None:
            return QIcon()
        try:
            return self._source_action.icon()
        except RuntimeError:
            self._handle_source_destroyed()
            return QIcon()

    def _resolved_state_widget(self):
        if self._state_widget is not None:
            return self._state_widget
        if not callable(self._state_widget_resolver):
            return None
        try:
            self._state_widget = self._state_widget_resolver()
        except Exception:
            self._state_widget = None
        return self._state_widget

    def _handle_state_widget_destroyed(self, *args):
        del args
        self._state_widget = None
        self._apply_snapshot_from_source()

    def eventFilter(self, watched, event):
        if watched is self._state_widget and event is not None:
            if event.type() == QEvent.EnabledChange:
                self._sync_state_from_source()
        return super().eventFilter(watched, event)

    def _handle_source_destroyed(self, *args):
        del args
        self._source_action = None
        self.setEnabled(False)


class CustomToolbarOverlayPlugin:
    SETTINGS_ROOT = "custom_toolbar_overlay"
    SETTINGS_TOOLBARS = SETTINGS_ROOT + "/toolbars"
    SETTINGS_HIDDEN_TOOLBARS = SETTINGS_ROOT + "/hidden_toolbars"
    SETTINGS_BRANDING_ENABLED = SETTINGS_ROOT + "/branding_enabled"
    SETTINGS_SHOW_PLUGIN_BUTTON = SETTINGS_ROOT + "/show_plugin_button"
    SETTINGS_LAYOUT_STATE = SETTINGS_ROOT + "/layout_state"
    PRESET_DIRECTORY_NAME = "presets"
    LAYOUT_STATE_VERSION = 1

    MANAGED_TOOLBAR_PREFIX = "customToolbarOverlayToolbar::"
    MANAGED_TOOLBAR_PROPERTY = "customToolbarOverlayManaged"
    MANAGED_TOOLBAR_ID_PROPERTY = "customToolbarOverlayManagedToolbarId"
    MANAGED_WIDGET_ACTION_PROPERTY = "customToolbarOverlayManagedWidgetAction"
    TOOLBAR_SYNC_CONNECTED_PROPERTY = "customToolbarOverlaySyncConnected"
    BRANDING_TOOLBAR_OBJECT_NAME = "customToolbarOverlayBrandingToolbar"
    PLUGIN_ACTION_OBJECT_NAME = "actionCustomToolbarOverlayManager"

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.settings = QSettings()

        self.menu_name = self.tr("&Custom Toolbar Overlay")
        self.action = None
        self.debug_action = None

        self.toolbar_definitions = []
        self.hidden_native_toolbar_ids = set()
        self.branding_enabled = False
        self.show_plugin_toolbar_button = True

        self._managed_toolbars = {}
        self._branding_toolbar = None
        self._plugin_toolbar_icon_added = False
        self._ignore_toolbar_visibility_events = False
        self._saved_layout_state = None
        self._layout_state_restored = False

        self._load_settings()

    def tr(self, message):
        return QCoreApplication.translate("CustomToolbarOverlayPlugin", message)

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.svg")
        self.action = QAction(
            QIcon(icon_path),
            self.tr("Eigene Werkzeugleisten konfigurieren"),
            self.iface.mainWindow(),
        )
        self.action.setObjectName(self.PLUGIN_ACTION_OBJECT_NAME)
        self.action.setShortcut(QKeySequence("Ctrl+Alt+T"))
        self.action.setStatusTip(
            self.tr("Dialog zum Verwalten eigener Werkzeugleisten oeffnen")
        )
        self.action.triggered.connect(self.show_overlay)

        self.debug_action = QAction(
            self.tr("Toolbar-Debug exportieren"),
            self.iface.mainWindow(),
        )
        self.debug_action.setObjectName(
            "actionCustomToolbarOverlayDebugExport"
        )
        self.debug_action.setStatusTip(
            self.tr("Interne QGIS-Toolbar-Struktur als JSON exportieren")
        )
        self.debug_action.triggered.connect(self.export_debug_snapshot)

        self.iface.addPluginToMenu(self.menu_name, self.action)
        self.iface.addPluginToMenu(self.menu_name, self.debug_action)
        try:
            self.iface.registerMainWindowAction(self.action, "")
        except Exception:
            pass

        self._apply_plugin_toolbar_button_visibility()
        self._install_toolbar_sync_hooks()

        QTimer.singleShot(0, self.apply_configuration)
        QTimer.singleShot(1500, self.apply_configuration)

    def unload(self):
        self._ignore_toolbar_visibility_events = True
        try:
            self._save_layout_state()
            self._remove_managed_toolbars()
            self._remove_branding_toolbar()
            self._restore_native_toolbars()
            self._remove_plugin_toolbar_icon()
        finally:
            self._ignore_toolbar_visibility_events = False

        if self.action is not None:
            try:
                self.iface.unregisterMainWindowAction(self.action)
            except Exception:
                pass
            self.iface.removePluginMenu(self.menu_name, self.action)
            self.action.deleteLater()
            self.action = None
        if self.debug_action is not None:
            self.iface.removePluginMenu(self.menu_name, self.debug_action)
            self.debug_action.deleteLater()
            self.debug_action = None

    def show_overlay(self):
        self._sync_settings_from_qgis(save=True)
        dialog = ToolbarOverlayDialog(
            parent=self.iface.mainWindow(),
            available_actions=self._available_actions(),
            native_toolbars=self._available_native_toolbars(),
            native_toolbar_templates=self._available_native_toolbar_templates(),
            toolbar_definitions=self.toolbar_definitions,
            hidden_toolbar_ids=self.hidden_native_toolbar_ids,
            built_in_presets=self._available_presets(),
            branding_enabled=self.branding_enabled,
            show_plugin_toolbar_button=self.show_plugin_toolbar_button,
        )
        if dialog.exec():
            self.toolbar_definitions = dialog.toolbar_definitions()
            self.hidden_native_toolbar_ids = set(dialog.hidden_toolbar_ids())
            self.branding_enabled = dialog.branding_enabled()
            self.show_plugin_toolbar_button = dialog.show_plugin_toolbar_button()
            self._save_settings()
            self.apply_configuration()

    def export_debug_snapshot(self):
        suggested_path = os.path.join(
            os.path.expanduser("~"),
            "custom-toolbar-overlay-debug.json",
        )
        file_path, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            self.tr("Toolbar-Debug exportieren"),
            suggested_path,
            "JSON (*.json)",
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".json"):
            file_path += ".json"

        payload = self._debug_payload()
        try:
            with open(file_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=True)
                handle.write("\n")
        except Exception as exc:
            QMessageBox.critical(
                self.iface.mainWindow(),
                self.tr("Toolbar-Debug exportieren"),
                self.tr("Die Debug-Datei konnte nicht geschrieben werden:\n{}").format(
                    exc
                ),
            )
            return

        QMessageBox.information(
            self.iface.mainWindow(),
            self.tr("Toolbar-Debug exportiert"),
            self.tr(
                "Die Debug-Datei wurde gespeichert unter:\n{}\n\nSchick mir diese JSON-Datei, dann kann ich die problematischen QGIS-Sonderbuttons gezielt nachbauen."
            ).format(file_path),
        )

    def apply_configuration(self):
        self._ignore_toolbar_visibility_events = True
        try:
            migrated = self._migrate_toolbar_definitions_to_stable_native_dropdown_ids()
            self._apply_plugin_toolbar_button_visibility()
            self._apply_native_toolbar_visibility()
            self._apply_custom_toolbars()
            self._apply_branding_toolbar()
            self._install_toolbar_sync_hooks()
            self._restore_layout_state_if_needed()
            self._save_layout_state()
            if migrated:
                self._save_settings()
        finally:
            self._ignore_toolbar_visibility_events = False

    def _load_settings(self):
        toolbars_raw = self._read_json_setting(self.SETTINGS_TOOLBARS, [])
        hidden_raw = self._read_json_setting(self.SETTINGS_HIDDEN_TOOLBARS, [])

        self.toolbar_definitions = self._normalize_toolbar_definitions(toolbars_raw)
        self.hidden_native_toolbar_ids = {
            str(toolbar_id).strip()
            for toolbar_id in hidden_raw
            if str(toolbar_id).strip()
        }

        legacy_branding = any(
            self._is_logo_only_toolbar_definition(definition)
            for definition in self.toolbar_definitions
        )
        if legacy_branding:
            self.toolbar_definitions = [
                definition
                for definition in self.toolbar_definitions
                if not self._is_logo_only_toolbar_definition(definition)
            ]

        self.branding_enabled = self._read_bool_setting(
            self.SETTINGS_BRANDING_ENABLED,
            legacy_branding,
        )
        self.show_plugin_toolbar_button = self._read_bool_setting(
            self.SETTINGS_SHOW_PLUGIN_BUTTON,
            True,
        )
        self._saved_layout_state = self._read_bytearray_setting(
            self.SETTINGS_LAYOUT_STATE
        )

    def _save_settings(self):
        self.settings.setValue(
            self.SETTINGS_TOOLBARS,
            json.dumps(self.toolbar_definitions, ensure_ascii=True),
        )
        self.settings.setValue(
            self.SETTINGS_HIDDEN_TOOLBARS,
            json.dumps(sorted(self.hidden_native_toolbar_ids), ensure_ascii=True),
        )
        self.settings.setValue(
            self.SETTINGS_BRANDING_ENABLED,
            bool(self.branding_enabled),
        )
        self.settings.setValue(
            self.SETTINGS_SHOW_PLUGIN_BUTTON,
            bool(self.show_plugin_toolbar_button),
        )

    def _read_json_setting(self, key, default):
        raw_value = self.settings.value(key, None)
        if raw_value in (None, ""):
            return default
        if isinstance(raw_value, (list, dict)):
            return raw_value
        try:
            return json.loads(raw_value)
        except Exception:
            return default

    def _read_bool_setting(self, key, default):
        raw_value = self.settings.value(key, default)
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, (int, float)):
            return bool(raw_value)
        value = str(raw_value or "").strip().lower()
        if value in ("1", "true", "yes", "on"):
            return True
        if value in ("0", "false", "no", "off"):
            return False
        return bool(default)

    def _read_bytearray_setting(self, key):
        try:
            value = self.settings.value(
                key,
                QByteArray(),
                type=QByteArray,
            )
        except TypeError:
            value = self.settings.value(key, QByteArray())

        if isinstance(value, QByteArray):
            return value if not value.isEmpty() else None
        return value or None

    def _available_actions(self):
        return [
            {
                "id": entry["id"],
                "label": entry["label"],
                "sources": list(entry.get("sources", [])),
                "is_native_dropdown": bool(
                    entry.get("menu") is not None or entry.get("menu_actions")
                ),
            }
            for entry in self._collect_available_action_entries()
        ]

    def _debug_payload(self):
        return {
            "generated_at": datetime.now().isoformat(),
            "plugin_version": "0.3.22",
            "main_window_class": self.iface.mainWindow().__class__.__name__,
            "native_toolbars": [
                self._debug_toolbar_snapshot(toolbar)
                for toolbar in self._iter_native_toolbars()
            ],
        }

    def _debug_toolbar_snapshot(self, toolbar):
        return {
            "label": self._toolbar_label(toolbar),
            "object_name": toolbar.objectName(),
            "class": toolbar.__class__.__name__,
            "visible": bool(toolbar.isVisible()),
            "actions": [
                self._debug_toolbar_action_snapshot(toolbar, toolbar_action)
                for toolbar_action in toolbar.actions()
            ],
        }

    def _debug_toolbar_action_snapshot(self, toolbar, toolbar_action):
        binding = self._toolbar_action_binding(toolbar, toolbar_action)
        widget = self._widget_for_toolbar_action(toolbar, toolbar_action)
        source_label = self._toolbar_label(toolbar)

        resolved_action = binding.get("action") if binding else None
        resolved_menu = binding.get("menu") if binding else None
        resolved_state_widget = binding.get("state_widget") if binding else None

        return {
            "toolbar_action": self._debug_action_snapshot(toolbar_action),
            "toolbar_action_class": toolbar_action.__class__.__name__
            if toolbar_action is not None
            else None,
            "is_widget_action": bool(
                isinstance(toolbar_action, QWidgetAction)
            ),
            "widget": self._debug_widget_snapshot(widget),
            "resolved_binding": {
                "action": self._debug_action_snapshot(resolved_action),
                "storage_id": self._action_storage_id(
                    resolved_action,
                    source_label,
                    [],
                )
                if resolved_action is not None
                else None,
                "menu": self._debug_menu_snapshot(resolved_menu),
                "state_widget": self._debug_widget_snapshot(
                    resolved_state_widget
                ),
                "is_supported_root_action": bool(
                    resolved_action is not None
                    and self._is_supported_root_action(
                        resolved_action,
                        resolved_menu,
                    )
                ),
            }
            if binding is not None
            else None,
        }

    def _debug_action_snapshot(self, action):
        if action is None:
            return None
        try:
            associated_widgets_getter = getattr(action, "associatedWidgets", None)
            if callable(associated_widgets_getter):
                associated_widgets = [
                    self._debug_widget_brief(widget)
                    for widget in associated_widgets_getter()
                    if widget is not None
                ]
            else:
                associated_widgets = []
        except Exception:
            associated_widgets = []

        return {
            "class": action.__class__.__name__,
            "object_name": action.objectName(),
            "text": self._clean_text(action.text()),
            "icon_text": self._clean_text(action.iconText()),
            "tool_tip": self._clean_text(action.toolTip()),
            "status_tip": self._clean_text(action.statusTip()),
            "enabled": bool(action.isEnabled()),
            "visible": bool(action.isVisible()),
            "checkable": bool(action.isCheckable()),
            "checked": bool(action.isChecked()),
            "separator": bool(action.isSeparator()),
            "associated_widgets": associated_widgets,
        }

    def _debug_widget_brief(self, widget):
        if widget is None:
            return None
        return {
            "class": widget.__class__.__name__,
            "object_name": widget.objectName(),
            "enabled": bool(widget.isEnabled()),
            "visible": bool(widget.isVisible()),
        }

    def _debug_widget_snapshot(self, widget):
        if widget is None:
            return None

        toolbuttons = []
        for button in self._toolbuttons_for_widget(widget):
            toolbuttons.append(
                {
                    "class": button.__class__.__name__,
                    "object_name": button.objectName(),
                    "enabled": bool(button.isEnabled()),
                    "visible": bool(button.isVisible()),
                    "text": self._clean_text(button.text()),
                    "tool_tip": self._clean_text(button.toolTip()),
                    "popup_mode": int(button.popupMode()),
                    "default_action": self._debug_action_snapshot(
                        button.defaultAction()
                    ),
                    "menu": self._debug_menu_snapshot(button.menu()),
                }
            )

        return {
            "class": widget.__class__.__name__,
            "object_name": widget.objectName(),
            "enabled": bool(widget.isEnabled()),
            "visible": bool(widget.isVisible()),
            "window_title": self._clean_text(
                getattr(widget, "windowTitle", lambda: "")()
            )
            if hasattr(widget, "windowTitle")
            else "",
            "toolbuttons": toolbuttons,
        }

    def _debug_menu_snapshot(self, menu, depth=0, max_depth=2):
        if menu is None:
            return None

        snapshot = {
            "class": menu.__class__.__name__,
            "object_name": menu.objectName(),
            "title": self._clean_text(menu.title()),
            "actions": [],
        }
        if depth >= max_depth:
            return snapshot

        for action in menu.actions():
            if action is None:
                continue
            try:
                submenu = action.menu()
            except Exception:
                submenu = None
            snapshot["actions"].append(
                {
                    "action": self._debug_action_snapshot(action),
                    "submenu": self._debug_menu_snapshot(
                        submenu,
                        depth=depth + 1,
                        max_depth=max_depth,
                    )
                    if submenu is not None
                    else None,
                }
            )
        return snapshot

    def _available_native_toolbars(self):
        toolbars = []
        for toolbar in self._iter_native_toolbars():
            object_name = toolbar.objectName().strip()
            if not object_name:
                continue
            toolbars.append(
                {
                    "id": object_name,
                    "label": self._toolbar_label(toolbar),
                    "visible": toolbar.isVisible(),
                }
            )
        toolbars.sort(key=lambda entry: entry["label"].lower())
        return toolbars

    def _available_native_toolbar_templates(self):
        action_entries = self._collect_available_action_entries()
        action_entry_lookup = {
            entry["id"]: entry for entry in action_entries
        }

        templates = []
        for toolbar in self._iter_native_toolbars():
            object_name = toolbar.objectName().strip()
            if not object_name:
                continue

            items = self._native_toolbar_template_items(
                toolbar,
                action_entry_lookup,
            )
            if not items:
                continue

            templates.append(
                {
                    "id": object_name,
                    "label": self._toolbar_label(toolbar),
                    "actions": items,
                }
            )

        templates.sort(key=lambda entry: entry["label"].lower())
        return templates

    def _apply_plugin_toolbar_button_visibility(self):
        if self.action is None:
            return

        if self.show_plugin_toolbar_button and not self._plugin_toolbar_icon_added:
            self.iface.addToolBarIcon(self.action)
            self._plugin_toolbar_icon_added = True
            return

        if not self.show_plugin_toolbar_button and self._plugin_toolbar_icon_added:
            self._remove_plugin_toolbar_icon()

    def _remove_plugin_toolbar_icon(self):
        if self.action is None or not self._plugin_toolbar_icon_added:
            return
        self.iface.removeToolBarIcon(self.action)
        self._plugin_toolbar_icon_added = False

    def _apply_native_toolbar_visibility(self):
        hidden_ids = set(self.hidden_native_toolbar_ids)
        for toolbar in self._iter_native_toolbars():
            object_name = toolbar.objectName().strip()
            if not object_name:
                continue
            toolbar.setVisible(object_name not in hidden_ids)

    def _apply_custom_toolbars(self):
        action_ids = self._collect_referenced_action_ids(self.toolbar_definitions)
        action_lookup = self._resolve_action_lookup(action_ids)
        main_window = self.iface.mainWindow()

        next_managed = {}
        for definition in self.toolbar_definitions:
            toolbar = self._managed_toolbars.get(definition["id"])
            is_new_toolbar = toolbar is None
            if toolbar is None:
                toolbar = QToolBar(definition["title"], main_window)
                toolbar.setObjectName(
                    self.MANAGED_TOOLBAR_PREFIX + definition["id"]
                )
                toolbar.setProperty(self.MANAGED_TOOLBAR_PROPERTY, True)
                toolbar.setFloatable(False)
                toolbar.setMovable(True)
                toolbar.setProperty(
                    self.MANAGED_TOOLBAR_ID_PROPERTY,
                    definition["id"],
                )

            toolbar.setWindowTitle(definition["title"])
            toolbar.setProperty(
                self.MANAGED_TOOLBAR_ID_PROPERTY,
                definition["id"],
            )
            self._clear_toolbar(toolbar)

            for item in definition["actions"]:
                item_type = item["type"]
                if item_type == "separator":
                    toolbar.addSeparator()
                    continue
                if item_type == "logo":
                    self._add_logo_widget(toolbar, item, left_padding=8)
                    continue
                if item_type == "dropdown":
                    self._add_dropdown_button(toolbar, item, action_lookup)
                    continue

                entry = action_lookup.get(item["id"])
                if entry is None:
                    continue
                if entry.get("menu") is not None or entry.get("menu_actions"):
                    self._add_native_dropdown_button(toolbar, entry)
                    continue
                if entry.get("action") is not None:
                    self._add_shared_action_button(toolbar, entry)

            if is_new_toolbar:
                main_window.addToolBar(Qt.TopToolBarArea, toolbar)
            toolbar.setVisible(bool(definition.get("visible", True)))
            next_managed[definition["id"]] = toolbar

        removed_ids = set(self._managed_toolbars) - set(next_managed)
        for toolbar_id in removed_ids:
            toolbar = self._managed_toolbars[toolbar_id]
            main_window.removeToolBar(toolbar)
            toolbar.deleteLater()

        self._managed_toolbars = next_managed

    def _apply_branding_toolbar(self):
        if not self.branding_enabled:
            self._remove_branding_toolbar()
            return

        main_window = self.iface.mainWindow()
        if self._branding_toolbar is None:
            self._branding_toolbar = QToolBar(self.tr("Branding"), main_window)
            self._branding_toolbar.setObjectName(self.BRANDING_TOOLBAR_OBJECT_NAME)
            self._branding_toolbar.setProperty(self.MANAGED_TOOLBAR_PROPERTY, True)
            self._branding_toolbar.setFloatable(False)
            self._branding_toolbar.setMovable(False)

        toolbar = self._branding_toolbar
        main_window.removeToolBar(toolbar)
        toolbar.setWindowTitle(self.tr("Branding"))
        self._clear_toolbar(toolbar)
        self._add_logo_widget(
            toolbar,
            {
                "type": "logo",
                "path": "logo.svg",
                "label": "Branding",
                "height": 28,
            },
            left_padding=18,
        )

        anchor_toolbar = self._first_top_level_toolbar(exclude_toolbar=toolbar)
        if anchor_toolbar is not None:
            main_window.insertToolBar(anchor_toolbar, toolbar)
        else:
            main_window.addToolBar(Qt.TopToolBarArea, toolbar)
        toolbar.setVisible(True)

    def _remove_branding_toolbar(self):
        if self._branding_toolbar is None:
            return
        self.iface.mainWindow().removeToolBar(self._branding_toolbar)
        self._branding_toolbar.deleteLater()
        self._branding_toolbar = None

    def _install_toolbar_sync_hooks(self):
        for toolbar in self._iter_native_toolbars():
            self._connect_toolbar_visibility_signal(toolbar)
        for toolbar in self._managed_toolbars.values():
            self._connect_toolbar_visibility_signal(toolbar)
        if self._branding_toolbar is not None:
            self._connect_toolbar_visibility_signal(self._branding_toolbar)

    def _connect_toolbar_visibility_signal(self, toolbar):
        if toolbar is None:
            return
        if bool(toolbar.property(self.TOOLBAR_SYNC_CONNECTED_PROPERTY)):
            return

        toolbar.visibilityChanged.connect(
            lambda visible, tb=toolbar: self._on_toolbar_visibility_changed(
                tb, visible
            )
        )
        toolbar.setProperty(self.TOOLBAR_SYNC_CONNECTED_PROPERTY, True)

    def _on_toolbar_visibility_changed(self, toolbar, visible):
        del visible
        if self._ignore_toolbar_visibility_events or toolbar is None:
            return

        changed = False
        if toolbar is self._branding_toolbar:
            is_visible = bool(toolbar.isVisible())
            if self.branding_enabled != is_visible:
                self.branding_enabled = is_visible
                changed = True
        elif self._is_managed_toolbar(toolbar):
            toolbar_id = str(
                toolbar.property(self.MANAGED_TOOLBAR_ID_PROPERTY) or ""
            ).strip()
            definition = self._definition_by_managed_toolbar_id(toolbar_id)
            if definition is not None:
                is_visible = bool(toolbar.isVisible())
                if bool(definition.get("visible", True)) != is_visible:
                    definition["visible"] = is_visible
                    changed = True
        else:
            toolbar_id = toolbar.objectName().strip()
            if toolbar_id:
                is_hidden = not bool(toolbar.isVisible())
                if is_hidden and toolbar_id not in self.hidden_native_toolbar_ids:
                    self.hidden_native_toolbar_ids.add(toolbar_id)
                    changed = True
                elif not is_hidden and toolbar_id in self.hidden_native_toolbar_ids:
                    self.hidden_native_toolbar_ids.discard(toolbar_id)
                    changed = True

        if changed:
            self._save_settings()

    def _sync_settings_from_qgis(self, save):
        changed = False

        current_hidden_native = set()
        for toolbar in self._iter_native_toolbars():
            toolbar_id = toolbar.objectName().strip()
            if toolbar_id and not toolbar.isVisible():
                current_hidden_native.add(toolbar_id)
        if current_hidden_native != self.hidden_native_toolbar_ids:
            self.hidden_native_toolbar_ids = current_hidden_native
            changed = True

        for toolbar in self._managed_toolbars.values():
            toolbar_id = str(
                toolbar.property(self.MANAGED_TOOLBAR_ID_PROPERTY) or ""
            ).strip()
            definition = self._definition_by_managed_toolbar_id(toolbar_id)
            if definition is None:
                continue
            is_visible = bool(toolbar.isVisible())
            if bool(definition.get("visible", True)) != is_visible:
                definition["visible"] = is_visible
                changed = True

        if self._branding_toolbar is not None:
            is_visible = bool(self._branding_toolbar.isVisible())
            if self.branding_enabled != is_visible:
                self.branding_enabled = is_visible
                changed = True

        if changed and save:
            self._save_settings()

        return changed

    def _collect_referenced_action_ids(self, toolbar_definitions):
        action_ids = set()
        for definition in toolbar_definitions:
            for item in definition.get("actions", []):
                item_type = item.get("type")
                if item_type == "action":
                    action_ids.add(item["id"])
                    continue
                if item_type == "dropdown":
                    for action_id in item.get("actions", []):
                        action_ids.add(action_id)
        return action_ids

    def _resolve_action_lookup(self, action_ids):
        action_lookup = {}
        remaining_ids = set(action_ids)
        if not remaining_ids:
            return action_lookup

        for entry in self._collect_available_action_entries():
            action_id = entry["id"]
            if action_id in remaining_ids:
                action_lookup[action_id] = entry
                remaining_ids.discard(action_id)
                if not remaining_ids:
                    break
        return action_lookup

    def _migrate_toolbar_definitions_to_stable_native_dropdown_ids(self):
        entries = self._collect_available_action_entries()
        if not entries:
            return False

        direct_lookup = {entry["id"]: entry for entry in entries}
        alias_lookup = {}
        for entry in entries:
            if entry.get("menu") is None and not entry.get("menu_actions"):
                continue
            for alias_id in entry.get("legacy_alias_ids", []):
                alias_lookup.setdefault(alias_id, entry["id"])

        changed = False
        for definition in self.toolbar_definitions:
            for item in definition.get("actions", []):
                if item.get("type") != "action":
                    continue
                item_id = str(item.get("id") or "").strip()
                if not item_id:
                    continue
                root_id = alias_lookup.get(item_id)
                if not root_id or root_id == item_id:
                    continue
                direct_entry = direct_lookup.get(item_id)
                if direct_entry is not None and (
                    direct_entry.get("menu") is not None
                    or direct_entry.get("menu_actions")
                ):
                    continue
                item["id"] = root_id
                changed = True

        return changed

    def _collect_available_action_entries(self):
        action_map = {}

        for toolbar in self._iter_native_toolbars():
            source_label = self._toolbar_label(toolbar)
            for toolbar_action in toolbar.actions():
                binding = self._toolbar_action_binding(toolbar, toolbar_action)
                if binding is None:
                    continue

                action = binding["action"]
                menu = binding["menu"]
                state_widget = binding["state_widget"]
                if not self._is_supported_root_action(action, menu):
                    continue

                storage_id = self._root_action_storage_id(
                    toolbar,
                    toolbar_action,
                    action,
                    menu,
                    source_label,
                )
                self._register_action_entry(
                    action_map,
                    action,
                    source_label,
                    path_parts=[],
                    storage_id=storage_id,
                )
                self._attach_state_widget_to_action_entry(
                    action_map,
                    action,
                    source_label,
                    path_parts=[],
                    state_widget=state_widget,
                    storage_id=storage_id,
                )

                if menu is None:
                    continue
                self._attach_menu_to_action_entry(
                    action_map,
                    action,
                    source_label,
                    path_parts=[],
                    menu=menu,
                    storage_id=storage_id,
                )
                self._attach_aliases_to_action_entry(
                    action_map,
                    action,
                    source_label,
                    path_parts=[],
                    alias_ids=self._native_dropdown_alias_ids(menu),
                    storage_id=storage_id,
                )

                root_label = self._action_label(action)
                root_path = [root_label] if root_label else []
                self._register_menu_actions(
                    action_map,
                    menu,
                    source_label,
                    root_path,
                )

        for action in self.iface.mainWindow().findChildren(QAction):
            menu = self._menu_for_action(action)
            if not self._is_supported_root_action(action, menu):
                continue
            if self._special_native_dropdown_storage_id(action):
                continue
            source_label, path_parts = self._action_context(action)
            self._register_action_entry(
                action_map,
                action,
                source_label,
                path_parts=path_parts,
            )
            self._attach_state_widget_to_action_entry(
                action_map,
                action,
                source_label,
                path_parts=path_parts,
                state_widget=self._preferred_state_widget_for_action(action),
            )

            if menu is None:
                continue
            self._attach_menu_to_action_entry(
                action_map,
                action,
                source_label,
                path_parts=path_parts,
                menu=menu,
            )
            root_label = self._action_label(action)
            next_path = list(path_parts)
            if root_label:
                next_path.append(root_label)
            self._register_menu_actions(
                action_map,
                    menu,
                    source_label,
                    next_path,
                )

        self._inject_special_native_dropdown_entries(action_map)

        entries = list(action_map.values())
        entries.sort(
            key=lambda entry: (
                ",".join(entry.get("sources", [])).lower(),
                entry.get("label", "").lower(),
                entry.get("id", "").lower(),
            )
        )
        return entries

    def _native_toolbar_template_items(self, toolbar, action_entry_lookup):
        items = []
        source_label = self._toolbar_label(toolbar)

        for toolbar_action in toolbar.actions():
            if toolbar_action is None:
                continue
            if toolbar_action.isSeparator():
                items.append({"type": "separator"})
                continue

            binding = self._toolbar_action_binding(toolbar, toolbar_action)
            if binding is None:
                continue

            action = binding["action"]
            menu = binding["menu"]
            if not self._is_supported_root_action(action, menu):
                continue

            action_id = self._root_action_storage_id(
                toolbar,
                toolbar_action,
                action,
                menu,
                source_label,
            )
            if action_id not in action_entry_lookup:
                continue
            items.append({"type": "action", "id": action_id})

        return self._trim_separator_items(items)

    def _trim_separator_items(self, items):
        compact_items = []
        previous_was_separator = True

        for item in items:
            item_type = str(item.get("type") or "").strip().lower()
            if item_type == "separator":
                if previous_was_separator:
                    continue
                compact_items.append({"type": "separator"})
                previous_was_separator = True
                continue

            compact_items.append(item)
            previous_was_separator = False

        while compact_items and compact_items[-1].get("type") == "separator":
            compact_items.pop()

        return compact_items

    def _register_action_entry(
        self,
        action_map,
        action,
        source_label,
        path_parts,
        storage_id=None,
    ):
        if not self._is_eligible_action(action):
            return

        action_label = self._action_label(action)
        action_id = storage_id or self._action_storage_id(
            action,
            source_label,
            path_parts,
        )

        label_parts = [part for part in path_parts if part]
        if label_parts and label_parts[-1] == action_label:
            display_label = " -> ".join(label_parts)
        elif label_parts:
            display_label = " -> ".join(label_parts + [action_label])
        else:
            display_label = action_label

        source_hint = source_label
        if path_parts:
            source_hint = "{} / {}".format(source_label, " -> ".join(path_parts))

        entry = action_map.setdefault(
            action_id,
            {
                "id": action_id,
                "label": display_label,
                "sources": [],
                "action": action,
                "state_widget": None,
                "legacy_alias_ids": [],
            },
        )
        if source_hint not in entry["sources"]:
            entry["sources"].append(source_hint)
        entry["label"] = display_label or entry.get("label") or action_id
        entry["action"] = action

    def _attach_state_widget_to_action_entry(
        self,
        action_map,
        action,
        source_label,
        path_parts,
        state_widget,
        storage_id=None,
    ):
        if state_widget is None:
            return
        action_id = storage_id or self._action_storage_id(
            action,
            source_label,
            path_parts,
        )
        entry = action_map.get(action_id)
        if entry is None:
            return
        entry["state_widget"] = state_widget

    def _attach_menu_to_action_entry(
        self,
        action_map,
        action,
        source_label,
        path_parts,
        menu,
        storage_id=None,
    ):
        if menu is None:
            return
        action_id = storage_id or self._action_storage_id(
            action,
            source_label,
            path_parts,
        )
        entry = action_map.get(action_id)
        if entry is None:
            return
        entry["menu"] = menu

    def _attach_aliases_to_action_entry(
        self,
        action_map,
        action,
        source_label,
        path_parts,
        alias_ids,
        storage_id=None,
    ):
        if not alias_ids:
            return
        action_id = storage_id or self._action_storage_id(
            action,
            source_label,
            path_parts,
        )
        entry = action_map.get(action_id)
        if entry is None:
            return

        existing = entry.setdefault("legacy_alias_ids", [])
        for alias_id in alias_ids:
            if alias_id and alias_id not in existing:
                existing.append(alias_id)

    def _register_menu_actions(self, action_map, menu, source_label, path_parts):
        if menu is None:
            return

        for menu_action in menu.actions():
            if menu_action is None or menu_action.isSeparator():
                continue

            submenu = None
            try:
                submenu = menu_action.menu()
            except Exception:
                submenu = None

            action_label = self._action_label(menu_action)
            if submenu is not None:
                next_path = list(path_parts)
                if action_label:
                    next_path.append(action_label)
                self._register_menu_actions(
                    action_map,
                    submenu,
                    source_label,
                    next_path,
                )
                continue

            self._register_action_entry(
                action_map,
                menu_action,
                source_label,
                path_parts,
            )

    def _action_context(self, action):
        menu_parts = []
        parent = action.parent()
        while parent is not None:
            title = ""
            title_getter = getattr(parent, "title", None)
            if callable(title_getter):
                try:
                    title = self._clean_text(title_getter())
                except Exception:
                    title = ""
            elif hasattr(parent, "windowTitle"):
                try:
                    title = self._clean_text(parent.windowTitle())
                except Exception:
                    title = ""

            if title:
                menu_parts.append(title)
            parent = parent.parent() if hasattr(parent, "parent") else None

        menu_parts.reverse()
        if menu_parts:
            return menu_parts[0], menu_parts[1:]

        return "Weitere QGIS-Aktionen", []

    def _menu_for_toolbar_action(self, toolbar, action):
        if toolbar is None or action is None:
            return None

        try:
            menu = action.menu()
        except Exception:
            menu = None
        if menu is not None:
            return menu

        try:
            widget = toolbar.widgetForAction(action)
        except Exception:
            widget = None
        if widget is None:
            return None

        widget_probe = self._menu_button_for_widget(widget) or widget

        menu_getter = getattr(widget_probe, "menu", None)
        if not callable(menu_getter):
            return None

        try:
            menu = menu_getter()
        except Exception:
            menu = None
        return menu

    def _default_action_for_toolbar_widget(self, widget):
        if widget is None:
            return None

        button = self._action_button_for_widget(widget)
        if button is not None:
            default_action_getter = getattr(button, "defaultAction", None)
            if callable(default_action_getter):
                try:
                    action = default_action_getter()
                except Exception:
                    action = None
                if isinstance(action, QAction):
                    return action

        default_action_getter = getattr(widget, "defaultAction", None)
        if callable(default_action_getter):
            try:
                action = default_action_getter()
            except Exception:
                action = None
            if isinstance(action, QAction):
                return action

        actions_getter = getattr(widget, "actions", None)
        if callable(actions_getter):
            try:
                for action in actions_getter():
                    if isinstance(action, QAction) and not action.isSeparator():
                        return action
            except Exception:
                return None

        return None

    def _toolbuttons_for_widget(self, widget):
        if widget is None:
            return []
        if isinstance(widget, QToolButton):
            return [widget]

        find_children = getattr(widget, "findChildren", None)
        if not callable(find_children):
            return []

        try:
            return [child for child in find_children(QToolButton) if child is not None]
        except Exception:
            return []

    def _action_button_for_widget(self, widget, source_action=None):
        buttons = self._toolbuttons_for_widget(widget)
        if not buttons:
            return None

        if source_action is not None:
            for button in buttons:
                default_action_getter = getattr(button, "defaultAction", None)
                if not callable(default_action_getter):
                    continue
                try:
                    default_action = default_action_getter()
                except Exception:
                    default_action = None
                if default_action is source_action:
                    return button

        for button in buttons:
            default_action_getter = getattr(button, "defaultAction", None)
            if not callable(default_action_getter):
                continue
            try:
                default_action = default_action_getter()
            except Exception:
                default_action = None
            if isinstance(default_action, QAction):
                return button

        return buttons[0]

    def _menu_button_for_widget(self, widget, source_action=None):
        buttons = self._toolbuttons_for_widget(widget)
        if not buttons:
            return None

        if source_action is not None:
            for button in buttons:
                default_action_getter = getattr(button, "defaultAction", None)
                if not callable(default_action_getter):
                    continue
                try:
                    default_action = default_action_getter()
                except Exception:
                    default_action = None
                if default_action is not source_action:
                    continue
                try:
                    if button.menu() is not None:
                        return button
                except Exception:
                    continue

        for button in buttons:
            try:
                if button.menu() is not None:
                    return button
            except Exception:
                continue

        return self._action_button_for_widget(widget, source_action=source_action)

    def _toolbar_action_binding(self, toolbar, toolbar_action):
        if toolbar is None or toolbar_action is None:
            return None

        state_widget = self._state_widget_for_toolbar_action(toolbar, toolbar_action)
        toolbar_widget = self._widget_for_toolbar_action(toolbar, toolbar_action)
        source_action = toolbar_action
        if isinstance(toolbar_action, QWidgetAction):
            source_action = self._default_action_for_toolbar_widget(
                toolbar_widget
            )
            if source_action is None:
                return None

        return {
            "action": source_action,
            "menu": self._menu_for_toolbar_action(toolbar, toolbar_action),
            "state_widget": state_widget,
        }

    def _menu_for_action(self, action):
        if action is None:
            return None
        try:
            return action.menu()
        except Exception:
            return None

    def _widget_for_toolbar_action(self, toolbar, action):
        if toolbar is None or action is None:
            return None
        try:
            return toolbar.widgetForAction(action)
        except Exception:
            return None

    def _state_widget_for_toolbar_action(self, toolbar, action):
        widget = self._widget_for_toolbar_action(toolbar, action)
        toolbar_widget = widget
        if isinstance(action, QWidgetAction):
            source_action = self._default_action_for_toolbar_widget(toolbar_widget)
        else:
            source_action = action

        return (
            self._action_button_for_widget(
                toolbar_widget,
                source_action=source_action,
            )
            or toolbar_widget
        )

    def _preferred_state_widget_for_action(self, action):
        if action is None:
            return None
        associated_widgets_getter = getattr(action, "associatedWidgets", None)
        if not callable(associated_widgets_getter):
            return None

        fallback_widget = None
        try:
            for widget in associated_widgets_getter():
                if widget is None:
                    continue
                if not self._object_belongs_to_main_window_context(widget):
                    continue
                inner_button = self._action_button_for_widget(
                    widget,
                    source_action=action,
                )
                if inner_button is not None:
                    return inner_button
                if isinstance(widget, QToolButton):
                    return widget
                if fallback_widget is None and isinstance(widget, QWidget):
                    fallback_widget = widget
        except Exception:
            return fallback_widget
        return fallback_widget

    def _iter_native_toolbars(self):
        for toolbar in self.iface.mainWindow().findChildren(QToolBar):
            if self._is_managed_toolbar(toolbar):
                continue
            if not toolbar.objectName().strip():
                continue
            yield toolbar

    def _first_top_level_toolbar(self, exclude_toolbar=None):
        main_window = self.iface.mainWindow()
        for toolbar in main_window.findChildren(QToolBar):
            if toolbar is exclude_toolbar:
                continue
            if main_window.toolBarArea(toolbar) != Qt.TopToolBarArea:
                continue
            return toolbar
        return None

    def _is_managed_toolbar(self, toolbar):
        if toolbar is None:
            return False
        if bool(toolbar.property(self.MANAGED_TOOLBAR_PROPERTY)):
            return True
        if toolbar.objectName() == self.BRANDING_TOOLBAR_OBJECT_NAME:
            return True
        return toolbar.objectName().startswith(self.MANAGED_TOOLBAR_PREFIX)

    def _toolbar_label(self, toolbar):
        label = (
            toolbar.windowTitle()
            or toolbar.toggleViewAction().text()
            or toolbar.objectName()
        )
        return self._clean_text(label) or toolbar.objectName()

    def _is_eligible_action(self, action):
        if action is None or action.isSeparator():
            return False
        if isinstance(action, QWidgetAction):
            return False
        if action is self.action:
            return False
        object_name = action.objectName().strip()
        if object_name == self.PLUGIN_ACTION_OBJECT_NAME:
            return False
        if object_name.startswith(self.MANAGED_TOOLBAR_PREFIX):
            return False
        return bool(self._action_label(action))

    def _is_supported_root_action(self, action, menu):
        if not self._is_eligible_action(action):
            return False
        if not self._belongs_to_main_window_context(action):
            return False
        if menu is not None and not self._menu_belongs_to_main_window_context(menu):
            return False
        return True

    def _belongs_to_main_window_context(self, action):
        main_window = self.iface.mainWindow()
        associated_widgets_getter = getattr(action, "associatedWidgets", None)
        if callable(associated_widgets_getter):
            try:
                for widget in associated_widgets_getter():
                    if widget is None:
                        continue
                    if not self._object_belongs_to_main_window_context(widget):
                        return False
            except Exception:
                pass

        return self._object_belongs_to_main_window_context(action.parent())

    def _menu_belongs_to_main_window_context(self, menu):
        return self._object_belongs_to_main_window_context(menu)

    def _object_belongs_to_main_window_context(self, obj):
        main_window = self.iface.mainWindow()
        visited = set()
        current = obj
        while current is not None:
            marker = id(current)
            if marker in visited:
                break
            visited.add(marker)

            if current is main_window:
                return True

            if isinstance(current, QWidget):
                parent_widget = current.parentWidget()
                if parent_widget is not None:
                    current = parent_widget
                    continue
                if current.isWindow():
                    return False

            parent_getter = getattr(current, "parent", None)
            current = parent_getter() if callable(parent_getter) else None

        return True

    def _restore_layout_state_if_needed(self):
        if self._layout_state_restored:
            return
        self._layout_state_restored = True

        if self._saved_layout_state in (None, ""):
            return
        if not self.toolbar_definitions and not self.branding_enabled:
            return

        main_window = self.iface.mainWindow()
        restored = False
        try:
            restored = bool(
                main_window.restoreState(
                    self._saved_layout_state,
                    self.LAYOUT_STATE_VERSION,
                )
            )
        except TypeError:
            try:
                restored = bool(main_window.restoreState(self._saved_layout_state))
            except Exception:
                restored = False
        except Exception:
            restored = False

        if not restored:
            return

        self._apply_native_toolbar_visibility()
        for definition in self.toolbar_definitions:
            toolbar = self._managed_toolbars.get(definition["id"])
            if toolbar is not None:
                toolbar.setVisible(bool(definition.get("visible", True)))
        if self._branding_toolbar is not None:
            self._branding_toolbar.setVisible(bool(self.branding_enabled))

    def _save_layout_state(self):
        if not self.toolbar_definitions and not self.branding_enabled:
            self.settings.remove(self.SETTINGS_LAYOUT_STATE)
            self._saved_layout_state = None
            return

        main_window = self.iface.mainWindow()
        try:
            state = main_window.saveState(self.LAYOUT_STATE_VERSION)
        except TypeError:
            state = main_window.saveState()
        except Exception:
            return

        if isinstance(state, QByteArray) and state.isEmpty():
            return
        if state in (None, ""):
            return

        self._saved_layout_state = state
        self.settings.setValue(self.SETTINGS_LAYOUT_STATE, state)

    def _iface_action(self, getter_name):
        getter = getattr(self.iface, getter_name, None)
        if not callable(getter):
            return None
        try:
            action = getter()
        except Exception:
            return None
        return action if isinstance(action, QAction) else None

    def _special_native_dropdown_storage_id(self, action):
        if action is None:
            return None

        object_name = action.objectName().strip()
        root_action = self._iface_action("actionVertexTool")
        active_layer_action = self._iface_action("actionVertexToolActiveLayer")
        if (
            action is root_action
            or action is active_layer_action
            or object_name in ("mActionVertexTool", "mActionVertexToolActiveLayer")
        ):
            return "native-dropdown::vertex-tool"

        return None

    def _special_native_dropdown_actions(self, action):
        storage_id = self._special_native_dropdown_storage_id(action)
        if storage_id != "native-dropdown::vertex-tool":
            return []

        actions = []
        for getter_name in ("actionVertexTool", "actionVertexToolActiveLayer"):
            source_action = self._iface_action(getter_name)
            if source_action is None or source_action in actions:
                continue
            actions.append(source_action)
        return actions

    def _inject_special_native_dropdown_entries(self, action_map):
        root_action = self._iface_action("actionVertexTool")
        source_actions = self._special_native_dropdown_actions(root_action)
        if root_action is None or len(source_actions) < 2:
            return

        storage_id = self._special_native_dropdown_storage_id(root_action)
        if not storage_id:
            return

        entry = action_map.get(storage_id)
        if entry is None:
            entry = {
                "id": storage_id,
                "label": self._action_label(root_action),
                "sources": [],
                "action": root_action,
                "state_widget": None,
                "legacy_alias_ids": [],
            }
            action_map[storage_id] = entry

        digitize_toolbar_getter = getattr(self.iface, "digitizeToolBar", None)
        toolbar = digitize_toolbar_getter() if callable(digitize_toolbar_getter) else None
        source_label = (
            self._toolbar_label(toolbar)
            if isinstance(toolbar, QToolBar)
            else self.tr("Digitalisierung")
        )
        if source_label and source_label not in entry["sources"]:
            entry["sources"].append(source_label)

        entry["action"] = root_action
        entry["state_widget"] = self._preferred_state_widget_for_action(root_action)
        entry["menu_actions"] = source_actions
        entry["label"] = entry.get("label") or self._action_label(root_action)

        alias_ids = entry.setdefault("legacy_alias_ids", [])
        for source_action in source_actions:
            object_name = source_action.objectName().strip()
            if object_name and object_name not in alias_ids:
                alias_ids.append(object_name)

    def _native_dropdown_alias_ids(self, menu):
        alias_ids = []
        if menu is None:
            return alias_ids

        for menu_action in menu.actions():
            if menu_action is None or menu_action.isSeparator():
                continue
            try:
                if menu_action.menu() is not None:
                    continue
            except Exception:
                pass

            object_name = menu_action.objectName().strip()
            if object_name:
                alias_ids.append(object_name)
        return alias_ids

    def _menu_signature(self, menu):
        if menu is None:
            return ""

        signature_parts = []
        for menu_action in menu.actions():
            if menu_action is None or menu_action.isSeparator():
                continue

            object_name = menu_action.objectName().strip()
            if object_name:
                signature_parts.append(object_name)
                continue

            label = self._action_label(menu_action)
            if label:
                signature_parts.append(self._slugify(label))
                continue

            signature_parts.append(menu_action.__class__.__name__.lower())

        return "--".join(signature_parts)

    def _checked_menu_action(self, menu):
        if menu is None:
            return None

        first_action = None
        for menu_action in menu.actions():
            if menu_action is None or menu_action.isSeparator():
                continue
            try:
                if menu_action.menu() is not None:
                    continue
            except Exception:
                continue

            if first_action is None and isinstance(menu_action, QAction):
                first_action = menu_action
            try:
                if menu_action.isCheckable() and menu_action.isChecked():
                    return menu_action
            except Exception:
                continue

        return first_action

    def _root_action_storage_id(
        self,
        toolbar,
        toolbar_action,
        action,
        menu,
        source_label,
    ):
        special_storage_id = self._special_native_dropdown_storage_id(action)
        if special_storage_id:
            return special_storage_id

        if menu is None:
            return self._action_storage_id(action, source_label, [])

        toolbar_key = ""
        if toolbar is not None:
            toolbar_key = toolbar.objectName().strip() or self._slugify(
                self._toolbar_label(toolbar)
            )
        menu_signature = self._menu_signature(menu)
        if toolbar_key and menu_signature:
            return "native-dropdown::{}::{}".format(
                toolbar_key,
                menu_signature,
            )

        return self._action_storage_id(action, source_label, [])

    def _action_storage_id(self, action, source_label, path_parts):
        object_name = action.objectName().strip()
        if object_name:
            return object_name

        signature_parts = [source_label] + list(path_parts) + [self._action_label(action)]
        signature = "-".join(
            self._slugify(part)
            for part in signature_parts
            if self._clean_text(part)
        )
        if not signature:
            signature = "action"
        return "synthetic::{}".format(signature)

    def _action_label(self, action):
        label = (
            action.iconText()
            or action.text()
            or action.toolTip()
            or action.statusTip()
            or action.objectName()
        )
        return self._clean_text(label)

    def _clean_text(self, value):
        return clean_ui_text(value)

    def _slugify(self, value):
        text = self._clean_text(value).lower()
        text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
        return text

    def _normalize_toolbar_definitions(self, raw_definitions):
        normalized = []
        seen_ids = set()

        for index, raw_definition in enumerate(raw_definitions or [], start=1):
            if not isinstance(raw_definition, dict):
                continue

            title = self._clean_text(raw_definition.get("title")) or (
                "Eigene Werkzeugleiste {}".format(index)
            )
            toolbar_id = str(raw_definition.get("id") or "").strip()
            if not toolbar_id:
                toolbar_id = self._unique_toolbar_id(title, seen_ids)
            else:
                toolbar_id = self._dedupe_toolbar_id(toolbar_id, seen_ids)

            normalized_actions = []
            for raw_item in raw_definition.get("actions", []):
                normalized_item = self._normalize_toolbar_item(raw_item)
                if normalized_item is not None:
                    normalized_actions.append(normalized_item)

            normalized.append(
                {
                    "id": toolbar_id,
                    "title": title,
                    "visible": bool(raw_definition.get("visible", True)),
                    "actions": normalized_actions,
                }
            )

        return normalized

    def _normalize_toolbar_item(self, raw_item):
        if isinstance(raw_item, dict):
            item_type = str(raw_item.get("type") or "").strip().lower()
            if item_type == "separator":
                return {"type": "separator"}
            if item_type == "logo":
                return {
                    "type": "logo",
                    "path": str(raw_item.get("path") or "logo.svg").strip()
                    or "logo.svg",
                    "label": self._clean_text(raw_item.get("label")) or "Logo",
                    "height": self._normalize_int(raw_item.get("height"), 28),
                }
            if item_type == "dropdown":
                label = self._clean_text(raw_item.get("label")) or "Dropdown"
                action_ids = self._normalize_dropdown_action_ids(
                    raw_item.get("actions", [])
                )
                if not action_ids:
                    return None
                return {
                    "type": "dropdown",
                    "label": label,
                    "actions": action_ids,
                }

            action_id = str(raw_item.get("id") or "").strip()
            if action_id:
                return {"type": "action", "id": action_id}
            return None

        action_id = str(raw_item or "").strip()
        if action_id:
            return {"type": "action", "id": action_id}
        return None

    def _normalize_dropdown_action_ids(self, raw_actions):
        action_ids = []
        for raw_action in raw_actions or []:
            if isinstance(raw_action, dict):
                action_id = str(raw_action.get("id") or "").strip()
            else:
                action_id = str(raw_action or "").strip()
            if action_id:
                action_ids.append(action_id)
        return action_ids

    def _normalize_int(self, value, default):
        try:
            parsed = int(value)
        except Exception:
            return default
        return max(12, min(parsed, 96))

    def _unique_toolbar_id(self, title, seen_ids):
        base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        if not base:
            base = "toolbar"
        return self._dedupe_toolbar_id(base, seen_ids)

    def _dedupe_toolbar_id(self, base_id, seen_ids):
        candidate = base_id
        suffix = 2
        while candidate in seen_ids:
            candidate = "{}-{}".format(base_id, suffix)
            suffix += 1
        seen_ids.add(candidate)
        return candidate

    def _is_logo_only_toolbar_definition(self, definition):
        items = list(definition.get("actions", []))
        if not items:
            return False
        return all(item.get("type") == "logo" for item in items)

    def _clear_toolbar(self, toolbar):
        for action in list(toolbar.actions()):
            toolbar.removeAction(action)
            if bool(action.property(self.MANAGED_WIDGET_ACTION_PROPERTY)):
                widget = toolbar.widgetForAction(action)
                if widget is not None:
                    widget.deleteLater()
                action.deleteLater()

    def _create_mirrored_action(
        self,
        parent,
        action,
        text_override=None,
        state_widget=None,
    ):
        if action is None:
            return None
        state_widget_resolver = (
            lambda source_action=action: self._preferred_state_widget_for_action(
                source_action
            )
        )
        return StaticProxyAction(
            action,
            parent=parent,
            text_override=text_override,
            state_widget=state_widget,
            state_widget_resolver=state_widget_resolver,
        )

    def _sync_button_enabled_state(self, button, action):
        if button is None or action is None:
            return

        def apply_state():
            try:
                button.setEnabled(bool(action.isEnabled()))
            except RuntimeError:
                return
            except Exception:
                return

            try:
                icon = action.icon()
            except RuntimeError:
                return
            except Exception:
                icon = QIcon()
            if not icon.isNull():
                self._apply_button_icon_state(
                    button,
                    icon,
                    bool(button.isEnabled()),
                )

        try:
            apply_state()
        except Exception:
            return

        try:
            action.changed.connect(apply_state)
        except Exception:
            pass

    def _apply_button_icon_state(self, button, icon, enabled):
        if button is None or icon is None or icon.isNull():
            return

        if enabled:
            button.setIcon(icon)
            return

        size = button.iconSize()
        if not size.isValid():
            size = QSize(24, 24)

        disabled_pixmap = icon.pixmap(size, QIcon.Disabled)
        disabled_icon = QIcon()
        disabled_icon.addPixmap(disabled_pixmap, QIcon.Normal)
        disabled_icon.addPixmap(disabled_pixmap, QIcon.Disabled)
        button.setIcon(disabled_icon)

    def _is_qt_object_alive(self, obj):
        if obj is None:
            return False
        try:
            return not sip.isdeleted(obj)
        except Exception:
            return True

    def _add_shared_action_button(self, toolbar, entry):
        action = entry.get("action")
        state_widget = entry.get("state_widget")
        if action is None:
            return
        button = QToolButton(toolbar)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.NoFocus)
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setIconSize(toolbar.iconSize())
        mirrored_action = self._create_mirrored_action(
            button,
            action,
            state_widget=state_widget,
        )
        if mirrored_action is None:
            button.deleteLater()
            return
        button.setDefaultAction(mirrored_action)
        self._sync_button_enabled_state(button, mirrored_action)
        widget_action = toolbar.addWidget(button)
        widget_action.setProperty(self.MANAGED_WIDGET_ACTION_PROPERTY, True)
        widget_action.setText(self._action_label(action))

    def _add_dropdown_button(self, toolbar, item, action_lookup):
        entries = [
            action_lookup[action_id]
            for action_id in item.get("actions", [])
            if action_id in action_lookup
            and action_lookup[action_id].get("action") is not None
        ]
        if not entries:
            return

        button = QToolButton(toolbar)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.NoFocus)
        button.setPopupMode(QToolButton.InstantPopup)
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setIconSize(toolbar.iconSize())
        button.setToolTip(self._clean_text(item.get("label")) or "Dropdown")

        first_action = entries[0].get("action")
        first_state_widget = entries[0].get("state_widget")
        first_proxy_action = self._create_mirrored_action(
            button,
            first_action,
            state_widget=first_state_widget,
        )
        if first_proxy_action is not None:
            button.setIcon(first_proxy_action.icon())
            self._sync_button_enabled_state(button, first_proxy_action)
        else:
            button.setIcon(first_action.icon())

        if button.icon().isNull():
            button.setText(self._clean_text(item.get("label")) or "Dropdown")
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)

        menu = QMenu(button)
        for entry in entries:
            mirrored_action = self._create_mirrored_action(
                menu,
                entry.get("action"),
                state_widget=entry.get("state_widget"),
            )
            if mirrored_action is not None:
                menu.addAction(mirrored_action)
        button.setMenu(menu)

        widget_action = toolbar.addWidget(button)
        widget_action.setProperty(self.MANAGED_WIDGET_ACTION_PROPERTY, True)
        widget_action.setText(self._clean_text(item.get("label")) or "Dropdown")

    def _add_native_dropdown_button(self, toolbar, entry):
        source_action = entry.get("action")
        source_menu = entry.get("menu")
        source_menu_actions = [
            action
            for action in entry.get("menu_actions", [])
            if isinstance(action, QAction)
        ]
        state_widget = entry.get("state_widget")
        if source_action is None or (source_menu is None and not source_menu_actions):
            return

        button = QToolButton(toolbar)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.NoFocus)
        button.setPopupMode(QToolButton.MenuButtonPopup)
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setIconSize(toolbar.iconSize())
        button.setToolTip(self._action_label(source_action))

        def resolve_state_button():
            current_action = resolve_current_action()
            if self._is_qt_object_alive(current_action):
                resolved = self._preferred_state_widget_for_action(current_action)
                if isinstance(resolved, QToolButton) and self._is_qt_object_alive(
                    resolved
                ):
                    return resolved
            if self._is_qt_object_alive(source_action):
                resolved = self._preferred_state_widget_for_action(source_action)
                if isinstance(resolved, QToolButton) and self._is_qt_object_alive(
                    resolved
                ):
                    return resolved
            if isinstance(state_widget, QToolButton) and self._is_qt_object_alive(
                state_widget
            ):
                return state_widget
            return None

        def resolve_current_action():
            if source_menu_actions:
                first_action = None
                for menu_action in source_menu_actions:
                    if not self._is_qt_object_alive(menu_action):
                        continue
                    if first_action is None:
                        first_action = menu_action
                    try:
                        if menu_action.isCheckable() and menu_action.isChecked():
                            return menu_action
                    except Exception:
                        continue
                if self._is_qt_object_alive(source_action):
                    return source_action
                return first_action

            current_action = self._checked_menu_action(source_menu)
            if isinstance(current_action, QAction) and self._is_qt_object_alive(
                current_action
            ):
                return current_action
            if self._is_qt_object_alive(source_action):
                return source_action
            return None

        def adopt_current_action_on_source_button(current_action):
            if current_action is None:
                return
            source_button = resolve_state_button()
            if source_button is None or not self._is_qt_object_alive(source_button):
                return
            set_default_action = getattr(source_button, "setDefaultAction", None)
            if not callable(set_default_action):
                return
            try:
                set_default_action(current_action)
            except Exception:
                pass

        def trigger_via_source_button(current_action):
            if current_action is None:
                return False
            source_button = resolve_state_button()
            if source_button is None or not self._is_qt_object_alive(source_button):
                return False
            try:
                adopt_current_action_on_source_button(current_action)
                if source_button.isEnabled():
                    source_button.click()
                    return True
            except Exception:
                return False
            return False

        def sync_special_mirrored_action(mirrored_action, source_menu_action):
            if not self._is_qt_object_alive(mirrored_action) or not self._is_qt_object_alive(
                source_menu_action
            ):
                return
            try:
                label = self._action_label(source_menu_action)
                tool_tip = self._clean_text(
                    source_menu_action.toolTip() or source_menu_action.text() or label
                )
            except Exception:
                label = ""
                tool_tip = ""
            try:
                mirrored_action.setCheckable(bool(source_menu_action.isCheckable()))
                mirrored_action.setChecked(bool(source_menu_action.isChecked()))
                mirrored_action.setEnabled(bool(source_menu_action.isEnabled()))
                mirrored_action.setIcon(source_menu_action.icon())
                mirrored_action.setText(label)
                mirrored_action.setToolTip(tool_tip)
                mirrored_action.setStatusTip(tool_tip)
            except Exception:
                return

        mirrored_menu = None
        if source_menu_actions:
            mirrored_menu = QMenu(button)
            for menu_source_action in source_menu_actions:
                mirrored_action = QAction(mirrored_menu)
                sync_special_mirrored_action(mirrored_action, menu_source_action)
                try:
                    menu_source_action.changed.connect(
                        lambda source=menu_source_action, target=mirrored_action: (
                            sync_special_mirrored_action(target, source)
                        )
                    )
                except Exception:
                    pass
                try:
                    menu_source_action.toggled.connect(
                        lambda checked=False, source=menu_source_action, target=mirrored_action: (
                            sync_special_mirrored_action(target, source)
                        )
                    )
                except Exception:
                    pass
                try:
                    mirrored_action.triggered.connect(
                        lambda checked=False, source=menu_source_action: (
                            trigger_via_source_button(source)
                            or (
                                source.isEnabled() and source.trigger()
                            ),
                            QTimer.singleShot(0, sync_native_button),
                        )
                    )
                except Exception:
                    pass
                mirrored_menu.addAction(mirrored_action)
        else:
            mirrored_menu = self._build_mirrored_menu(button, source_menu)

        if mirrored_menu is not None:
            button.setMenu(mirrored_menu)

        def sync_native_button():
            try:
                if not self._is_qt_object_alive(button):
                    return
                current_action = resolve_current_action()
                source_button = resolve_state_button()
                if current_action is None:
                    return

                enabled = False
                icon = QIcon()
                text = self._action_label(current_action)
                try:
                    tool_tip = self._clean_text(
                        current_action.toolTip() or current_action.text() or text
                    )
                except Exception:
                    tool_tip = text

                if source_menu_actions:
                    try:
                        enabled = bool(current_action.isEnabled())
                    except Exception:
                        enabled = False
                    if source_button is not None:
                        try:
                            enabled = enabled and bool(source_button.isEnabled())
                        except Exception:
                            enabled = False
                elif source_button is not None:
                    try:
                        enabled = bool(source_button.isEnabled())
                        if icon.isNull():
                            icon = source_button.icon()
                    except Exception:
                        source_button = None
                        enabled = False

                if source_button is None:
                    try:
                        enabled = bool(current_action.isEnabled())
                    except Exception:
                        enabled = False

                if icon.isNull():
                    try:
                        icon = current_action.icon()
                    except Exception:
                        icon = QIcon()

                if not self._is_qt_object_alive(button):
                    return
                button.setCheckable(bool(current_action.isCheckable()))

                if not self._is_qt_object_alive(button):
                    return
                if button.isCheckable():
                    try:
                        button.setChecked(bool(current_action.isChecked()))
                    except Exception:
                        button.setChecked(False)
                button.setEnabled(enabled)
                self._apply_button_icon_state(button, icon, enabled)
                button.setToolTip(tool_tip)

                if icon.isNull():
                    button.setText(text)
                    button.setToolButtonStyle(Qt.ToolButtonTextOnly)
                else:
                    button.setText("")
                    button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            except RuntimeError:
                return
            except Exception:
                return

        def trigger_current_action():
            current_action = resolve_current_action()
            if current_action is None:
                return
            if source_menu_actions and trigger_via_source_button(current_action):
                QTimer.singleShot(0, sync_native_button)
                return
            try:
                if current_action.isEnabled():
                    current_action.trigger()
            except Exception:
                return
            QTimer.singleShot(0, sync_native_button)

        button.clicked.connect(trigger_current_action)

        def connect_menu_sync(menu):
            if menu is None:
                return
            for menu_action in menu.actions():
                if menu_action is None:
                    continue
                try:
                    menu_action.triggered.connect(
                        lambda checked=False: QTimer.singleShot(0, sync_native_button)
                    )
                except Exception:
                    pass
                submenu = None
                try:
                    submenu = menu_action.menu()
                except Exception:
                    submenu = None
                if submenu is not None:
                    connect_menu_sync(submenu)

        connect_menu_sync(mirrored_menu)

        def connect_source_action_sync(actions):
            for menu_action in actions:
                if menu_action is None:
                    continue
                try:
                    menu_action.changed.connect(
                        lambda: QTimer.singleShot(0, sync_native_button)
                    )
                except Exception:
                    pass
                try:
                    menu_action.toggled.connect(
                        lambda checked=False: QTimer.singleShot(0, sync_native_button)
                    )
                except Exception:
                    pass

        if source_menu_actions:
            connect_source_action_sync(source_menu_actions)
        else:
            def connect_source_menu_sync(menu):
                if menu is None:
                    return
                for menu_action in menu.actions():
                    if menu_action is None:
                        continue
                    try:
                        menu_action.changed.connect(
                            lambda: QTimer.singleShot(0, sync_native_button)
                        )
                    except Exception:
                        pass
                    try:
                        menu_action.toggled.connect(
                            lambda checked=False: QTimer.singleShot(
                                0, sync_native_button
                            )
                        )
                    except Exception:
                        pass
                    submenu = None
                    try:
                        submenu = menu_action.menu()
                    except Exception:
                        submenu = None
                    if submenu is not None:
                        connect_source_menu_sync(submenu)

            connect_source_menu_sync(source_menu)

        try:
            source_action.changed.connect(sync_native_button)
        except Exception:
            pass

        sync_native_button()

        widget_action = toolbar.addWidget(button)
        widget_action.setProperty(self.MANAGED_WIDGET_ACTION_PROPERTY, True)
        widget_action.setText(self._action_label(source_action))

    def _build_mirrored_menu(self, parent, source_menu):
        if source_menu is None:
            return None

        menu = QMenu(parent)
        try:
            menu_title = self._clean_text(source_menu.title())
        except Exception:
            menu_title = ""
        if menu_title:
            menu.setTitle(menu_title)

        self._populate_mirrored_menu(menu, source_menu)
        return menu

    def _populate_mirrored_menu(self, target_menu, source_menu):
        if target_menu is None or source_menu is None:
            return

        for source_action in source_menu.actions():
            if source_action is None:
                continue
            if source_action.isSeparator():
                target_menu.addSeparator()
                continue

            submenu = None
            try:
                submenu = source_action.menu()
            except Exception:
                submenu = None

            if submenu is not None:
                submenu_label = self._action_label(source_action) or self._clean_text(
                    submenu.title()
                ) or self.tr("Untermenue")
                target_submenu = target_menu.addMenu(
                    source_action.icon(),
                    submenu_label,
                )
                self._populate_mirrored_menu(target_submenu, submenu)
                continue

            mirrored_action = self._create_mirrored_action(
                target_menu,
                source_action,
                state_widget=self._preferred_state_widget_for_action(source_action),
            )
            if mirrored_action is not None:
                target_menu.addAction(mirrored_action)

    def _add_logo_widget(self, toolbar, item, left_padding):
        logo_path = self._resolve_logo_path(item.get("path") or "logo.svg")

        content_label = QLabel(toolbar)
        content_label.setAlignment(Qt.AlignCenter)
        content_label.setMargin(0)
        content_label.setContentsMargins(0, 0, 0, 0)
        content_label.setIndent(0)
        content_label.setToolTip(self._clean_text(item.get("label")) or "Logo")
        content_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        pixmap = self._render_logo_pixmap(
            logo_path,
            self._normalize_int(item.get("height"), 28),
        )
        if not pixmap.isNull():
            content_label.setPixmap(pixmap)
            content_label.setFixedSize(pixmap.size())
        else:
            content_label.setText(self._clean_text(item.get("label")) or "Logo")

        container = QWidget(toolbar)
        container.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(left_padding, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(content_label)
        container.adjustSize()

        widget_action = toolbar.addWidget(container)
        widget_action.setProperty(self.MANAGED_WIDGET_ACTION_PROPERTY, True)
        widget_action.setText(self._clean_text(item.get("label")) or "Logo")

    def _resolve_logo_path(self, raw_path):
        path = str(raw_path or "").strip()
        if not path:
            return os.path.join(self.plugin_dir, "logo.svg")
        if os.path.isabs(path):
            return path
        return os.path.join(self.plugin_dir, path)

    def _render_logo_pixmap(self, logo_path, target_height):
        if not os.path.exists(logo_path):
            return QPixmap()

        renderer = QSvgRenderer(logo_path)
        if not renderer.isValid():
            return QPixmap(logo_path)

        default_size = renderer.defaultSize()
        if default_size.isEmpty() or default_size.height() <= 0:
            width = target_height * 4
            height = target_height
        else:
            height = target_height
            width = max(
                24,
                int(
                    round(
                        default_size.width()
                        * (float(height) / default_size.height())
                    )
                ),
            )

        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        renderer.render(painter, QRectF(0, 0, width, height))
        painter.end()
        return QPixmap.fromImage(image)

    def _remove_managed_toolbars(self):
        main_window = self.iface.mainWindow()
        for toolbar in self._managed_toolbars.values():
            main_window.removeToolBar(toolbar)
            toolbar.deleteLater()
        self._managed_toolbars = {}

    def _definition_by_managed_toolbar_id(self, toolbar_id):
        if not toolbar_id:
            return None
        for definition in self.toolbar_definitions:
            if definition.get("id") == toolbar_id:
                return definition
        return None

    def _restore_native_toolbars(self):
        for toolbar in self._iter_native_toolbars():
            toolbar.setVisible(True)

    def _available_presets(self):
        preset_dir = os.path.join(self.plugin_dir, self.PRESET_DIRECTORY_NAME)
        if not os.path.isdir(preset_dir):
            return []

        presets = []
        for file_name in sorted(os.listdir(preset_dir)):
            if not file_name.lower().endswith(".json"):
                continue
            file_path = os.path.join(preset_dir, file_name)
            preset = self._load_preset_file(file_path)
            if preset is not None:
                presets.append(preset)
        return presets

    def _load_preset_file(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return None

        preset_id = os.path.splitext(os.path.basename(file_path))[0]
        return self._normalize_preset_payload(payload, preset_id)

    def _normalize_preset_payload(self, payload, preset_id):
        if not isinstance(payload, dict):
            return None

        name = self._clean_text(payload.get("name")) or preset_id
        description = self._clean_text(payload.get("description"))

        hidden_raw = payload.get("hidden_native_toolbars")
        if hidden_raw is None:
            hidden_raw = payload.get("hidden_toolbars", [])

        hidden_toolbar_ids = [
            str(toolbar_id).strip()
            for toolbar_id in hidden_raw or []
            if str(toolbar_id).strip()
        ]

        return {
            "id": preset_id,
            "name": name,
            "description": description,
            "toolbars": self._normalize_toolbar_definitions(
                payload.get("toolbars", [])
            ),
            "hidden_toolbar_ids": hidden_toolbar_ids,
            "branding_enabled": bool(payload.get("branding_enabled", False)),
            "show_plugin_toolbar_button": bool(
                payload.get("show_plugin_toolbar_button", True)
            ),
        }
