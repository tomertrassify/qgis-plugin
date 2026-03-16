import json
import os
from dataclasses import dataclass

from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


@dataclass
class ToolEntry:
    key: str
    text: str
    toolbar_name: str
    action: object


class ToolbarManagerDock(QDockWidget):
    SETTINGS_KEY_CATEGORIES = "custom_tool_leiste/categories"
    SETTINGS_KEY_FAVORITES = "custom_tool_leiste/favorites"

    def __init__(self, iface, plugin_dir):
        super().__init__("Custom Tool-Leisten", iface.mainWindow())
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.settings = QSettings()

        self.categories = {}
        self.favorites = set()
        self.entries = []
        self._is_populating_table = False

        self._load_state()
        self._build_ui()
        self.visibilityChanged.connect(self._on_visibility_changed)
        self.refresh()

    def refresh(self):
        self.entries = self._discover_toolbar_actions()
        self._rebuild_filter_combo()
        self._rebuild_cards()
        self._populate_table()

    def _build_ui(self):
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        header_row = QHBoxLayout()
        title = QLabel("Custom QGIS Workspace")
        title.setObjectName("brandTitle")
        header_row.addWidget(title)
        header_row.addStretch(1)

        self.logo_label = QLabel()
        self.logo_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.logo_label.setMinimumWidth(130)
        self._apply_logo()
        header_row.addWidget(self.logo_label, 0, Qt.AlignRight)
        root.addLayout(header_row)

        controls = QHBoxLayout()
        self.refresh_button = QPushButton("Neu laden")
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_button)

        self.filter_combo = QComboBox()
        self.filter_combo.currentIndexChanged.connect(self._rebuild_cards)
        controls.addWidget(self.filter_combo, 1)

        self.overview_button = QToolButton()
        self.overview_button.setCheckable(True)
        self.overview_button.setChecked(False)
        self.overview_button.clicked.connect(self._toggle_overview)
        self._set_overview_button_text(False)
        controls.addWidget(self.overview_button)
        root.addLayout(controls)

        hint = QLabel(
            "Hinweis: Kategorien in der Gesamtuebersicht bearbeiten. "
            "Doppelklick auf eine Zeile startet das Werkzeug."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #35546f; font-size: 11px;")
        root.addWidget(hint)

        self.quick_scroll = QScrollArea()
        self.quick_scroll.setWidgetResizable(True)
        self.quick_scroll.setFrameShape(QFrame.NoFrame)

        self.quick_container = QWidget()
        self.quick_layout = QVBoxLayout(self.quick_container)
        self.quick_layout.setContentsMargins(0, 0, 0, 0)
        self.quick_layout.setSpacing(8)
        self.quick_layout.addStretch(1)
        self.quick_scroll.setWidget(self.quick_container)
        root.addWidget(self.quick_scroll, 1)

        self.overview_table = QTableWidget()
        self.overview_table.setColumnCount(4)
        self.overview_table.setHorizontalHeaderLabels(
            ["Fav", "Werkzeug", "Leiste", "Kategorie"]
        )
        header = self.overview_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        self.overview_table.itemChanged.connect(self._on_table_item_changed)
        self.overview_table.cellDoubleClicked.connect(self._on_table_cell_double_clicked)
        self.overview_table.setVisible(False)
        root.addWidget(self.overview_table, 1)

        self.setWidget(container)
        self.setMinimumWidth(390)
        self.setStyleSheet(
            """
            QDockWidget {
                background: #edf2f7;
            }
            QLabel#brandTitle {
                color: #12314a;
                font-size: 18px;
                font-weight: 700;
            }
            QFrame#sectionCard {
                background: #f8fbff;
                border: 1px solid #d3deea;
                border-radius: 8px;
            }
            QLabel[class="sectionTitle"] {
                color: #163952;
                font-weight: 600;
            }
            QPushButton[class="toolButton"] {
                text-align: left;
                padding: 5px 8px;
                border: 1px solid #ccd8e4;
                border-radius: 6px;
                background: #ffffff;
            }
            QPushButton[class="toolButton"]:hover {
                border-color: #4a7fa7;
                background: #f1f7fc;
            }
            QToolButton[class="starButton"] {
                font-size: 14px;
                min-width: 30px;
                border: 1px solid #ccd8e4;
                border-radius: 6px;
                background: #ffffff;
            }
            QToolButton[class="starButton"]:checked {
                color: #d49400;
                border-color: #d49400;
                background: #fff5d6;
            }
            """
        )

    def _apply_logo(self):
        candidates = ["logo.png", "logo.svg", "icon.svg"]
        for name in candidates:
            path = os.path.join(self.plugin_dir, name)
            if not os.path.exists(path):
                continue
            icon = QIcon(path)
            pix = icon.pixmap(130, 44)
            if not pix.isNull():
                self.logo_label.setPixmap(pix)
                return
        self.logo_label.setText("DEIN LOGO")

    def _discover_toolbar_actions(self):
        results = []
        seen = set()
        for toolbar in self.iface.mainWindow().findChildren(QToolBar):
            toolbar_name = (
                (toolbar.windowTitle() or "").strip()
                or (toolbar.objectName() or "").strip()
                or "Unbenannte Leiste"
            )
            for action in toolbar.actions():
                if action is None or action.isSeparator():
                    continue

                action_text = (action.text() or "").replace("&", "").strip()
                if not action_text:
                    action_text = (action.objectName() or "").strip()
                if not action_text:
                    continue

                key = self._build_action_key(toolbar, action, action_text)
                if key in seen:
                    continue
                seen.add(key)
                results.append(
                    ToolEntry(
                        key=key,
                        text=action_text,
                        toolbar_name=toolbar_name,
                        action=action,
                    )
                )

        results.sort(key=lambda item: (item.toolbar_name.lower(), item.text.lower()))
        return results

    def _build_action_key(self, toolbar, action, fallback_text):
        toolbar_key = (
            (toolbar.objectName() or "").strip()
            or (toolbar.windowTitle() or "").strip()
            or "toolbar"
        )
        action_key = (
            (action.objectName() or "").strip() or (action.text() or "").strip() or fallback_text
        )
        return "{}::{}::{}".format(toolbar_key, action_key, fallback_text)

    def _set_overview_button_text(self, visible):
        if visible:
            self.overview_button.setText("Gesamtuebersicht verbergen")
        else:
            self.overview_button.setText("Gesamtuebersicht anzeigen")

    def _toggle_overview(self):
        show = self.overview_button.isChecked()
        self.overview_table.setVisible(show)
        self._set_overview_button_text(show)

    def _on_visibility_changed(self, visible):
        if visible:
            self.refresh()

    def _rebuild_filter_combo(self):
        previous = self.filter_combo.currentData()
        options = [("__all__", "Alle Kategorien"), ("__favorites__", "Nur Favoriten")]

        category_names = {
            self.categories.get(entry.key, "Ohne Kategorie").strip() or "Ohne Kategorie"
            for entry in self.entries
        }
        for category in sorted(category_names, key=str.lower):
            options.append((category, category))

        self.filter_combo.blockSignals(True)
        self.filter_combo.clear()
        for value, label in options:
            self.filter_combo.addItem(label, value)

        index = self.filter_combo.findData(previous)
        if index < 0:
            index = 0
        self.filter_combo.setCurrentIndex(index)
        self.filter_combo.blockSignals(False)

    def _rebuild_cards(self):
        self._clear_layout(self.quick_layout)

        filtered = self._filtered_entries()
        if not filtered:
            empty = QLabel("Keine Werkzeuge fuer die aktuelle Ansicht.")
            self.quick_layout.addWidget(empty)
            self.quick_layout.addStretch(1)
            return

        mode = self.filter_combo.currentData()
        if mode == "__all__":
            favorites = [entry for entry in filtered if entry.key in self.favorites]
            if favorites:
                self._add_section("Favoriten", favorites)

        grouped = {}
        for entry in filtered:
            category = self.categories.get(entry.key, "Ohne Kategorie").strip() or "Ohne Kategorie"
            grouped.setdefault(category, []).append(entry)

        for category in sorted(grouped, key=str.lower):
            self._add_section(category, grouped[category])

        self.quick_layout.addStretch(1)

    def _filtered_entries(self):
        mode = self.filter_combo.currentData() or "__all__"
        if mode == "__favorites__":
            return [entry for entry in self.entries if entry.key in self.favorites]
        if mode == "__all__":
            return list(self.entries)
        return [
            entry
            for entry in self.entries
            if (self.categories.get(entry.key, "Ohne Kategorie").strip() or "Ohne Kategorie") == mode
        ]

    def _add_section(self, title, entries):
        card = QFrame()
        card.setObjectName("sectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        section_title = QLabel(title)
        section_title.setProperty("class", "sectionTitle")
        layout.addWidget(section_title)

        for entry in entries:
            row = QHBoxLayout()
            row.setSpacing(6)

            button = QPushButton(entry.text)
            button.setProperty("class", "toolButton")
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(
                lambda _checked=False, key=entry.key: self._trigger_action(key)
            )
            row.addWidget(button, 1)

            star_button = QToolButton()
            star_button.setProperty("class", "starButton")
            star_button.setText("\u2605")
            star_button.setCheckable(True)
            star_button.setChecked(entry.key in self.favorites)
            star_button.setToolTip("Als Favorit markieren")
            star_button.toggled.connect(
                lambda checked, key=entry.key: self._set_favorite(key, checked)
            )
            row.addWidget(star_button)
            layout.addLayout(row)

        self.quick_layout.addWidget(card)

    def _trigger_action(self, key):
        for entry in self.entries:
            if entry.key == key:
                entry.action.trigger()
                return

    def _set_favorite(self, key, is_favorite):
        if is_favorite:
            self.favorites.add(key)
        else:
            self.favorites.discard(key)

        self._save_state()
        self._rebuild_cards()
        self._populate_table()

    def _populate_table(self):
        self._is_populating_table = True
        self.overview_table.setRowCount(len(self.entries))

        for row, entry in enumerate(self.entries):
            favorite_item = QTableWidgetItem("\u2605")
            favorite_item.setData(Qt.UserRole, entry.key)
            favorite_item.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
            )
            favorite_item.setCheckState(
                Qt.Checked if entry.key in self.favorites else Qt.Unchecked
            )
            self.overview_table.setItem(row, 0, favorite_item)

            name_item = QTableWidgetItem(entry.text)
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.overview_table.setItem(row, 1, name_item)

            toolbar_item = QTableWidgetItem(entry.toolbar_name)
            toolbar_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.overview_table.setItem(row, 2, toolbar_item)

            category_value = self.categories.get(entry.key, "")
            category_item = QTableWidgetItem(category_value)
            category_item.setData(Qt.UserRole, entry.key)
            category_item.setToolTip("Kategorie direkt bearbeiten")
            category_item.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable
            )
            self.overview_table.setItem(row, 3, category_item)

        self.overview_table.resizeRowsToContents()
        self._is_populating_table = False

    def _on_table_item_changed(self, item):
        if self._is_populating_table:
            return

        key = item.data(Qt.UserRole)
        if not key:
            return

        if item.column() == 0:
            is_favorite = item.checkState() == Qt.Checked
            if is_favorite:
                self.favorites.add(key)
            else:
                self.favorites.discard(key)
            self._save_state()
            self._rebuild_cards()
            return

        if item.column() == 3:
            category = (item.text() or "").strip()
            if category:
                self.categories[key] = category
            else:
                self.categories.pop(key, None)
            self._save_state()
            self._rebuild_filter_combo()
            self._rebuild_cards()

    def _on_table_cell_double_clicked(self, row, _column):
        key_item = self.overview_table.item(row, 0)
        if key_item is None:
            return
        key = key_item.data(Qt.UserRole)
        if key:
            self._trigger_action(key)

    def _load_state(self):
        categories_raw = self.settings.value(self.SETTINGS_KEY_CATEGORIES, "{}")
        favorites_raw = self.settings.value(self.SETTINGS_KEY_FAVORITES, "[]")

        self.categories = self._deserialize_categories(categories_raw)
        self.favorites = self._deserialize_favorites(favorites_raw)

    def _save_state(self):
        self.settings.setValue(
            self.SETTINGS_KEY_CATEGORIES, json.dumps(self.categories, ensure_ascii=True)
        )
        self.settings.setValue(
            self.SETTINGS_KEY_FAVORITES,
            json.dumps(sorted(self.favorites), ensure_ascii=True),
        )

    def _deserialize_categories(self, raw):
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items() if str(v).strip()}
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return {str(k): str(v) for k, v in parsed.items() if str(v).strip()}
            except ValueError:
                pass
        return {}

    def _deserialize_favorites(self, raw):
        if isinstance(raw, list):
            return {str(item) for item in raw}
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return {str(item) for item in parsed}
            except ValueError:
                pass
        return set()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            child_layout = item.layout()
            child_widget = item.widget()
            if child_layout is not None:
                self._clear_layout(child_layout)
            if child_widget is not None:
                child_widget.deleteLater()
