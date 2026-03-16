import json
from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QAction,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from qgis.core import (
    QgsExpression,
    QgsMapLayerType,
    QgsRuleBasedRenderer,
    QgsSymbol,
    QgsWkbTypes,
)


DEFAULT_CONFIG = {
    "presets": {
        "betreiber": {
            "label": "Preset: Betreiber",
            "aliases": [
                "betreiber",
                "netzbetreiber",
                "operator",
                "owner",
                "company",
                "provider",
            ],
        },
        "sparte": {
            "label": "Preset: Sparte",
            "aliases": [
                "sparte",
                "segment",
                "category",
                "typ",
                "type",
                "branche",
            ],
        },
    }
}


class QuickruleDialog(QDialog):
    def __init__(self, parent, layer, config):
        super().__init__(parent)
        self.layer = layer
        self.config = config
        self.field_names = [field.name() for field in self.layer.fields()]

        self.preset_combo = None
        self.field_combo = None
        self.mode_combo = None
        self.search_edit = None
        self.value_list = None
        self.state_label = None
        self.selection_label = None

        self._build_ui()
        self._populate_presets()
        self._populate_fields()
        self._bind_events()
        self._reload_values()

    def _build_ui(self):
        self.setWindowTitle("Quickrule Einstellungen")
        self.resize(760, 560)
        self.setStyleSheet(
            """
            QDialog {
                background-color: #eef4f6;
            }
            QFrame#quickruleHeader {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #0e4257, stop: 1 #1a718a
                );
                border-radius: 10px;
                padding: 10px;
            }
            QLabel#quickruleTitle {
                color: #ffffff;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#quickruleSubtitle {
                color: #d9edf3;
            }
            QFrame#quickruleCard {
                background-color: #ffffff;
                border: 1px solid #c9d8de;
                border-radius: 10px;
            }
            QLabel#quickruleState {
                color: #22556a;
                font-weight: 600;
            }
            QListWidget {
                border: 1px solid #c9d8de;
                border-radius: 8px;
                background-color: #fbfdfe;
            }
            QPushButton {
                background-color: #e6f0f3;
                border: 1px solid #b6ccd5;
                border-radius: 6px;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #d7e8ee;
            }
            """
        )

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        header = QFrame()
        header.setObjectName("quickruleHeader")
        header_layout = QVBoxLayout(header)
        header_title = QLabel("Quickrule Overlay")
        header_title.setObjectName("quickruleTitle")
        header_subtitle = QLabel(
            "Preset waehlen, Werte markieren, Regeln und/oder Layer-Filter anwenden."
        )
        header_subtitle.setObjectName("quickruleSubtitle")
        header_layout.addWidget(header_title)
        header_layout.addWidget(header_subtitle)
        root_layout.addWidget(header)

        card = QFrame()
        card.setObjectName("quickruleCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(10)
        root_layout.addWidget(card)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self.preset_combo = QComboBox()
        self.field_combo = QComboBox()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Regelbasierung", "rules")
        self.mode_combo.addItem("Layer-Filter", "filter")
        self.mode_combo.addItem("Regeln + Layer-Filter", "both")

        top_row.addLayout(self._labeled_widget("Preset", self.preset_combo))
        top_row.addLayout(self._labeled_widget("Spalte", self.field_combo))
        top_row.addLayout(self._labeled_widget("Modus", self.mode_combo))
        card_layout.addLayout(top_row)

        self.state_label = QLabel("Preset bereit.")
        self.state_label.setObjectName("quickruleState")
        card_layout.addWidget(self.state_label)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Werte filtern (Suche)...")
        search_row.addLayout(self._labeled_widget("Wertesuche", self.search_edit))
        card_layout.addLayout(search_row)

        self.value_list = QListWidget()
        card_layout.addWidget(self.value_list, stretch=1)

        value_button_row = QHBoxLayout()
        select_visible_button = QPushButton("Alle sichtbar")
        clear_visible_button = QPushButton("Keine sichtbar")
        value_button_row.addWidget(select_visible_button)
        value_button_row.addWidget(clear_visible_button)
        value_button_row.addStretch(1)
        self.selection_label = QLabel("Ausgewaehlt: 0")
        value_button_row.addWidget(self.selection_label)
        card_layout.addLayout(value_button_row)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        card_layout.addWidget(button_box)

        select_visible_button.clicked.connect(lambda: self._set_visible_items_checked(True))
        clear_visible_button.clicked.connect(lambda: self._set_visible_items_checked(False))
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

    def _bind_events(self):
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self.field_combo.currentIndexChanged.connect(self._reload_values)
        self.search_edit.textChanged.connect(self._filter_visible_values)
        self.value_list.itemChanged.connect(self._update_selection_label)

    def _labeled_widget(self, label_text, widget):
        wrapper = QVBoxLayout()
        wrapper.setSpacing(4)
        wrapper.addWidget(QLabel(label_text))
        wrapper.addWidget(widget)
        return wrapper

    def _populate_presets(self):
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("Manuell", "")

        presets = self.config.get("presets", {})
        for key, preset in presets.items():
            label = preset.get("label", key)
            self.preset_combo.addItem(str(label), key)
        self.preset_combo.blockSignals(False)

    def _populate_fields(self):
        self.field_combo.blockSignals(True)
        self.field_combo.clear()
        self.field_combo.addItems(self.field_names)
        self.field_combo.blockSignals(False)

        if not self.field_names:
            self.state_label.setText("Layer enthaelt keine Attributspalten.")
            return

        for key in self.config.get("presets", {}):
            field_name = self._find_field_for_preset(key)
            if field_name:
                preset_index = self.preset_combo.findData(key)
                if preset_index >= 0:
                    self.preset_combo.setCurrentIndex(preset_index)
                field_index = self.field_combo.findText(field_name)
                if field_index >= 0:
                    self.field_combo.setCurrentIndex(field_index)
                return

    def _on_preset_changed(self):
        preset_key = self.preset_combo.currentData()
        if not preset_key:
            self.state_label.setText("Manuelle Spaltenauswahl aktiv.")
            return

        field_name = self._find_field_for_preset(preset_key)
        if not field_name:
            preset_text = self.preset_combo.currentText()
            self.state_label.setText(
                f"Kein Alias von '{preset_text}' passt zu einer Layer-Spalte."
            )
            return

        index = self.field_combo.findText(field_name)
        if index >= 0:
            self.field_combo.setCurrentIndex(index)
        self.state_label.setText(f"Preset nutzt Spalte: {field_name}")

    def _find_field_for_preset(self, preset_key):
        preset = self.config.get("presets", {}).get(preset_key, {})
        aliases = preset.get("aliases", [])
        lookup = {field_name.lower(): field_name for field_name in self.field_names}
        for alias in aliases:
            alias_key = str(alias).strip().lower()
            if not alias_key:
                continue
            if alias_key in lookup:
                return lookup[alias_key]
        return None

    def _reload_values(self):
        self.value_list.blockSignals(True)
        self.value_list.clear()

        field_name = self.field_combo.currentText()
        if not field_name:
            self.value_list.blockSignals(False)
            self._update_selection_label()
            return

        field_index = self.layer.fields().indexOf(field_name)
        if field_index < 0:
            self.value_list.blockSignals(False)
            self._update_selection_label()
            return

        values = self._collect_sorted_unique_values(self.layer, field_index)
        for value in values:
            label = "(NULL)" if value is None else str(value)
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, value)
            self.value_list.addItem(item)

        self.value_list.blockSignals(False)
        self._filter_visible_values()
        self._update_selection_label()

    def _filter_visible_values(self):
        query = self.search_edit.text().strip().lower()
        for index in range(self.value_list.count()):
            item = self.value_list.item(index)
            is_visible = not query or query in item.text().lower()
            item.setHidden(not is_visible)

    def _set_visible_items_checked(self, checked):
        state = Qt.Checked if checked else Qt.Unchecked
        self.value_list.blockSignals(True)
        for index in range(self.value_list.count()):
            item = self.value_list.item(index)
            if item.isHidden():
                continue
            item.setCheckState(state)
        self.value_list.blockSignals(False)
        self._update_selection_label()

    def _update_selection_label(self):
        total = self.value_list.count()
        selected = 0
        for index in range(total):
            item = self.value_list.item(index)
            if item.checkState() == Qt.Checked:
                selected += 1
        self.selection_label.setText(f"Ausgewaehlt: {selected} / {total}")

    def selection(self):
        selected_values = []
        for index in range(self.value_list.count()):
            item = self.value_list.item(index)
            if item.checkState() == Qt.Checked:
                selected_values.append(item.data(Qt.UserRole))

        return {
            "field_name": self.field_combo.currentText().strip(),
            "mode": self.mode_combo.currentData(),
            "selected_values": selected_values,
        }

    def accept(self):
        if not self.field_combo.currentText().strip():
            QMessageBox.warning(self, "Quickrule", "Bitte eine Spalte auswaehlen.")
            return

        if not self.selection()["selected_values"]:
            QMessageBox.warning(self, "Quickrule", "Bitte mindestens einen Wert auswaehlen.")
            return
        super().accept()

    def _collect_sorted_unique_values(self, layer, field_index):
        raw_values = list(layer.uniqueValues(field_index))
        normalized = [self._normalize_value(value) for value in raw_values]
        deduplicated = []
        seen = set()
        for value in normalized:
            token = self._tokenize_value(value)
            if token in seen:
                continue
            seen.add(token)
            deduplicated.append(value)
        deduplicated.sort(key=self._sort_key_for_value)
        return deduplicated

    def _normalize_value(self, value):
        if value is None:
            return None
        if hasattr(value, "isNull") and value.isNull():
            return None
        return value

    def _tokenize_value(self, value):
        if value is None:
            return ("NULL", "")
        return (type(value).__name__, str(value))

    def _sort_key_for_value(self, value):
        if value is None:
            return (0, "")
        if isinstance(value, bool):
            return (1, int(value))
        if isinstance(value, (int, float)):
            return (2, float(value))
        return (3, str(value).lower())


