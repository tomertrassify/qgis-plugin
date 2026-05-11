# -*- coding: utf-8 -*-

import copy
import json
import os
import re

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class ToolbarOverlayDialog(QDialog):
    PRESET_FILE_FILTER = "Toolbar Preset (*.json)"

    def __init__(
        self,
        parent,
        available_actions,
        native_toolbars,
        native_toolbar_templates,
        toolbar_definitions,
        hidden_toolbar_ids,
        built_in_presets=None,
        branding_enabled=False,
        show_plugin_toolbar_button=True,
    ):
        super().__init__(parent)

        self._available_actions = list(available_actions or [])
        self._action_lookup = {
            entry["id"]: entry for entry in self._available_actions
        }
        self._native_toolbars = list(native_toolbars or [])
        self._native_toolbar_templates = copy.deepcopy(
            native_toolbar_templates or []
        )
        self._toolbar_definitions = copy.deepcopy(toolbar_definitions or [])
        self._hidden_toolbar_ids = set(hidden_toolbar_ids or [])
        self._built_in_presets = copy.deepcopy(built_in_presets or [])
        self._branding_enabled = bool(branding_enabled)
        self._show_plugin_toolbar_button = bool(show_plugin_toolbar_button)

        self._updating_toolbar_items = False

        self.setModal(True)
        self.setWindowTitle("Werkzeugleisten konfigurieren")
        self.resize(1180, 780)
        self.setMinimumSize(960, 640)

        self._build_ui()
        self._populate_presets()
        self._populate_native_toolbars()
        self._populate_toolbar_list()
        self._populate_available_actions()
        self._select_initial_toolbar()
        self._update_editor_state()

    def toolbar_definitions(self):
        return copy.deepcopy(self._toolbar_definitions)

    def hidden_toolbar_ids(self):
        hidden_ids = []
        for index in range(self.native_toolbar_list.count()):
            item = self.native_toolbar_list.item(index)
            if item.checkState() != Qt.Checked:
                hidden_ids.append(item.data(Qt.UserRole))
        return hidden_ids

    def branding_enabled(self):
        return bool(self.branding_checkbox.isChecked())

    def show_plugin_toolbar_button(self):
        return bool(self.plugin_button_checkbox.isChecked())

    def _build_ui(self):
        root_layout = QVBoxLayout(self)

        help_label = QLabel(
            "Baue eigene kompakte Werkzeugleisten, halte Originale bei Bedarf sichtbar, "
            "und exportiere fertige Setups als Preset-Datei."
        )
        help_label.setWordWrap(True)
        root_layout.addWidget(help_label)

        splitter = QSplitter(Qt.Horizontal, self)

        left_panel = QWidget(splitter)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)

        options_group = QGroupBox("Optionen", left_panel)
        options_layout = QVBoxLayout(options_group)
        options_layout.setSpacing(8)

        self.branding_checkbox = QCheckBox(
            "Branding-Logo links oben anzeigen",
            options_group,
        )
        self.branding_checkbox.setChecked(self._branding_enabled)
        options_layout.addWidget(self.branding_checkbox)

        branding_hint = QLabel(
            "Zeigt dein logo.svg als feste, nicht klickbare Branding-Leiste ganz links oben."
        )
        branding_hint.setWordWrap(True)
        options_layout.addWidget(branding_hint)

        self.plugin_button_checkbox = QCheckBox(
            "Plugin-Button in QGIS-Toolbar anzeigen",
            options_group,
        )
        self.plugin_button_checkbox.setChecked(self._show_plugin_toolbar_button)
        options_layout.addWidget(self.plugin_button_checkbox)
        left_layout.addWidget(options_group, 1)

        preset_group = QGroupBox("Vorlagen", left_panel)
        preset_layout = QVBoxLayout(preset_group)
        preset_layout.setSpacing(10)

        self.preset_combo = QComboBox(preset_group)
        self.preset_combo.currentIndexChanged.connect(
            self._on_preset_selection_changed
        )
        preset_layout.addWidget(self.preset_combo)

        self.preset_description_label = QLabel(preset_group)
        self.preset_description_label.setWordWrap(True)
        preset_layout.addWidget(self.preset_description_label)

        preset_button_row_top = QHBoxLayout()
        self.apply_preset_button = QPushButton("Vorlage ersetzen", preset_group)
        self.apply_preset_button.clicked.connect(self._apply_selected_preset)
        self.import_preset_button = QPushButton("Preset importieren", preset_group)
        self.import_preset_button.clicked.connect(self._import_preset)
        preset_button_row_top.addWidget(self.apply_preset_button)
        preset_button_row_top.addWidget(self.import_preset_button)
        preset_layout.addLayout(preset_button_row_top)

        preset_button_row_bottom = QHBoxLayout()
        self.export_preset_button = QPushButton("Preset exportieren", preset_group)
        self.export_preset_button.clicked.connect(self._export_preset)
        preset_button_row_bottom.addWidget(self.export_preset_button)
        preset_button_row_bottom.addStretch(1)
        preset_layout.addLayout(preset_button_row_bottom)

        export_hint_label = QLabel(
            "Exportierte JSON-Dateien kannst du spaeter direkt wieder importieren oder mir zum Einbauen schicken."
        )
        export_hint_label.setWordWrap(True)
        preset_layout.addWidget(export_hint_label)
        left_layout.addWidget(preset_group, 2)

        native_group = QGroupBox("Standardleisten", left_panel)
        native_layout = QVBoxLayout(native_group)
        native_layout.setSpacing(10)

        native_controls = QHBoxLayout()
        show_all_button = QPushButton("Alle einblenden", native_group)
        show_all_button.clicked.connect(lambda: self._set_all_native_toolbars(True))
        hide_all_button = QPushButton("Alle ausblenden", native_group)
        hide_all_button.clicked.connect(lambda: self._set_all_native_toolbars(False))
        native_controls.addWidget(show_all_button)
        native_controls.addWidget(hide_all_button)
        native_controls.addStretch(1)
        native_layout.addLayout(native_controls)

        native_hint = QLabel(
            "Custom-Toolbars duplizieren Werkzeuge jetzt, die Originale bleiben also erhalten. Hier blendest du sie nur bei Bedarf aus."
        )
        native_hint.setWordWrap(True)
        native_layout.addWidget(native_hint)

        self.native_toolbar_list = QListWidget(native_group)
        self.native_toolbar_list.setAlternatingRowColors(True)
        native_layout.addWidget(self.native_toolbar_list)
        left_layout.addWidget(native_group, 3)

        toolbar_group = QGroupBox("Eigene Werkzeugleisten", left_panel)
        toolbar_layout = QVBoxLayout(toolbar_group)
        toolbar_layout.setSpacing(10)

        self.toolbar_list = QListWidget(toolbar_group)
        self.toolbar_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.toolbar_list.currentItemChanged.connect(
            self._on_toolbar_selection_changed
        )
        self.toolbar_list.itemChanged.connect(self._on_toolbar_item_changed)
        toolbar_layout.addWidget(self.toolbar_list)

        toolbar_button_row = QHBoxLayout()
        new_toolbar_button = QPushButton("Neu", toolbar_group)
        new_toolbar_button.clicked.connect(self._add_toolbar)
        copy_toolbar_button = QPushButton(
            "Aus Standardleiste kopieren",
            toolbar_group,
        )
        copy_toolbar_button.clicked.connect(self._copy_native_toolbar_template)
        rename_toolbar_button = QPushButton("Umbenennen", toolbar_group)
        rename_toolbar_button.clicked.connect(self._rename_toolbar)
        delete_toolbar_button = QPushButton("Loeschen", toolbar_group)
        delete_toolbar_button.clicked.connect(self._delete_toolbar)
        toolbar_button_row.addWidget(new_toolbar_button)
        toolbar_button_row.addWidget(copy_toolbar_button)
        toolbar_button_row.addWidget(rename_toolbar_button)
        toolbar_button_row.addWidget(delete_toolbar_button)
        toolbar_layout.addLayout(toolbar_button_row)
        left_layout.addWidget(toolbar_group, 3)

        right_panel = QWidget(splitter)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        available_group = QGroupBox("Verfuegbare Tools", right_panel)
        available_layout = QVBoxLayout(available_group)
        available_layout.setSpacing(10)

        self.search_input = QLineEdit(available_group)
        self.search_input.setPlaceholderText(
            "Suche nach Name, Quelle, Dropdown-Eintrag oder Action-ID"
        )
        self.search_input.textChanged.connect(self._filter_available_actions)
        available_layout.addWidget(self.search_input)

        self.available_actions_tree = QTreeWidget(available_group)
        self.available_actions_tree.setRootIsDecorated(False)
        self.available_actions_tree.setAlternatingRowColors(True)
        self.available_actions_tree.setSelectionMode(
            QAbstractItemView.ExtendedSelection
        )
        self.available_actions_tree.setHeaderLabels(["Werkzeug", "Quelle", "ID"])
        self.available_actions_tree.itemDoubleClicked.connect(
            lambda *_: self._add_selected_actions()
        )
        self.available_actions_tree.setUniformRowHeights(True)
        available_layout.addWidget(self.available_actions_tree)

        available_button_row = QHBoxLayout()
        self.add_action_button = QPushButton(
            "Einzeln hinzufuegen",
            available_group,
        )
        self.add_action_button.clicked.connect(self._add_selected_actions)
        self.add_dropdown_button = QPushButton(
            "Als Dropdown",
            available_group,
        )
        self.add_dropdown_button.clicked.connect(self._add_selected_dropdown)
        available_button_row.addWidget(self.add_action_button)
        available_button_row.addWidget(self.add_dropdown_button)
        available_layout.addLayout(available_button_row)
        right_layout.addWidget(available_group, 3)

        current_group = QGroupBox("In ausgewaehlter Leiste", right_panel)
        current_layout = QVBoxLayout(current_group)
        current_layout.setSpacing(10)

        self.current_actions_list = QListWidget(current_group)
        self.current_actions_list.setSelectionMode(
            QAbstractItemView.ExtendedSelection
        )
        current_layout.addWidget(self.current_actions_list)

        current_button_row_top = QHBoxLayout()
        self.separator_button = QPushButton("Trennlinie", current_group)
        self.separator_button.clicked.connect(self._insert_separator)
        self.remove_action_button = QPushButton("Entfernen", current_group)
        self.remove_action_button.clicked.connect(self._remove_selected_actions)
        current_button_row_top.addWidget(self.separator_button)
        current_button_row_top.addWidget(self.remove_action_button)
        current_layout.addLayout(current_button_row_top)

        current_button_row_bottom = QHBoxLayout()
        self.move_up_button = QPushButton("Nach oben", current_group)
        self.move_up_button.clicked.connect(lambda: self._move_selected_action(-1))
        self.move_down_button = QPushButton("Nach unten", current_group)
        self.move_down_button.clicked.connect(lambda: self._move_selected_action(1))
        current_button_row_bottom.addWidget(self.move_up_button)
        current_button_row_bottom.addWidget(self.move_down_button)
        current_layout.addLayout(current_button_row_bottom)
        right_layout.addWidget(current_group, 2)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        root_layout.addWidget(splitter, 1)

        button_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            parent=self,
        )
        self.reset_button = button_box.addButton(
            "Auf QGIS-Standard zuruecksetzen",
            QDialogButtonBox.ResetRole,
        )
        self.reset_button.clicked.connect(self._reset_to_qgis_defaults)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        save_button = button_box.button(QDialogButtonBox.Save)
        cancel_button = button_box.button(QDialogButtonBox.Cancel)
        if save_button is not None:
            save_button.setText("Speichern")
        if cancel_button is not None:
            cancel_button.setText("Abbrechen")
        root_layout.addWidget(button_box)

    def _populate_presets(self):
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("Vorlage waehlen", None)
        for preset in self._built_in_presets:
            self.preset_combo.addItem(preset.get("name", "Preset"), preset["id"])
        self.preset_combo.blockSignals(False)
        self._on_preset_selection_changed()

    def _preset_by_id(self, preset_id):
        for preset in self._built_in_presets:
            if preset.get("id") == preset_id:
                return preset
        return None

    def _on_preset_selection_changed(self):
        preset = self._preset_by_id(self.preset_combo.currentData())
        self.apply_preset_button.setEnabled(preset is not None)
        if preset is None:
            self.preset_description_label.setText(
                "Vorlagen aus dem Plugin koennen hier direkt angewendet werden."
            )
            return

        description = preset.get("description") or "Keine Beschreibung hinterlegt."
        self.preset_description_label.setText(description)

    def _apply_selected_preset(self):
        preset = self._preset_by_id(self.preset_combo.currentData())
        if preset is None:
            return

        if self._has_current_configuration():
            result = QMessageBox.question(
                self,
                "Vorlage anwenden",
                "Die aktuelle Konfiguration im Dialog wird durch die Vorlage ersetzt. Fortfahren?",
            )
            if result != QMessageBox.Yes:
                return

        self._apply_preset_data(preset)

    def _apply_preset_data(self, preset):
        self._toolbar_definitions = self._normalize_toolbar_definitions(
            preset.get("toolbars", [])
        )
        self._hidden_toolbar_ids = set(
            self._normalize_hidden_toolbar_ids(
                preset.get("hidden_toolbar_ids", [])
            )
        )

        if "branding_enabled" in preset:
            self.branding_checkbox.setChecked(bool(preset["branding_enabled"]))
        if "show_plugin_toolbar_button" in preset:
            self.plugin_button_checkbox.setChecked(
                bool(preset["show_plugin_toolbar_button"])
            )

        self._populate_native_toolbars()
        self._populate_toolbar_list()
        self._select_initial_toolbar()
        self._update_editor_state()

    def _import_preset(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Preset importieren",
            "",
            self.PRESET_FILE_FILTER,
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Preset importieren",
                "Die Datei konnte nicht gelesen werden:\n{}".format(exc),
            )
            return

        preset = self._normalize_preset_payload(
            payload,
            fallback_name=os.path.splitext(os.path.basename(file_path))[0],
            fallback_description="Importiert aus {}".format(
                os.path.basename(file_path)
            ),
        )
        if preset is None:
            QMessageBox.warning(
                self,
                "Preset importieren",
                "Die Datei hat kein gueltiges Preset-Format.",
            )
            return

        self._apply_preset_data(preset)
        QMessageBox.information(
            self,
            "Preset importiert",
            'Preset "{}" wurde in den Dialog geladen.'.format(
                preset["name"]
            ),
        )

    def _export_preset(self):
        suggested_name = self._default_export_name()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Preset exportieren",
            suggested_name,
            self.PRESET_FILE_FILTER,
        )
        if not file_path:
            return

        if not file_path.lower().endswith(".json"):
            file_path += ".json"

        payload = self._current_preset_payload(file_path)
        try:
            with open(file_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=True)
                handle.write("\n")
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Preset exportieren",
                "Die Datei konnte nicht geschrieben werden:\n{}".format(exc),
            )
            return

        QMessageBox.information(
            self,
            "Preset exportiert",
            "Preset gespeichert unter:\n{}\n\nDiese JSON-Datei kannst du spaeter direkt weitergeben.".format(
                file_path
            ),
        )

    def _current_preset_payload(self, file_path):
        return {
            "schema_version": 1,
            "name": self._clean_text(
                os.path.splitext(os.path.basename(file_path))[0]
            )
            or "Preset",
            "description": "Exportiert aus Custom Toolbar Overlay.",
            "branding_enabled": self.branding_enabled(),
            "show_plugin_toolbar_button": self.show_plugin_toolbar_button(),
            "hidden_native_toolbars": self.hidden_toolbar_ids(),
            "toolbars": self.toolbar_definitions(),
        }

    def _default_export_name(self):
        if len(self._toolbar_definitions) == 1:
            return "{}.json".format(
                self._slugify(self._toolbar_definitions[0]["title"]) or "preset"
            )
        return "custom-toolbar-preset.json"

    def _has_current_configuration(self):
        if self._toolbar_definitions:
            return True
        if self.hidden_toolbar_ids():
            return True
        if self.branding_enabled():
            return True
        if not self.show_plugin_toolbar_button():
            return True
        return False

    def _reset_to_qgis_defaults(self):
        if self._has_current_configuration():
            result = QMessageBox.question(
                self,
                "Auf QGIS-Standard zuruecksetzen",
                "Alle Custom-Toolbars werden entfernt, alle Standardleisten wieder eingeblendet und Branding deaktiviert. Fortfahren?",
            )
            if result != QMessageBox.Yes:
                return

        self._toolbar_definitions = []
        self._hidden_toolbar_ids = set()
        self.branding_checkbox.setChecked(False)
        self.plugin_button_checkbox.setChecked(True)
        self.preset_combo.setCurrentIndex(0)
        self._populate_native_toolbars()
        self._populate_toolbar_list()
        self.current_actions_list.clear()
        self._update_editor_state()

    def _normalize_preset_payload(
        self,
        payload,
        fallback_name="",
        fallback_description="",
    ):
        if not isinstance(payload, dict):
            return None

        name = self._clean_text(payload.get("name")) or self._clean_text(
            fallback_name
        )
        if not name:
            name = "Preset"

        description = self._clean_text(payload.get("description")) or self._clean_text(
            fallback_description
        )

        hidden_raw = payload.get("hidden_native_toolbars")
        if hidden_raw is None:
            hidden_raw = payload.get("hidden_toolbars", [])

        return {
            "id": self._slugify(name) or "preset",
            "name": name,
            "description": description,
            "branding_enabled": bool(
                payload.get("branding_enabled", self.branding_enabled())
            ),
            "show_plugin_toolbar_button": bool(
                payload.get(
                    "show_plugin_toolbar_button",
                    self.show_plugin_toolbar_button(),
                )
            ),
            "toolbars": self._normalize_toolbar_definitions(
                payload.get("toolbars", [])
            ),
            "hidden_toolbar_ids": self._normalize_hidden_toolbar_ids(hidden_raw),
        }

    def _normalize_hidden_toolbar_ids(self, raw_ids):
        return [
            str(toolbar_id).strip()
            for toolbar_id in raw_ids or []
            if str(toolbar_id).strip()
        ]

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

    def _populate_native_toolbars(self):
        self.native_toolbar_list.clear()
        for entry in self._native_toolbars:
            item = QListWidgetItem(entry["label"])
            item.setData(Qt.UserRole, entry["id"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Unchecked
                if entry["id"] in self._hidden_toolbar_ids
                else Qt.Checked
            )
            self.native_toolbar_list.addItem(item)

    def _populate_toolbar_list(self):
        self._updating_toolbar_items = True
        self.toolbar_list.clear()
        for definition in self._toolbar_definitions:
            item = QListWidgetItem(definition["title"])
            item.setData(Qt.UserRole, definition["id"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if definition.get("visible", True) else Qt.Unchecked
            )
            self.toolbar_list.addItem(item)
        self._updating_toolbar_items = False

    def _populate_available_actions(self):
        self.available_actions_tree.clear()
        for entry in self._available_actions:
            label = entry.get("label", "")
            if entry.get("is_native_dropdown"):
                label = "{} [QGIS-Dropdown]".format(label)
            sources = ", ".join(entry.get("sources", []))
            item = QTreeWidgetItem(
                [
                    label,
                    sources,
                    entry.get("id", ""),
                ]
            )
            item.setData(0, Qt.UserRole, entry.get("id"))
            self.available_actions_tree.addTopLevelItem(item)
        self.available_actions_tree.sortItems(0, Qt.AscendingOrder)

    def _select_initial_toolbar(self):
        if self.toolbar_list.count() > 0:
            self.toolbar_list.setCurrentRow(0)

    def _set_all_native_toolbars(self, visible):
        target_state = Qt.Checked if visible else Qt.Unchecked
        for index in range(self.native_toolbar_list.count()):
            self.native_toolbar_list.item(index).setCheckState(target_state)

    def _add_toolbar(self):
        title, accepted = QInputDialog.getText(
            self,
            "Neue Werkzeugleiste",
            "Name der Werkzeugleiste:",
            text=self._default_toolbar_title(),
        )
        if not accepted:
            return

        clean_title = self._clean_text(title)
        if not clean_title:
            return

        toolbar_id = self._unique_toolbar_id(clean_title)
        self._toolbar_definitions.append(
            {
                "id": toolbar_id,
                "title": clean_title,
                "visible": True,
                "actions": [],
            }
        )
        self._populate_toolbar_list()
        self._select_toolbar_by_id(toolbar_id)
        self._update_editor_state()

    def _copy_native_toolbar_template(self):
        if not self._native_toolbar_templates:
            QMessageBox.information(
                self,
                "Keine Standardleisten",
                "Es wurden keine kopierbaren QGIS-Standardleisten gefunden.",
            )
            return

        labels = [
            template.get("label", "Standardleiste")
            for template in self._native_toolbar_templates
        ]
        current_native_item = self.native_toolbar_list.currentItem()
        current_native_id = (
            current_native_item.data(Qt.UserRole)
            if current_native_item is not None
            else None
        )
        default_index = 0
        if current_native_id is not None:
            for index, template in enumerate(self._native_toolbar_templates):
                if template.get("id") == current_native_id:
                    default_index = index
                    break

        selected_label, accepted = QInputDialog.getItem(
            self,
            "Standardleiste kopieren",
            "QGIS-Werkzeugleiste:",
            labels,
            default_index,
            False,
        )
        if not accepted:
            return

        template = None
        for entry in self._native_toolbar_templates:
            if entry.get("label") == selected_label:
                template = entry
                break
        if template is None:
            return

        template_actions = copy.deepcopy(template.get("actions", []))
        if not template_actions:
            QMessageBox.information(
                self,
                "Leiste leer",
                "Diese Standardleiste enthaelt keine kopierbaren Werkzeuge.",
            )
            return

        suggested_title = self._default_copy_title(template.get("label", "Kopie"))
        title, accepted = QInputDialog.getText(
            self,
            "Kopie anlegen",
            "Name der neuen Werkzeugleiste:",
            text=suggested_title,
        )
        if not accepted:
            return

        clean_title = self._clean_text(title)
        if not clean_title:
            return

        toolbar_id = self._unique_toolbar_id(clean_title)
        self._toolbar_definitions.append(
            {
                "id": toolbar_id,
                "title": clean_title,
                "visible": True,
                "actions": template_actions,
            }
        )
        self._populate_toolbar_list()
        self._select_toolbar_by_id(toolbar_id)
        self._update_editor_state()

    def _rename_toolbar(self):
        index = self._selected_toolbar_index()
        if index is None:
            return

        definition = self._toolbar_definitions[index]
        title, accepted = QInputDialog.getText(
            self,
            "Werkzeugleiste umbenennen",
            "Neuer Name:",
            text=definition["title"],
        )
        if not accepted:
            return

        clean_title = self._clean_text(title)
        if not clean_title:
            return

        definition["title"] = clean_title
        self._populate_toolbar_list()
        self._select_toolbar_by_id(definition["id"])

    def _delete_toolbar(self):
        index = self._selected_toolbar_index()
        if index is None:
            return

        definition = self._toolbar_definitions[index]
        result = QMessageBox.question(
            self,
            "Werkzeugleiste loeschen",
            'Werkzeugleiste "{}" wirklich loeschen?'.format(
                definition["title"]
            ),
        )
        if result != QMessageBox.Yes:
            return

        del self._toolbar_definitions[index]
        self._populate_toolbar_list()
        self._select_initial_toolbar()
        self._update_editor_state()

    def _on_toolbar_selection_changed(self, current, previous):
        del previous
        if current is None:
            self.current_actions_list.clear()
            self._update_editor_state()
            return

        toolbar_id = current.data(Qt.UserRole)
        definition = self._definition_by_id(toolbar_id)
        if definition is None:
            self.current_actions_list.clear()
            self._update_editor_state()
            return

        self._populate_current_actions(definition["actions"])
        self._update_editor_state()

    def _on_toolbar_item_changed(self, item):
        if self._updating_toolbar_items or item is None:
            return

        definition = self._definition_by_id(item.data(Qt.UserRole))
        if definition is None:
            return

        definition["visible"] = item.checkState() == Qt.Checked

    def _populate_current_actions(self, actions):
        self.current_actions_list.clear()
        for action_definition in actions:
            item = QListWidgetItem(self._action_display_label(action_definition))
            item.setData(Qt.UserRole, copy.deepcopy(action_definition))
            self.current_actions_list.addItem(item)

    def _action_display_label(self, action_definition):
        action_type = action_definition["type"]
        if action_type == "separator":
            return "----- Trennlinie -----"
        if action_type == "logo":
            return "[Logo] {}".format(
                self._clean_text(action_definition.get("label")) or "Branding"
            )
        if action_type == "dropdown":
            return "[Dropdown] {} ({} Eintraege)".format(
                self._clean_text(action_definition.get("label")) or "Dropdown",
                len(action_definition.get("actions", [])),
            )

        entry = self._action_lookup.get(action_definition["id"])
        if entry is None:
            return "[Fehlt] {}".format(action_definition["id"])

        label = entry.get("label", action_definition["id"])
        if entry.get("is_native_dropdown"):
            label = "[QGIS-Dropdown] {}".format(label)

        sources = ", ".join(entry.get("sources", []))
        if sources:
            return "{} ({})".format(
                label,
                sources,
            )
        return label

    def _add_selected_actions(self):
        index = self._selected_toolbar_index()
        if index is None:
            QMessageBox.information(
                self,
                "Keine Werkzeugleiste",
                "Lege zuerst eine eigene Werkzeugleiste an oder waehle eine aus.",
            )
            return

        selected_items = self.available_actions_tree.selectedItems()
        if not selected_items:
            return

        definition = self._toolbar_definitions[index]
        for item in selected_items:
            action_id = item.data(0, Qt.UserRole)
            if action_id:
                definition["actions"].append({"type": "action", "id": action_id})

        self._populate_current_actions(definition["actions"])

    def _add_selected_dropdown(self):
        index = self._selected_toolbar_index()
        if index is None:
            QMessageBox.information(
                self,
                "Keine Werkzeugleiste",
                "Lege zuerst eine eigene Werkzeugleiste an oder waehle eine aus.",
            )
            return

        selected_items = self.available_actions_tree.selectedItems()
        action_ids = []
        selected_labels = []
        for item in selected_items:
            action_id = item.data(0, Qt.UserRole)
            if action_id:
                action_ids.append(action_id)
                selected_labels.append(item.text(0))

        if not action_ids:
            return

        default_label = "Dropdown"
        if len(selected_labels) == 1:
            default_label = selected_labels[0]
        elif selected_labels:
            default_label = "{} Gruppe".format(selected_labels[0])

        label, accepted = QInputDialog.getText(
            self,
            "Dropdown erstellen",
            "Bezeichnung fuer das Dropdown:",
            text=default_label,
        )
        if not accepted:
            return

        clean_label = self._clean_text(label)
        if not clean_label:
            return

        definition = self._toolbar_definitions[index]
        definition["actions"].append(
            {
                "type": "dropdown",
                "label": clean_label,
                "actions": action_ids,
            }
        )
        self._populate_current_actions(definition["actions"])

    def _insert_separator(self):
        index = self._selected_toolbar_index()
        if index is None:
            return

        definition = self._toolbar_definitions[index]
        definition["actions"].append({"type": "separator"})
        self._populate_current_actions(definition["actions"])
        self.current_actions_list.setCurrentRow(
            self.current_actions_list.count() - 1
        )

    def _remove_selected_actions(self):
        index = self._selected_toolbar_index()
        if index is None:
            return

        selected_rows = sorted(
            {
                current_item.row()
                for current_item in self.current_actions_list.selectedIndexes()
            },
            reverse=True,
        )
        if not selected_rows:
            return

        definition = self._toolbar_definitions[index]
        for row in selected_rows:
            del definition["actions"][row]

        self._populate_current_actions(definition["actions"])

    def _move_selected_action(self, offset):
        index = self._selected_toolbar_index()
        if index is None:
            return

        current_row = self.current_actions_list.currentRow()
        if current_row < 0:
            return

        definition = self._toolbar_definitions[index]
        target_row = current_row + offset
        if target_row < 0 or target_row >= len(definition["actions"]):
            return

        action_definition = definition["actions"].pop(current_row)
        definition["actions"].insert(target_row, action_definition)
        self._populate_current_actions(definition["actions"])
        self.current_actions_list.setCurrentRow(target_row)

    def _filter_available_actions(self, text):
        needle = self._clean_text(text).lower()
        for index in range(self.available_actions_tree.topLevelItemCount()):
            item = self.available_actions_tree.topLevelItem(index)
            haystack = " ".join(
                [item.text(0), item.text(1), item.text(2)]
            ).lower()
            item.setHidden(bool(needle) and needle not in haystack)

    def _selected_toolbar_index(self):
        current_item = self.toolbar_list.currentItem()
        if current_item is None:
            return None

        toolbar_id = current_item.data(Qt.UserRole)
        for index, definition in enumerate(self._toolbar_definitions):
            if definition["id"] == toolbar_id:
                return index
        return None

    def _definition_by_id(self, toolbar_id):
        for definition in self._toolbar_definitions:
            if definition["id"] == toolbar_id:
                return definition
        return None

    def _select_toolbar_by_id(self, toolbar_id):
        for index in range(self.toolbar_list.count()):
            item = self.toolbar_list.item(index)
            if item.data(Qt.UserRole) == toolbar_id:
                self.toolbar_list.setCurrentItem(item)
                return

    def _default_toolbar_title(self):
        existing_titles = {
            definition["title"].lower() for definition in self._toolbar_definitions
        }
        suffix = 1
        while True:
            title = "Meine Leiste {}".format(suffix)
            if title.lower() not in existing_titles:
                return title
            suffix += 1

    def _default_copy_title(self, base_label):
        clean_base = self._clean_text(base_label) or "Standardleiste"
        existing_titles = {
            definition["title"].lower() for definition in self._toolbar_definitions
        }

        first_candidate = "{} Kopie".format(clean_base)
        if first_candidate.lower() not in existing_titles:
            return first_candidate

        suffix = 2
        while True:
            candidate = "{} Kopie {}".format(clean_base, suffix)
            if candidate.lower() not in existing_titles:
                return candidate
            suffix += 1

    def _unique_toolbar_id(self, title, seen_ids=None):
        base = self._slugify(title)
        if not base:
            base = "toolbar"

        if seen_ids is None:
            seen_ids = {definition["id"] for definition in self._toolbar_definitions}
        candidate = base
        suffix = 2
        while candidate in seen_ids:
            candidate = "{}-{}".format(base, suffix)
            suffix += 1
        if isinstance(seen_ids, set):
            seen_ids.add(candidate)
        return candidate

    def _dedupe_toolbar_id(self, base_id, seen_ids):
        candidate = str(base_id).strip() or "toolbar"
        suffix = 2
        while candidate in seen_ids:
            candidate = "{}-{}".format(base_id, suffix)
            suffix += 1
        seen_ids.add(candidate)
        return candidate

    def _clean_text(self, value):
        text = str(value or "")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _slugify(self, value):
        text = self._clean_text(value).lower()
        text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
        return text

    def _normalize_int(self, value, default):
        try:
            parsed = int(value)
        except Exception:
            return default
        return max(12, min(parsed, 96))

    def _update_editor_state(self):
        has_toolbar = self._selected_toolbar_index() is not None
        self.available_actions_tree.setEnabled(has_toolbar)
        self.current_actions_list.setEnabled(has_toolbar)
        self.add_action_button.setEnabled(has_toolbar)
        self.add_dropdown_button.setEnabled(has_toolbar)
        self.separator_button.setEnabled(has_toolbar)
        self.remove_action_button.setEnabled(has_toolbar)
        self.move_up_button.setEnabled(has_toolbar)
        self.move_down_button.setEnabled(has_toolbar)
