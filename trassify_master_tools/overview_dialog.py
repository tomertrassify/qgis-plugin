from __future__ import annotations

from html import escape

from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QFont, QIcon
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class MasterOverviewDialog(QDialog):
    FILTERS = (
        ("all", "Alle", QStyle.SP_FileDialogDetailedView),
        ("interactive", "Normale Tools", QStyle.SP_FileDialogListView),
        ("background", "Hintergrundtools", QStyle.SP_ComputerIcon),
        ("favorites", "Favoriten", QStyle.SP_DirHomeIcon),
    )
    STATUS_FILTERS = (
        ("all", "Alle Stati"),
        ("ready", "Bereit"),
        ("loaded", "Geladen"),
        ("conflict", "Blockiert"),
        ("error", "Fehler"),
    )

    def __init__(self, plugin_controller, parent=None):
        super().__init__(parent)
        self.plugin_controller = plugin_controller
        self._rows_by_key = {}
        self._all_rows = []

        self.setWindowTitle("Erweiterungen | Installiert")
        self.setWindowIcon(QIcon(str(plugin_controller.plugin_dir / "icon.svg")))
        self.resize(1240, 760)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(8)
        layout.addLayout(controls_layout)

        self.search_field = QLineEdit(self)
        self.search_field.setPlaceholderText("Suchen...")
        self.search_field.setClearButtonEnabled(True)
        self.search_field.textChanged.connect(self._apply_filters)
        controls_layout.addWidget(self.search_field, 1)

        status_label = QLabel("Status", self)
        controls_layout.addWidget(status_label)

        self.status_filter = QComboBox(self)
        self.status_filter.setMinimumWidth(170)
        for filter_key, label in self.STATUS_FILTERS:
            self.status_filter.addItem(label, filter_key)
        self.status_filter.currentIndexChanged.connect(self._apply_filters)
        controls_layout.addWidget(self.status_filter)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(8)
        layout.addLayout(content_layout, 1)

        self.filter_list = QListWidget(self)
        self.filter_list.setFixedWidth(190)
        self.filter_list.currentItemChanged.connect(self._apply_filters)
        content_layout.addWidget(self.filter_list)

        self.content_splitter = QSplitter(Qt.Horizontal, self)
        self.content_splitter.setChildrenCollapsible(False)
        content_layout.addWidget(self.content_splitter, 1)

        self.module_list = QTreeWidget(self)
        self.module_list.setHeaderHidden(True)
        self.module_list.setRootIsDecorated(False)
        self.module_list.setIndentation(0)
        self.module_list.setAlternatingRowColors(True)
        self.module_list.setUniformRowHeights(True)
        self.module_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.module_list.setIconSize(QSize(20, 20))
        self.module_list.itemSelectionChanged.connect(self._sync_details)
        self.module_list.itemDoubleClicked.connect(self._handle_item_double_click)
        self.content_splitter.addWidget(self.module_list)

        detail_panel = QWidget(self)
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(14, 14, 14, 14)
        detail_layout.setSpacing(12)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)
        detail_layout.addLayout(header_layout)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(6)
        header_layout.addLayout(title_layout, 1)

        self.title_label = QLabel(detail_panel)
        title_font = QFont(self.font())
        title_font.setPointSize(title_font.pointSize() + 12)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setWordWrap(True)
        title_layout.addWidget(self.title_label)

        self.description_label = QLabel(detail_panel)
        description_font = QFont(self.font())
        description_font.setPointSize(description_font.pointSize() + 3)
        description_font.setBold(True)
        self.description_label.setFont(description_font)
        self.description_label.setWordWrap(True)
        title_layout.addWidget(self.description_label)

        self.status_label = QLabel(detail_panel)
        self.status_label.setWordWrap(True)
        title_layout.addWidget(self.status_label)

        self.icon_label = QLabel(detail_panel)
        self.icon_label.setFixedSize(88, 88)
        self.icon_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        header_layout.addWidget(self.icon_label, 0, Qt.AlignTop)

        self.about_label = QLabel(detail_panel)
        self.about_label.setWordWrap(True)
        self.about_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        detail_layout.addWidget(self.about_label)

        separator = QFrame(detail_panel)
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        detail_layout.addWidget(separator)

        self.metadata_form = QFormLayout()
        self.metadata_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.metadata_form.setFormAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.metadata_form.setHorizontalSpacing(16)
        self.metadata_form.setVerticalSpacing(10)
        detail_layout.addLayout(self.metadata_form)

        self.category_value = self._create_value_label(detail_panel)
        self.type_value = self._create_value_label(detail_panel)
        self.favorite_value = self._create_value_label(detail_panel)
        self.package_value = self._create_value_label(detail_panel)
        self.tags_value = self._create_value_label(detail_panel)
        self.author_value = self._create_value_label(detail_panel)
        self.version_value = self._create_value_label(detail_panel)
        self.links_value = self._create_value_label(detail_panel, rich_text=True)

        self.metadata_form.addRow("Kategorie", self.category_value)
        self.metadata_form.addRow("Typ", self.type_value)
        self.metadata_form.addRow("Favorit", self.favorite_value)
        self.metadata_form.addRow("Paket", self.package_value)
        self.metadata_form.addRow("Tags", self.tags_value)
        self.metadata_form.addRow("Autor", self.author_value)
        self.metadata_form.addRow("Version", self.version_value)
        self.metadata_form.addRow("Weitere Informationen", self.links_value)

        detail_layout.addStretch(1)
        self.content_splitter.addWidget(detail_panel)
        self.content_splitter.setStretchFactor(0, 4)
        self.content_splitter.setStretchFactor(1, 7)

        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(8)
        layout.addLayout(actions_layout)

        self.refresh_button = QPushButton("Aktualisieren", self)
        self.refresh_button.clicked.connect(self.refresh)
        actions_layout.addWidget(self.refresh_button)

        self.settings_button = QPushButton("Einstellungen", self)
        self.settings_button.clicked.connect(self.plugin_controller.show_settings)
        actions_layout.addWidget(self.settings_button)

        actions_layout.addStretch(1)

        self.favorite_button = QPushButton("Zu Favoriten", self)
        self.favorite_button.clicked.connect(self._toggle_selected_favorite)
        actions_layout.addWidget(self.favorite_button)

        self.load_button = QPushButton("Ausgewaehltes Modul laden", self)
        self.load_button.clicked.connect(self._load_selected_module)
        actions_layout.addWidget(self.load_button)

        button_box = QDialogButtonBox(QDialogButtonBox.Close, self)
        button_box.rejected.connect(self.reject)
        actions_layout.addWidget(button_box)

        self.refresh()

    def refresh(self):
        current_item = self.module_list.currentItem()
        current_key = current_item.data(0, Qt.UserRole) if current_item is not None else None
        self._all_rows = sorted(
            self.plugin_controller.get_module_rows(),
            key=lambda row: row["label"].lower(),
        )
        self._rows_by_key = {
            row["key"]: row for row in self._all_rows
        }

        self._populate_filters()
        self._apply_filters(preferred_key=current_key)
        self.setWindowTitle(
            f"Erweiterungen | Installiert ({len(self._all_rows)})"
        )

    def _populate_filters(self):
        current_filter = self._active_filter_key()
        counts = {
            "all": len(self._all_rows),
            "interactive": sum(
                1 for row in self._all_rows if row["tool_type"] == "interactive"
            ),
            "background": sum(
                1 for row in self._all_rows if row["tool_type"] == "background"
            ),
            "favorites": sum(
                1 for row in self._all_rows if row["is_favorite"]
            ),
        }

        self.filter_list.blockSignals(True)
        self.filter_list.clear()
        style = self.style()
        fallback_item = None

        for filter_key, label, icon_role in self.FILTERS:
            item = QListWidgetItem(style.standardIcon(icon_role), f"{label} ({counts[filter_key]})")
            item.setData(Qt.UserRole, filter_key)
            self.filter_list.addItem(item)
            if filter_key == current_filter:
                fallback_item = item
            if filter_key == "all" and fallback_item is None:
                fallback_item = item

        if fallback_item is not None:
            self.filter_list.setCurrentItem(fallback_item)
        self.filter_list.blockSignals(False)

    def _active_filter_key(self):
        current_item = self.filter_list.currentItem()
        if current_item is None:
            return "all"
        return current_item.data(Qt.UserRole) or "all"

    def _active_status_filter_key(self):
        return self.status_filter.currentData() or "all"

    def _apply_filters(self, *_args, preferred_key=None):
        filter_key = self._active_filter_key()
        status_filter_key = self._active_status_filter_key()
        search_term = self.search_field.text().strip().lower()

        self.module_list.blockSignals(True)
        self.module_list.clear()

        visible_rows = []
        for row in self._all_rows:
            if not self._matches_filter(row, filter_key):
                continue
            if not self._matches_status_filter(row, status_filter_key):
                continue
            if search_term and not self._matches_search(row, search_term):
                continue
            visible_rows.append(row)

        for row in visible_rows:
            display_label = row["label"]
            if row["is_favorite"]:
                display_label = f"[Favorit] {display_label}"

            item = QTreeWidgetItem([display_label])
            item.setData(0, Qt.UserRole, row["key"])
            item.setData(0, Qt.UserRole + 1, row["status_code"])
            item.setToolTip(0, f"{row['status_text']}: {row['detail']}")
            item.setIcon(0, QIcon(row["icon_path"]))

            font = item.font(0)
            if row["status_code"] == "loaded":
                font.setBold(True)
                item.setFont(0, font)

            self.module_list.addTopLevelItem(item)

        self.module_list.blockSignals(False)

        selected_item = None
        if preferred_key:
            selected_item = self._find_item_by_key(preferred_key)
        if selected_item is None and self.module_list.topLevelItemCount() > 0:
            selected_item = self.module_list.topLevelItem(0)

        if selected_item is not None:
            self.module_list.setCurrentItem(selected_item)
        else:
            self._render_empty_state(search_term)

        self._sync_details()

    def _matches_filter(self, row, filter_key):
        if filter_key == "all":
            return True
        if filter_key in {"interactive", "background"}:
            return row["tool_type"] == filter_key
        if filter_key == "favorites":
            return row["is_favorite"]
        return False

    def _matches_status_filter(self, row, filter_key):
        if filter_key == "all":
            return True
        return row["status_code"] == filter_key

    def _matches_search(self, row, search_term):
        search_haystack = " ".join(
            [
                row["label"],
                row["package"],
                row["description"],
                row["about"],
                row["author"],
                row["category"],
                row["tool_type_label"],
                row["detail"],
                "favorit" if row["is_favorite"] else "",
                " ".join(row["tags"]),
            ]
        ).lower()
        return search_term in search_haystack

    def _find_item_by_key(self, wanted_key):
        for index in range(self.module_list.topLevelItemCount()):
            item = self.module_list.topLevelItem(index)
            if item.data(0, Qt.UserRole) == wanted_key:
                return item
        return None

    def _sync_details(self):
        item = self.module_list.currentItem()
        if item is None:
            self.favorite_button.setEnabled(False)
            self.favorite_button.setText("Zu Favoriten")
            self.load_button.setEnabled(False)
            return

        row = self._rows_by_key.get(item.data(0, Qt.UserRole))
        if row is None:
            self.favorite_button.setEnabled(False)
            self.favorite_button.setText("Zu Favoriten")
            self.load_button.setEnabled(False)
            return

        self.favorite_button.setEnabled(True)
        if row["is_favorite"]:
            self.favorite_button.setText("Aus Favoriten entfernen")
        else:
            self.favorite_button.setText("Zu Favoriten")
        self.load_button.setEnabled(row["status_code"] == "ready")
        if row["tool_type"] == "background":
            self.load_button.setText("Hintergrundtool laden")
        else:
            self.load_button.setText("Ausgewaehltes Modul laden")
        self._render_module_details(row)

    def _render_empty_state(self, search_term):
        self.title_label.setText("Keine Module gefunden")
        if search_term:
            self.description_label.setText(
                f"Keine Treffer fuer '{escape(search_term)}'."
            )
        else:
            self.description_label.setText("Der aktuelle Filter enthaelt keine Module.")
        self.status_label.setText("Passe Suche oder Filter an.")
        self.about_label.setText(
            "Die Trassify-Masteransicht orientiert sich an der nativen QGIS-Erweiterungsliste."
        )
        self.category_value.setText("-")
        self.type_value.setText("-")
        self.favorite_value.setText("-")
        self.package_value.setText("-")
        self.tags_value.setText("-")
        self.author_value.setText("-")
        self.version_value.setText("-")
        self.links_value.setText("-")
        self.icon_label.setPixmap(QIcon(
            str(self.plugin_controller.plugin_dir / "icon.svg")
        ).pixmap(88, 88))

    def _render_module_details(self, row):
        self.title_label.setText(row["label"])
        self.description_label.setText(
            row["description"] or "Kein Beschreibungstext verfuegbar."
        )
        self.status_label.setText(
            f"<b>Status:</b> {escape(row['status_text'])} | {escape(row['detail'])}"
        )
        self.status_label.setTextFormat(Qt.RichText)

        about_text = row["about"]
        favorite_hint = ""
        if row["is_favorite"] and row["tool_type"] == "background":
            favorite_hint = (
                " Dieses Hintergrundtool ist als Favorit gespeichert und erscheint in der Favoritenliste, "
                "aber nicht als extra Toolbar-Button."
            )
        elif row["is_favorite"]:
            favorite_hint = (
                " Dieses Tool ist als Favorit gespeichert und erscheint zusaetzlich als Icon in der Master-Toolbar."
            )

        if about_text and about_text != row["description"]:
            self.about_label.setText(about_text + favorite_hint)
        elif row["tool_type"] == "background":
            self.about_label.setText(
                "Dieses Modul ist als Hintergrundtool vorgesehen und wird automatisch geladen, "
                "damit Kontextmenues oder stille Hilfsfunktionen ohne zusaetzlichen Button verfuegbar sind."
                + favorite_hint
            )
        else:
            self.about_label.setText(
                "Dieses Modul ist im Master-Plugin enthalten und kann bei Bedarf geladen werden."
                + favorite_hint
            )

        self.category_value.setText(row["category"] or "-")
        self.type_value.setText(row["tool_type_label"] or "-")
        self.favorite_value.setText("Ja" if row["is_favorite"] else "Nein")
        self.package_value.setText(row["package"] or "-")
        self.tags_value.setText(", ".join(row["tags"]) or "-")
        self.author_value.setText(row["author"] or "-")
        self.version_value.setText(row["version"] or "-")
        self.links_value.setText(self._build_links_html(row))

        icon = QIcon(row["icon_path"])
        self.icon_label.setPixmap(icon.pixmap(88, 88))

    def _build_links_html(self, row):
        links = []
        if row["homepage"]:
            links.append(
                f"<a href=\"{escape(row['homepage'])}\">Homepage</a>"
            )
        if row["tracker"]:
            links.append(
                f"<a href=\"{escape(row['tracker'])}\">Fehlerverfolgung</a>"
            )
        if row["repository"]:
            links.append(
                f"<a href=\"{escape(row['repository'])}\">Coderepository</a>"
            )
        return "   ".join(links) or "-"

    def _create_value_label(self, parent, rich_text=False):
        label = QLabel(parent)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if rich_text:
            label.setTextFormat(Qt.RichText)
            label.setOpenExternalLinks(True)
            label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        return label

    def _load_selected_module(self):
        item = self.module_list.currentItem()
        if item is None:
            return

        key = item.data(0, Qt.UserRole)
        if key is None:
            return

        self.plugin_controller.load_module_by_key(key)
        self.refresh()

    def _handle_item_double_click(self, item, _column):
        if item.data(0, Qt.UserRole + 1) != "ready":
            return
        self._load_selected_module()

    def _toggle_selected_favorite(self):
        item = self.module_list.currentItem()
        if item is None:
            return

        key = item.data(0, Qt.UserRole)
        if key is None:
            return

        self.plugin_controller.toggle_favorite_by_key(key)