class QuickrulePlugin:
    CONFIG_FILENAME = "quickrule_config.json"

    def __init__(self, iface):
        self.iface = iface
        self.action = None

    def initGui(self):
        self.action = QAction("Quickrule", self.iface.mainWindow())
        self.action.triggered.connect(self.run_quickrule)
        self.iface.addCustomActionForLayerType(
            self.action, "", QgsMapLayerType.VectorLayer, True
        )

    def unload(self):
        if not self.action:
            return
        self.action.triggered.disconnect(self.run_quickrule)
        self.iface.removeCustomActionForLayerType(self.action)
        self.action = None

    def run_quickrule(self):
        layer = self._current_vector_layer()
        if layer is None:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Quickrule",
                "Bitte waehle einen Vektor-Layer in der Layerliste aus.",
            )
            return

        if layer.fields().count() == 0:
            QMessageBox.information(
                self.iface.mainWindow(),
                "Quickrule",
                "Der Layer hat keine Attribute/Spalten.",
            )
            return

        config = self._load_config()
        dialog = QuickruleDialog(self.iface.mainWindow(), layer, config)
        if dialog.exec_() != QDialog.Accepted:
            return

        selection = dialog.selection()
        field_name = selection["field_name"]
        selected_values = selection["selected_values"]
        mode = selection["mode"]

        if mode in ("rules", "both"):
            if not self._apply_rule_renderer(layer, field_name, selected_values):
                return

        if mode in ("filter", "both"):
            if not self._apply_layer_filter(layer, field_name, selected_values):
                return

        layer.triggerRepaint()
        QMessageBox.information(
            self.iface.mainWindow(),
            "Quickrule",
            "Einstellungen wurden erfolgreich angewendet.",
        )

    def _current_vector_layer(self):
        layer = self.iface.layerTreeView().currentLayer()
        if layer is None:
            layer = self.iface.activeLayer()
        if layer is None:
            return None
        if layer.type() != QgsMapLayerType.VectorLayer:
            return None
        return layer

    def _apply_rule_renderer(self, layer, field_name, values):
        base_symbol = QgsSymbol.defaultSymbol(layer.geometryType())
        if base_symbol is None:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Quickrule",
                "Der Layer-Typ wird fuer eine automatische Symbolisierung nicht unterstuetzt.",
            )
            return False

        renderer = QgsRuleBasedRenderer(base_symbol)
        root_rule = renderer.rootRule()
        while root_rule.children():
            root_rule.removeChildAt(0)

        total = len(values)
        quoted_field = QgsExpression.quotedColumnRef(field_name)
        for index, value in enumerate(values):
            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            symbol.setColor(self._color_for_index(index, total))
            rule = QgsRuleBasedRenderer.Rule(symbol)
            rule.setLabel("(NULL)" if value is None else str(value))
            rule.setFilterExpression(self._build_single_value_expression(quoted_field, value))
            root_rule.appendChild(rule)

        layer.setRenderer(renderer)
        if layer.geometryType() != QgsWkbTypes.NullGeometry:
            self.iface.layerTreeView().refreshLayerSymbology(layer.id())
        return True

    def _apply_layer_filter(self, layer, field_name, values):
        if layer.isEditable():
            if not layer.commitChanges():
                commit_errors = layer.commitErrors()
                details = "\n".join(commit_errors) if commit_errors else "Unbekannter Fehler."
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Quickrule",
                    "Layer konnte nicht gespeichert werden. Filter wurde nicht gesetzt.\n\n"
                    f"{details}",
                )
                return False

        quoted_field = QgsExpression.quotedColumnRef(field_name)
        subset_expression = self._build_multi_value_expression(quoted_field, values)
        if not layer.setSubsetString(subset_expression):
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Quickrule",
                "Layer-Filter konnte nicht gesetzt werden. Bitte Feldtyp/Provider pruefen.",
            )
            return False
        return True

    def _build_multi_value_expression(self, quoted_field, values):
        conditions = []
        has_null = False
        non_null_values = []
        for value in values:
            if value is None:
                has_null = True
            else:
                non_null_values.append(value)

        if non_null_values:
            if len(non_null_values) == 1:
                single_value = QgsExpression.quotedValue(non_null_values[0])
                conditions.append(f"{quoted_field} = {single_value}")
            else:
                in_values = ", ".join(
                    QgsExpression.quotedValue(value) for value in non_null_values
                )
                conditions.append(f"{quoted_field} IN ({in_values})")
        if has_null:
            conditions.append(f"{quoted_field} IS NULL")

        if not conditions:
            return "FALSE"
        if len(conditions) == 1:
            return conditions[0]
        return "(" + ") OR (".join(conditions) + ")"

    def _color_for_index(self, index, total):
        if total <= 1:
            return QColor.fromHsv(200, 160, 220)
        hue = int((index * 359) / total)
        return QColor.fromHsv(hue, 180, 225)

    def _build_single_value_expression(self, quoted_field, value):
        if value is None:
            return f"{quoted_field} IS NULL"
        return f"{quoted_field} = {QgsExpression.quotedValue(value)}"

    def _load_config(self):
        config_path = Path(__file__).resolve().parent / self.CONFIG_FILENAME
        if not config_path.exists():
            try:
                config_path.write_text(
                    json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=True) + "\n",
                    encoding="utf-8",
                )
            except Exception:
                pass
            return self._default_config_copy()

        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Quickrule",
                "quickrule_config.json ist ungueltig. Standard-Presets werden verwendet.",
            )
            return self._default_config_copy()

        if not isinstance(loaded, dict):
            return self._default_config_copy()
        return self._merged_config(loaded)

    def _default_config_copy(self):
        return json.loads(json.dumps(DEFAULT_CONFIG))

    def _merged_config(self, loaded):
        config = self._default_config_copy()
        presets = loaded.get("presets", {})
        if not isinstance(presets, dict):
            return config

        for preset_key, preset in presets.items():
            if not isinstance(preset, dict):
                continue
            label = str(preset.get("label", preset_key))
            aliases = preset.get("aliases", [])
            if not isinstance(aliases, list):
                continue
            cleaned_aliases = []
            for alias in aliases:
                alias_text = str(alias).strip()
                if alias_text:
                    cleaned_aliases.append(alias_text)
            config["presets"][str(preset_key)] = {
                "label": label,
                "aliases": cleaned_aliases,
            }
        return config
