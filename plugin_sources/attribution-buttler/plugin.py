from __future__ import annotations

import csv
import json
import os
import re
import urllib.parse
from datetime import datetime

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QSize, Qt, QSettings
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QAction,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QHeaderView,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QStackedWidget,
    QSplitter,
    QStyle,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    Qgis,
    QgsEditFormConfig,
    QgsFeature,
    QgsMapLayerType,
    QgsVectorDataProvider,
    QgsVectorLayer,
)


PLUGIN_MENU = "&AttributionButler"
PROPERTY_PREFIX = "nextcloud_form/"
INIT_FUNCTION_NAME = "form_open"
BOOTSTRAP_CODE = (
    "try:\n"
    "    from attribution_buttler.form_handler import form_open\n"
    "except ModuleNotFoundError:\n"
    "    from nextcloud_form_plugin.form_handler import form_open\n"
)
BOOTSTRAP_CODE_MARKERS = (
    "attribution_buttler.form_handler",
    "nextcloud_form_plugin.form_handler",
)
LOCAL_ROOT_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*lokale\s*sync-roots\s*\}\}", flags=re.IGNORECASE)

DEFAULT_CONFIG = {
    "nextcloud_base_url": "https://nextcloud.trassify.cloud",
    "nextcloud_user": "",
    "nextcloud_app_password": "",
    "local_nextcloud_roots": [],
    "nextcloud_folder_marker": "Nextcloud",
    "path_field_name": "quelle_pfad",
    "file_link_field_name": "quelle_1",
    "folder_link_field_name": "quelle_2",
    "name_field_name": "",
    "stand_field_name": "Stand",
    # Betreiber-Feldzuordnung (Layer-Felder)
    "operator_name_field_name": "Betreiber",
    "operator_contact_field_name": "betr_anspr",
    "operator_phone_field_name": "betr_tel",
    "operator_email_field_name": "betr_email",
    "operator_fault_field_name": "stoer-nr",
    "operator_validity_field_name": "gueltigk",
    "operator_stand_field_name": "Stand",
    "overwrite_existing_values": True,
    "fill_on_form_open": False,
    "operators": [],
    "external_data_sources": [
        {
            "enabled": True,
            "name": "Betreiberliste-beta",
            "source_type": "file",
            "provider": "ogr",
            "source": "{{Lokale Sync-Roots}}/Trassify Allgemein/IT/Betreiberliste-beta.xlsx",
            "table": "",
            "operator_name_field": "Betreiber",
            "contact_name_field": "betr_anspr",
            "phone_field": "betr_tel",
            "email_field": "betr_email",
            "fault_number_field": "stoer-nr",
            "folder_path_field": "",
        },
        {
            "enabled": True,
            "name": "Geoserver_DB",
            "source_type": "qgis_uri",
            "provider": "ogr",
            "source": (
                "PG:host='168.119.214.156' port='9132' dbname='postgres' sslmode='prefer' "
                "user='geoserver' password='Atnzhol4zlCqKTUc' "
                "schemas='Plugin_Liste' active_schema='Plugin_Liste'"
            ),
            "table": "",
            "operator_name_field": "Betreiber",
            "contact_name_field": "betr_anspr",
            "phone_field": "betr_tel",
            "email_field": "betr_email",
            "fault_number_field": "stoer-nr",
            "folder_path_field": "",
        }
    ],
}

MASTER_SETTINGS_PREFIX = "TrassifyMasterTools/shared_settings"
USER_CONFIG_KEYS = (
    "nextcloud_base_url",
    "nextcloud_user",
    "nextcloud_app_password",
    "local_nextcloud_roots",
    "nextcloud_folder_marker",
)


def _layer_field_names(layer) -> list[str]:
    return [field.name() for field in layer.fields()]


def _first_field_match(layer_fields: list[str], candidates: list[str]) -> str:
    lowered = {name.lower(): name for name in layer_fields}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    for candidate in candidates:
        token = candidate.lower()
        for field_name in layer_fields:
            if token in field_name.lower():
                return field_name
    return ""


def _expand_local_root_placeholder(value: str, roots: list[str]) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not LOCAL_ROOT_PLACEHOLDER_PATTERN.search(text):
        return text

    root = ""
    for candidate in roots or []:
        token = str(candidate or "").strip()
        if token:
            root = token.rstrip("/\\")
            break
    # Use callable replacement so Windows backslashes are treated literally.
    return LOCAL_ROOT_PLACEHOLDER_PATTERN.sub(lambda _match: root, text)


class LayerConfigDialog(QDialog):
    def __init__(self, layer, parent=None):
        super().__init__(parent)
        self.layer = layer
        self.layer_fields = _layer_field_names(layer)
        self._auto_pg_table_cache = {}
        self._config_page_index = -1
        self._operators_page_index = -1
        self._data_page_index = -1
        self._last_external_load_debug = []

        self.setWindowTitle("AttributionButler konfigurieren")
        self.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), "icon.svg")))
        self.resize(980, 700)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        content_splitter = QSplitter(Qt.Horizontal, self)
        content_splitter.setChildrenCollapsible(False)
        root_layout.addWidget(content_splitter, 1)

        self.nav_list = QListWidget(self)
        self.nav_list.setFixedWidth(190)
        self.nav_list.setIconSize(QSize(18, 18))
        self.nav_list.setSelectionMode(QAbstractItemView.SingleSelection)
        content_splitter.addWidget(self.nav_list)

        self.page_stack = QStackedWidget(self)
        content_splitter.addWidget(self.page_stack)
        content_splitter.setStretchFactor(0, 0)
        content_splitter.setStretchFactor(1, 1)
        self.nav_list.currentItemChanged.connect(self._on_nav_item_changed)

        config_tab = QWidget()
        config_layout = QVBoxLayout(config_tab)
        self._config_page_index = self.page_stack.addWidget(config_tab)
        config_icon = self.style().standardIcon(QStyle.SP_FileDialogDetailedView)

        self._global_nextcloud_config = {
            "nextcloud_base_url": str(DEFAULT_CONFIG.get("nextcloud_base_url", "") or "").strip(),
            "nextcloud_user": "",
            "nextcloud_app_password": "",
            "local_nextcloud_roots": [],
            "nextcloud_folder_marker": str(
                DEFAULT_CONFIG.get("nextcloud_folder_marker", "Nextcloud") or "Nextcloud"
            ).strip(),
        }

        master_hint = QLabel(
            "Hinweis: Nextcloud-Verbindung wird zentral aus "
            "Trassify Master Tools > Einstellungen > Nextcloud uebernommen."
        )
        master_hint.setWordWrap(True)
        config_layout.addWidget(master_hint)

        fields_group = QGroupBox("1) Feld-Mapping")
        fields_form = QFormLayout(fields_group)

        self.path_field = self._make_field_combo()
        self.file_field = self._make_field_combo()
        self.folder_field = self._make_field_combo()
        self.name_field = self._make_field_combo()
        self.stand_field = self._make_field_combo()
        self.operator_name_field = self._make_field_combo()
        self.operator_contact_field = self._make_field_combo()
        self.operator_phone_field = self._make_field_combo()
        self.operator_email_field = self._make_field_combo()
        self.operator_fault_field = self._make_field_combo()
        self.operator_validity_field = self._make_field_combo()
        self.operator_stand_field = self._make_field_combo()

        fields_form.addRow("Pfadfeld (Pflicht)", self.path_field)
        fields_form.addRow("Datei-Link Feld", self.file_field)
        fields_form.addRow("Ordner-Link Feld", self.folder_field)
        fields_form.addRow("Dateiname Feld", self.name_field)
        fields_form.addRow("Stand-Datum Feld", self.stand_field)

        config_layout.addWidget(fields_group)

        operator_fields_group = QGroupBox("2) Betreiber-Feld-Mapping")
        operator_fields_form = QFormLayout(operator_fields_group)
        operator_fields_form.addRow("Betreibername Feld", self.operator_name_field)
        operator_fields_form.addRow("Ansprechpartner Feld", self.operator_contact_field)
        operator_fields_form.addRow("Telefonnummer Feld", self.operator_phone_field)
        operator_fields_form.addRow("E-Mail Feld", self.operator_email_field)
        operator_fields_form.addRow("Stoernummer Feld", self.operator_fault_field)
        operator_fields_form.addRow("Gültigkeit Feld", self.operator_validity_field)
        operator_fields_form.addRow("Stand Feld", self.operator_stand_field)
        config_layout.addWidget(operator_fields_group)

        suggestion_row = QHBoxLayout()
        suggest_button = QPushButton("Felder automatisch vorschlagen")
        suggest_button.clicked.connect(self._suggest_fields)
        clear_optional_button = QPushButton("Optionale Felder leeren")
        clear_optional_button.clicked.connect(self._clear_optional_fields)
        suggestion_row.addWidget(suggest_button)
        suggestion_row.addWidget(clear_optional_button)
        suggestion_row.addStretch(1)
        config_layout.addLayout(suggestion_row)

        behavior_group = QGroupBox("3) Verhalten")
        behavior_form = QFormLayout(behavior_group)

        self.overwrite = QCheckBox("Vorhandene Werte ueberschreiben")
        self.fill_on_open = QCheckBox("Bereits vorhandenen Pfad beim Oeffnen verarbeiten")
        behavior_form.addRow("", self.overwrite)
        behavior_form.addRow("", self.fill_on_open)

        config_layout.addWidget(behavior_group)

        footer = QLabel(
            "Hinweis: Leere Ziel-Felder werden ignoriert. So kannst du nur die Felder befuellen, die du brauchst."
        )
        footer.setWordWrap(True)
        config_layout.addWidget(footer)
        config_layout.addStretch(1)

        operators_tab = QWidget()
        operators_layout = QVBoxLayout(operators_tab)
        self._operators_page_index = self.page_stack.addWidget(operators_tab)
        operators_icon = self.style().standardIcon(QStyle.SP_DirIcon)

        source_row = QHBoxLayout()
        source_row.setContentsMargins(0, 0, 0, 0)
        self.operator_source_combo = QComboBox()
        self.operator_source_combo.currentIndexChanged.connect(self._on_operator_source_changed)
        source_row.addWidget(self.operator_source_combo, 1)
        operators_layout.addLayout(source_row)

        self.operator_view_stack = QStackedWidget()
        operators_layout.addWidget(self.operator_view_stack, 1)

        local_operators_page = QWidget()
        local_operators_layout = QVBoxLayout(local_operators_page)
        local_operators_layout.setContentsMargins(0, 0, 0, 0)

        self.operator_search_input = QLineEdit()
        self.operator_search_input.setPlaceholderText("Projektliste suchen...")
        self.operator_search_input.textChanged.connect(
            lambda text: self._apply_table_text_filter(self.operator_table, text)
        )
        local_operators_layout.addWidget(self.operator_search_input)

        self.operator_table = QTableWidget(0, 9)
        self.operator_table.setHorizontalHeaderLabels(
            [
                "Datenquelle",
                "Betreibername",
                "Gültigkeit",
                "Stand",
                "Ansprechpartner",
                "Telefonnummer",
                "E-Mail",
                "Störnummer",
                "Pfad",
            ]
        )
        self._configure_standard_table(
            self.operator_table,
            selection_mode=QAbstractItemView.ExtendedSelection,
        )
        header = self.operator_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(90)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        header.setSectionResizeMode(4, QHeaderView.Interactive)
        header.setSectionResizeMode(5, QHeaderView.Interactive)
        header.setSectionResizeMode(6, QHeaderView.Interactive)
        header.setSectionResizeMode(7, QHeaderView.Interactive)
        header.setSectionResizeMode(8, QHeaderView.Interactive)
        header.resizeSection(0, 190)
        header.resizeSection(1, 220)
        header.resizeSection(2, 150)
        header.resizeSection(3, 130)
        header.resizeSection(4, 170)
        header.resizeSection(5, 170)
        header.resizeSection(6, 220)
        header.resizeSection(7, 170)
        header.resizeSection(8, 360)
        header.setTextElideMode(Qt.ElideNone)
        # Kompakte Projektansicht: Betreibername + Stand + Quelle + Pfad.
        self.operator_table.setColumnHidden(2, True)
        self.operator_table.setColumnHidden(4, True)
        self.operator_table.setColumnHidden(5, True)
        self.operator_table.setColumnHidden(6, True)
        self.operator_table.setColumnHidden(7, True)
        # Betreibername links, danach Stand und die restlichen Projektspalten.
        self._set_operator_table_visual_order()
        self.operator_table.itemChanged.connect(self._on_operator_table_item_changed)
        local_operators_layout.addWidget(self.operator_table, 1)

        operator_buttons = QHBoxLayout()
        add_operator_button = QPushButton("Zeile hinzufuegen")
        add_operator_button.clicked.connect(self._add_operator_row)
        import_operator_button = QPushButton("Importieren...")
        import_operator_button.clicked.connect(self._import_operators)
        export_operator_button = QPushButton("Exportieren...")
        export_operator_button.clicked.connect(self._export_operators)
        choose_folder_button = QPushButton("Ordner fuer Auswahl...")
        choose_folder_button.clicked.connect(self._choose_folder_for_selected_row)
        bulk_assign_button = QPushButton("Ueberordner zuordnen...")
        bulk_assign_button.setToolTip(
            "Waehlt einen Ueberordner und uebernimmt passende Betreiberordner automatisch in 'Pfad'."
        )
        bulk_assign_button.clicked.connect(self._bulk_assign_operator_paths_from_parent)
        remove_operator_button = QPushButton("Ausgewaehlte Zeilen loeschen")
        remove_operator_button.clicked.connect(self._remove_selected_operator_row)
        operator_buttons.addWidget(add_operator_button)
        operator_buttons.addWidget(import_operator_button)
        operator_buttons.addWidget(export_operator_button)
        operator_buttons.addWidget(choose_folder_button)
        operator_buttons.addWidget(bulk_assign_button)
        operator_buttons.addWidget(remove_operator_button)
        operator_buttons.addStretch(1)
        local_operators_layout.addLayout(operator_buttons)
        self.operator_view_stack.addWidget(local_operators_page)

        external_operators_page = QWidget()
        external_operators_layout = QVBoxLayout(external_operators_page)
        external_operators_layout.setContentsMargins(0, 0, 0, 0)

        self.external_operator_hint = QLabel(
            "Waehle oben eine Datenquelle. Dann kannst du die angebundenen Betreiberdaten laden und bearbeiten."
        )
        self.external_operator_hint.setWordWrap(True)
        external_operators_layout.addWidget(self.external_operator_hint)

        self.external_operator_search_input = QPlainTextEdit()
        self.external_operator_search_input.setPlaceholderText("Externe Liste suchen...")
        self.external_operator_search_input.setFixedHeight(58)
        self.external_operator_search_input.setTabChangesFocus(True)
        self.external_operator_search_input.textChanged.connect(
            lambda: self._apply_table_text_filter(
                self.external_operator_table,
                self._external_search_text(),
            )
        )
        external_operators_layout.addWidget(self.external_operator_search_input)

        self.external_show_local_only_checkbox = QCheckBox(
            "Nur Betreiber aus Projektliste anzeigen"
        )
        self.external_show_local_only_checkbox.setToolTip(
            "Zeigt in der externen Liste nur Betreiber an, die bereits in der lokalen Projektliste vorhanden sind."
        )
        self.external_show_local_only_checkbox.toggled.connect(
            self._refilter_external_operator_table
        )
        external_operators_layout.addWidget(self.external_show_local_only_checkbox)

        self.external_operator_table = QTableWidget(0, 7)
        self.external_operator_table.setHorizontalHeaderLabels(
            [
                "",
                "Betreibername",
                "Ansprechpartner",
                "Telefonnummer",
                "E-Mail",
                "Störnummer",
                "Gültigk.",
            ]
        )
        self._configure_standard_table(self.external_operator_table)
        ext_header = self.external_operator_table.horizontalHeader()
        ext_header.setStretchLastSection(False)
        ext_header.setMinimumSectionSize(90)
        ext_header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        ext_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        ext_header.setSectionResizeMode(1, QHeaderView.Interactive)
        ext_header.setSectionResizeMode(2, QHeaderView.Interactive)
        ext_header.setSectionResizeMode(3, QHeaderView.Interactive)
        ext_header.setSectionResizeMode(4, QHeaderView.Interactive)
        ext_header.setSectionResizeMode(5, QHeaderView.Interactive)
        ext_header.setSectionResizeMode(6, QHeaderView.Interactive)
        ext_header.resizeSection(0, 40)
        ext_header.resizeSection(1, 220)
        ext_header.resizeSection(2, 200)
        ext_header.resizeSection(3, 170)
        ext_header.resizeSection(4, 240)
        ext_header.resizeSection(5, 170)
        ext_header.resizeSection(6, 120)
        ext_header.setTextElideMode(Qt.ElideNone)
        external_operators_layout.addWidget(self.external_operator_table, 1)

        external_buttons = QHBoxLayout()
        self.external_operator_reload_button = QPushButton("Daten neu laden")
        self.external_operator_reload_button.clicked.connect(self._reload_selected_external_operator_source)
        self.external_operator_add_to_local_button = QPushButton("Auswahl zur Projektliste")
        self.external_operator_add_to_local_button.clicked.connect(self._add_selected_external_rows_to_local)
        self.external_operator_suggest_missing_button = QPushButton("Fehlende ergaenzen")
        self.external_operator_suggest_missing_button.setToolTip(
            "Prueft die Suchliste und legt fehlende Betreiber als neue Zeilen in dieser externen Quelle an."
        )
        self.external_operator_suggest_missing_button.clicked.connect(
            self._suggest_missing_external_search_entries
        )
        self.external_operator_add_row_button = QPushButton("Zeile hinzufuegen")
        self.external_operator_add_row_button.clicked.connect(self._add_external_operator_row)
        self.external_operator_remove_row_button = QPushButton("Zeile loeschen")
        self.external_operator_remove_row_button.clicked.connect(self._remove_selected_external_operator_row)
        self.external_operator_save_button = QPushButton("Aenderungen speichern")
        self.external_operator_save_button.clicked.connect(self._save_external_operator_changes)
        external_buttons.addWidget(self.external_operator_reload_button)
        external_buttons.addWidget(self.external_operator_add_to_local_button)
        external_buttons.addWidget(self.external_operator_suggest_missing_button)
        external_buttons.addWidget(self.external_operator_add_row_button)
        external_buttons.addWidget(self.external_operator_remove_row_button)
        external_buttons.addWidget(self.external_operator_save_button)
        external_buttons.addStretch(1)
        external_operators_layout.addLayout(external_buttons)
        self.operator_view_stack.addWidget(external_operators_page)
        self._external_operator_context = None
        self.external_operator_add_to_local_button.setEnabled(False)
        self.external_operator_suggest_missing_button.setEnabled(False)
        self.external_operator_remove_row_button.setEnabled(False)

        data_tab = QWidget()
        data_layout = QVBoxLayout(data_tab)
        self._data_page_index = self.page_stack.addWidget(data_tab)
        data_icon_flag = getattr(QStyle, "SP_DriveNetIcon", QStyle.SP_DirOpenIcon)
        data_icon = self.style().standardIcon(data_icon_flag)

        file_sources_group = QGroupBox("Dateiquellen (Excel, CSV, ODS, GPKG ...)")
        file_sources_layout = QVBoxLayout(file_sources_group)
        self.file_data_source_search_input = QLineEdit()
        self.file_data_source_search_input.setPlaceholderText("Dateiquellen suchen...")
        file_sources_layout.addWidget(self.file_data_source_search_input)
        self.file_data_source_table = self._create_data_source_table("file")
        self.file_data_source_table.itemChanged.connect(self._on_data_source_table_item_changed)
        self.file_data_source_search_input.textChanged.connect(
            lambda text: self._apply_table_text_filter(self.file_data_source_table, text)
        )
        file_sources_layout.addWidget(self.file_data_source_table)
        file_source_buttons = QHBoxLayout()
        connect_file_source_button = QPushButton("Verbindung herstellen...")
        connect_file_source_button.clicked.connect(self._add_file_source_via_dialog)
        preview_file_source_button = QPushButton("Daten anzeigen...")
        preview_file_source_button.clicked.connect(self._preview_selected_file_source)
        remove_file_source_button = QPushButton("Ausgewaehlte Dateiquelle loeschen")
        remove_file_source_button.clicked.connect(self._remove_selected_file_source_row)
        file_source_buttons.addWidget(connect_file_source_button)
        file_source_buttons.addWidget(preview_file_source_button)
        file_source_buttons.addWidget(remove_file_source_button)
        file_source_buttons.addStretch(1)
        file_sources_layout.addLayout(file_source_buttons)
        data_layout.addWidget(file_sources_group, 1)

        db_sources_group = QGroupBox("Datenbankquellen")
        db_sources_layout = QVBoxLayout(db_sources_group)
        self.db_data_source_search_input = QLineEdit()
        self.db_data_source_search_input.setPlaceholderText("Datenbankquellen suchen...")
        db_sources_layout.addWidget(self.db_data_source_search_input)
        self.db_data_source_table = self._create_data_source_table("qgis_uri")
        self.db_data_source_table.itemChanged.connect(self._on_data_source_table_item_changed)
        self.db_data_source_search_input.textChanged.connect(
            lambda text: self._apply_table_text_filter(self.db_data_source_table, text)
        )
        db_sources_layout.addWidget(self.db_data_source_table)
        db_source_buttons = QHBoxLayout()
        connect_db_source_button = QPushButton("Verbindung herstellen...")
        connect_db_source_button.clicked.connect(self._add_db_source_via_dialog)
        preview_db_source_button = QPushButton("Daten anzeigen...")
        preview_db_source_button.clicked.connect(self._preview_selected_db_source)
        remove_db_source_button = QPushButton("Ausgewaehlte Datenbankquelle loeschen")
        remove_db_source_button.clicked.connect(self._remove_selected_db_source_row)
        db_source_buttons.addWidget(connect_db_source_button)
        db_source_buttons.addWidget(preview_db_source_button)
        db_source_buttons.addWidget(remove_db_source_button)
        db_source_buttons.addStretch(1)
        db_sources_layout.addLayout(db_source_buttons)
        data_layout.addWidget(db_sources_group, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root_layout.addWidget(buttons)

        # Navigation order on the left: Betreiberliste, Datenquellen, Konfiguration.
        self._add_nav_item("Betreiberliste", operators_icon, self._operators_page_index)
        self._add_nav_item("Datenquellen", data_icon, self._data_page_index)
        self._add_nav_item("Konfiguration", config_icon, self._config_page_index)
        self._refresh_operator_source_selector()
        self.nav_list.setCurrentRow(0)

    def _add_nav_item(self, title: str, icon: QIcon, page_index: int):
        item = QListWidgetItem(icon, title)
        item.setData(Qt.UserRole, int(page_index))
        self.nav_list.addItem(item)

    def _on_nav_item_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        del previous
        if current is None:
            return
        page_index = int(current.data(Qt.UserRole))
        self.page_stack.setCurrentIndex(page_index)

    def _set_global_nextcloud_config(self, config: dict):
        self._global_nextcloud_config = {
            "nextcloud_base_url": str(config.get("nextcloud_base_url", "") or "").strip(),
            "nextcloud_user": str(config.get("nextcloud_user", "") or "").strip(),
            "nextcloud_app_password": str(config.get("nextcloud_app_password", "") or ""),
            "local_nextcloud_roots": _parse_roots(config.get("local_nextcloud_roots", [])),
            "nextcloud_folder_marker": str(
                config.get("nextcloud_folder_marker", DEFAULT_CONFIG.get("nextcloud_folder_marker", "Nextcloud"))
                or ""
            ).strip(),
        }

    def _global_nextcloud_roots(self) -> list[str]:
        roots = [
            str(path or "").strip()
            for path in self._global_nextcloud_config.get("local_nextcloud_roots", [])
            if str(path or "").strip()
        ]
        if roots:
            return roots
        return [
            str(path or "").strip()
            for path in DEFAULT_CONFIG.get("local_nextcloud_roots", [])
            if str(path or "").strip()
        ]

    def _configure_standard_table(
        self,
        table: QTableWidget,
        selection_mode: QAbstractItemView.SelectionMode = QAbstractItemView.SingleSelection,
        editable: bool = True,
        sortable: bool = True,
    ):
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(selection_mode)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setWordWrap(False)
        table.setSortingEnabled(sortable)
        if not editable:
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)

    def _make_field_combo(self) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItem("")
        for field_name in self.layer_fields:
            combo.addItem(field_name)
        return combo

    def _set_combo_text(self, combo: QComboBox, value: str):
        text = str(value or "").strip()
        index = combo.findText(text)
        if index >= 0:
            combo.setCurrentIndex(index)
        else:
            combo.setEditText(text)

    def _combo_text(self, combo: QComboBox) -> str:
        return combo.currentText().strip()

    def _external_search_text(self) -> str:
        widget = getattr(self, "external_operator_search_input", None)
        if isinstance(widget, QPlainTextEdit):
            return widget.toPlainText()
        if isinstance(widget, QLineEdit):
            return widget.text()
        return ""

    def _external_search_tokens(self, text: str) -> list[str]:
        return [token for _label, token in self._external_search_entries(text)]

    def _external_search_entries(self, text: str) -> list[tuple[str, str]]:
        raw = str(text or "")
        entries = []
        seen = set()
        for part in re.split(r"[\r\n;,|\t]+", raw):
            label = str(part or "").strip()
            if not label:
                continue
            token = self._normalize_operator_match_token(label)
            if not token or token in seen:
                continue
            seen.add(token)
            entries.append((label, token))
        return entries

    def _external_search_token_matches_operator(
        self,
        search_token: str,
        operator_token: str,
    ) -> bool:
        left = str(search_token or "").strip()
        right = str(operator_token or "").strip()
        if not left or not right:
            return False
        if left in right or right in left:
            return True

        left_words = [word for word in left.split() if len(word) >= 2]
        right_words = [word for word in right.split() if len(word) >= 2]
        if not left_words or not right_words:
            return False

        common = len(set(left_words) & set(right_words))
        if len(left_words) >= 2 and len(right_words) >= 2:
            return common >= 2
        return common >= 1

    def _external_operator_row_tokens(self) -> list[str]:
        row_tokens = []
        for row in range(self.external_operator_table.rowCount()):
            item = self.external_operator_table.item(row, 1)
            name = item.text().strip() if item else ""
            token = self._normalize_operator_match_token(name)
            if token:
                row_tokens.append(token)
        return row_tokens

    def _local_operator_name_tokens(self) -> set[str]:
        tokens = set()
        for row in range(self.operator_table.rowCount()):
            item = self.operator_table.item(row, 1)
            name = item.text().strip() if item else ""
            token = self._normalize_operator_match_token(name)
            if token:
                tokens.add(token)
        return tokens

    def _refilter_external_operator_table(self):
        self._apply_table_text_filter(
            self.external_operator_table,
            self._external_search_text(),
        )

    def _append_external_operator_row(
        self,
        operator_name: str = "",
        contact_name: str = "",
        phone: str = "",
        email: str = "",
        fault_number: str = "",
        validity: str = "",
    ) -> int:
        row = self.external_operator_table.rowCount()
        self.external_operator_table.insertRow(row)

        select_item = QTableWidgetItem("")
        select_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
        select_item.setCheckState(Qt.Unchecked)
        self.external_operator_table.setItem(row, 0, select_item)

        operator_item = QTableWidgetItem(str(operator_name or ""))
        operator_item.setData(
            Qt.UserRole,
            {
                "feature_id": None,
                "is_new": True,
                "original": {
                    "operator_name": "",
                    "contact_name": "",
                    "phone": "",
                    "email": "",
                    "fault_number": "",
                    "validity": "",
                },
            },
        )
        self.external_operator_table.setItem(row, 1, operator_item)
        self.external_operator_table.setItem(row, 2, QTableWidgetItem(str(contact_name or "")))
        self.external_operator_table.setItem(row, 3, QTableWidgetItem(str(phone or "")))
        self.external_operator_table.setItem(row, 4, QTableWidgetItem(str(email or "")))
        self.external_operator_table.setItem(row, 5, QTableWidgetItem(str(fault_number or "")))
        self.external_operator_table.setItem(row, 6, QTableWidgetItem(str(validity or "")))
        return row

    def _suggest_missing_external_search_entries(self):
        context = self._external_operator_context
        if not isinstance(context, dict):
            QMessageBox.information(
                self,
                "Betreiberliste",
                "Bitte zuerst eine externe Quelle auswaehlen und laden.",
            )
            return

        entries = self._external_search_entries(self._external_search_text())
        if not entries:
            QMessageBox.information(
                self,
                "Betreiberliste",
                "Bitte zuerst eine Liste mit Betreiber-Namen in das Suchfeld einfuegen.",
            )
            return

        if not context.get("editable", False):
            QMessageBox.warning(
                self,
                "Betreiberliste",
                "Diese Quelle ist nur lesbar. Fehlende Betreiber koennen hier nicht angelegt werden.",
            )
            return
        if not context.get("addable", False):
            QMessageBox.warning(
                self,
                "Betreiberliste",
                "Diese Quelle unterstuetzt keine neuen Zeilen.",
            )
            return

        row_tokens = self._external_operator_row_tokens()
        missing_labels = []
        for label, token in entries:
            if not any(
                self._external_search_token_matches_operator(token, row_token)
                for row_token in row_tokens
            ):
                missing_labels.append(label)

        if not missing_labels:
            QMessageBox.information(
                self,
                "Betreiberliste",
                "Alle Eintraege aus deiner Liste wurden in der externen Quelle gefunden.",
            )
            return

        preview_limit = 12
        missing_preview = "\n".join(f"- {name}" for name in missing_labels[:preview_limit])
        if len(missing_labels) > preview_limit:
            missing_preview += f"\n- ... (+{len(missing_labels) - preview_limit} weitere)"

        message = (
            f"In der externen Quelle fehlen {len(missing_labels)} Betreiber.\n\n"
            f"Nicht gefunden:\n{missing_preview}\n\n"
            "Diese Betreiber jetzt als neue Zeilen in der externen Quelle anlegen?"
        )

        answer = QMessageBox.question(
            self,
            "Betreiberliste",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return

        sorting_enabled = self.external_operator_table.isSortingEnabled()
        if sorting_enabled:
            self.external_operator_table.setSortingEnabled(False)

        old_block = self.external_operator_table.blockSignals(True)
        added = 0
        try:
            for label in missing_labels:
                self._append_external_operator_row(operator_name=label)
                added += 1
        finally:
            self.external_operator_table.blockSignals(old_block)
            if sorting_enabled:
                self.external_operator_table.setSortingEnabled(True)

        self._apply_table_text_filter(
            self.external_operator_table,
            self._external_search_text(),
        )

        QMessageBox.information(
            self,
            "Betreiberliste",
            f"{added} fehlende Betreiber als neue Zeilen angelegt. Zum Persistieren bitte speichern.",
        )

        save_answer = QMessageBox.question(
            self,
            "Betreiberliste",
            "Neue Zeilen jetzt direkt in die externe Quelle speichern?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if save_answer == QMessageBox.Yes:
            self._save_external_operator_changes()

    def _apply_table_text_filter(self, table: QTableWidget, text: str):
        if table is self.external_operator_table:
            raw = str(text or "")
            tokens = self._external_search_tokens(raw)
            list_mode = len(tokens) > 1 or any(sep in raw for sep in ("\n", "\r", ";", ",", "|", "\t"))
            show_local_only = (
                hasattr(self, "external_show_local_only_checkbox")
                and self.external_show_local_only_checkbox.isChecked()
            )
            local_tokens = self._local_operator_name_tokens() if show_local_only else set()

            for row in range(table.rowCount()):
                operator_item = table.item(row, 1)
                operator_name = operator_item.text() if operator_item is not None else ""
                operator_token = self._normalize_operator_match_token(operator_name)
                visible = True

                if list_mode:
                    if tokens:
                        visible = any(
                            self._external_search_token_matches_operator(token, operator_token)
                            for token in tokens
                        )
                else:
                    token = raw.strip().casefold()
                    if token:
                        row_values = []
                        for col in range(table.columnCount()):
                            item = table.item(row, col)
                            if item is not None:
                                row_values.append(item.text())
                        row_text = " | ".join(row_values).casefold()
                        visible = token in row_text

                if show_local_only:
                    visible = visible and bool(operator_token) and operator_token in local_tokens

                table.setRowHidden(row, not visible)
            return

        token = str(text or "").strip().casefold()
        for row in range(table.rowCount()):
            row_values = []
            for col in range(table.columnCount()):
                item = table.item(row, col)
                if item is not None:
                    row_values.append(item.text())
                    if table is self.operator_table and col == 8:
                        hidden_path = str(item.data(Qt.UserRole) or "").strip()
                        if hidden_path and hidden_path != item.text():
                            row_values.append(hidden_path)
                    continue
                widget = table.cellWidget(row, col)
                if isinstance(widget, QLineEdit):
                    row_values.append(widget.text())
            row_text = " | ".join(row_values).casefold()
            table.setRowHidden(row, bool(token) and token not in row_text)

    def _set_operator_table_visual_order(self):
        header = self.operator_table.horizontalHeader()
        # Sichtbare Reihenfolge: Betreibername | Stand | Datenquelle | Pfad
        desired = [1, 3, 0, 8, 2, 4, 5, 6, 7]
        for target_visual_index, logical_index in enumerate(desired):
            current_visual_index = header.visualIndex(logical_index)
            if current_visual_index < 0 or current_visual_index == target_visual_index:
                continue
            header.moveSection(current_visual_index, target_visual_index)

    def _suggest_fields(self):
        suggestions = {
            "path": ["planpath", "quelle_pfad", "pfad", "path", "filepath"],
            "file": ["quelle_1", "e_dok_plan", "file_link", "share_file", "link_file"],
            "folder": ["quelle_2", "e_dok_ordn", "folder_link", "share_folder", "link_folder"],
            "name": ["quelle", "dateiname", "filename", "name"],
            "stand": ["Stand", "stand", "datum", "date", "modified", "aenderungsdatum"],
            "op_name": ["Betreiber", "betreiber", "operator", "betreibername"],
            "op_contact": ["betr_anspr", "ansprechpartner", "kontaktperson", "contact"],
            "op_phone": ["betr_tel", "telefon", "telefonnummer", "phone", "tel"],
            "op_email": ["betr_email", "email", "e_mail", "mail"],
            "op_fault": ["stoer-nr", "Stör-Nr.", "Stoer-Nr.", "stoernummer", "betr_stoer", "störnummer"],
            "op_validity": ["gueltigk", "Gültigk.", "Gueltigk.", "gueltigkeit", "gültigkeit", "validity"],
            "op_stand": ["Stand", "stand", "gueltig_ab", "gültig_ab", "statusdatum"],
        }

        if not self._combo_text(self.path_field):
            self._set_combo_text(
                self.path_field,
                _first_field_match(self.layer_fields, suggestions["path"]),
            )
        if not self._combo_text(self.file_field):
            self._set_combo_text(
                self.file_field,
                _first_field_match(self.layer_fields, suggestions["file"]),
            )
        if not self._combo_text(self.folder_field):
            self._set_combo_text(
                self.folder_field,
                _first_field_match(self.layer_fields, suggestions["folder"]),
            )
        if not self._combo_text(self.name_field):
            self._set_combo_text(
                self.name_field,
                _first_field_match(self.layer_fields, suggestions["name"]),
            )
        if not self._combo_text(self.stand_field):
            self._set_combo_text(
                self.stand_field,
                _first_field_match(self.layer_fields, suggestions["stand"]),
            )
        if not self._combo_text(self.operator_name_field):
            self._set_combo_text(
                self.operator_name_field,
                _first_field_match(self.layer_fields, suggestions["op_name"]),
            )
        if not self._combo_text(self.operator_contact_field):
            self._set_combo_text(
                self.operator_contact_field,
                _first_field_match(self.layer_fields, suggestions["op_contact"]),
            )
        if not self._combo_text(self.operator_phone_field):
            self._set_combo_text(
                self.operator_phone_field,
                _first_field_match(self.layer_fields, suggestions["op_phone"]),
            )
        if not self._combo_text(self.operator_email_field):
            self._set_combo_text(
                self.operator_email_field,
                _first_field_match(self.layer_fields, suggestions["op_email"]),
            )
        if not self._combo_text(self.operator_fault_field):
            self._set_combo_text(
                self.operator_fault_field,
                _first_field_match(self.layer_fields, suggestions["op_fault"]),
            )
        if not self._combo_text(self.operator_validity_field):
            self._set_combo_text(
                self.operator_validity_field,
                _first_field_match(self.layer_fields, suggestions["op_validity"]),
            )
        if not self._combo_text(self.operator_stand_field):
            self._set_combo_text(
                self.operator_stand_field,
                _first_field_match(self.layer_fields, suggestions["op_stand"]),
            )

    def _clear_optional_fields(self):
        self.folder_field.setCurrentText("")
        self.name_field.setCurrentText("")
        self.stand_field.setCurrentText("")

    def _add_operator_row(self, values=None):
        if isinstance(values, bool):
            values = None
        values = values or ["", "", "", "", "", "", "", "", ""]
        sorting_enabled = self.operator_table.isSortingEnabled()
        if sorting_enabled:
            self.operator_table.setSortingEnabled(False)
        try:
            row = self.operator_table.rowCount()
            self.operator_table.insertRow(row)
            for col in range(9):
                text = str(values[col]) if col < len(values) else ""
                if col == 8:
                    self._set_operator_path_item(row, text)
                else:
                    self.operator_table.setItem(row, col, QTableWidgetItem(text))
            self.operator_table.setCurrentCell(row, 1)
        finally:
            if sorting_enabled:
                self.operator_table.setSortingEnabled(True)
        self._apply_table_text_filter(self.operator_table, self.operator_search_input.text())
        self._refilter_external_operator_table()

    def _operator_path_alias(self, path_value: str) -> str:
        raw = str(path_value or "").strip()
        if not raw:
            return ""
        normalized = raw.replace("\\", "/")
        trimmed = normalized.rstrip("/")
        if not trimmed:
            return normalized

        for root in self._global_nextcloud_roots():
            root_norm = str(root or "").replace("\\", "/").rstrip("/")
            if not root_norm:
                continue
            if trimmed == root_norm:
                return "/"
            if trimmed.lower().startswith(root_norm.lower() + "/"):
                rel = trimmed[len(root_norm) :].lstrip("/")
                return f"/{rel}" if rel else "/"
        return trimmed

    def _operator_path_value(self, row_index: int) -> str:
        item = self.operator_table.item(row_index, 8)
        if item is None:
            return ""
        stored = str(item.data(Qt.UserRole) or "").strip()
        if stored:
            return stored
        return item.text().strip()

    def _set_operator_path_item(self, row_index: int, path_value: str):
        full_path = str(path_value or "").strip()
        alias = self._operator_path_alias(full_path)
        item = self.operator_table.item(row_index, 8)
        if item is None:
            item = QTableWidgetItem()
            self.operator_table.setItem(row_index, 8, item)
        item.setData(Qt.UserRole, full_path)
        item.setToolTip(full_path)
        item.setText(alias if full_path else "")
        self._auto_fill_operator_stand_from_path(row_index, full_path)

    def _oldest_file_date_in_path(self, path_value: str) -> str:
        target = str(path_value or "").strip()
        if not target:
            return ""
        if not os.path.exists(target):
            return ""

        try:
            if os.path.isfile(target):
                ts = os.path.getmtime(target)
                return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")

            if not os.path.isdir(target):
                return ""

            oldest_ts = None
            for root, _dirnames, filenames in os.walk(target):
                for filename in filenames:
                    file_path = os.path.join(root, filename)
                    try:
                        ts = os.path.getmtime(file_path)
                    except Exception:
                        continue
                    if oldest_ts is None or ts < oldest_ts:
                        oldest_ts = ts

            if oldest_ts is None:
                return ""
            return datetime.fromtimestamp(oldest_ts).strftime("%Y-%m-%d")
        except Exception:
            return ""

    def _auto_fill_operator_stand_from_path(self, row_index: int, full_path: str):
        if row_index < 0 or row_index >= self.operator_table.rowCount():
            return
        if not str(full_path or "").strip():
            return

        stand_item = self.operator_table.item(row_index, 3)
        if stand_item is None:
            stand_item = QTableWidgetItem("")
            self.operator_table.setItem(row_index, 3, stand_item)

        current_text = stand_item.text().strip().lower()
        if current_text and current_text not in ("<null>", "null", "none"):
            # Bestehende/manuelle Eingabe nicht ueberschreiben.
            return

        oldest_date = self._oldest_file_date_in_path(full_path)
        if not oldest_date:
            return
        stand_item.setText(oldest_date)

    def _on_operator_table_item_changed(self, item: QTableWidgetItem):
        if item is None:
            return

        if item.column() == 8:
            current_text = item.text().strip()
            stored_full_path = str(item.data(Qt.UserRole) or "").strip()
            if stored_full_path and current_text == self._operator_path_alias(stored_full_path):
                self._refilter_external_operator_table()
                return

            old_block = self.operator_table.blockSignals(True)
            try:
                self._set_operator_path_item(item.row(), current_text)
            finally:
                self.operator_table.blockSignals(old_block)

        self._refilter_external_operator_table()

    def _remove_selected_operator_row(self):
        selected = self.operator_table.selectionModel().selectedRows()
        if not selected:
            return
        row_indices = sorted({index.row() for index in selected}, reverse=True)
        for row_index in row_indices:
            self.operator_table.removeRow(row_index)
        self._apply_table_text_filter(self.operator_table, self.operator_search_input.text())
        self._refilter_external_operator_table()

    def _choose_folder_for_row(self, row_index: int):
        if row_index < 0 or row_index >= self.operator_table.rowCount():
            return
        current_path = self._operator_path_value(row_index)
        start_dir = ""
        if current_path:
            start_dir = current_path
        else:
            roots = self._global_nextcloud_roots()
            if roots:
                start_dir = roots[0]

        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Betreiber-Ordner waehlen",
            start_dir,
        )
        if not selected_dir:
            return

        self._set_operator_path_item(row_index, selected_dir)

    def _normalize_operator_match_token(self, value: str) -> str:
        token = str(value or "").strip().lower()
        token = (
            token.replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
        )
        token = "".join(ch if ch.isalnum() else " " for ch in token)
        return " ".join(token.split())

    def _bulk_assign_operator_paths_from_parent(self):
        start_dir = ""
        roots = self._global_nextcloud_roots()
        if roots:
            start_dir = roots[0]
        elif os.path.expanduser("~"):
            start_dir = os.path.expanduser("~")

        base_dir = QFileDialog.getExistingDirectory(
            self,
            "Ueberordner fuer Betreiberordner waehlen",
            start_dir,
        )
        if not base_dir:
            return

        folder_candidates = []
        base_depth = base_dir.rstrip("/\\").count(os.sep)
        for root, dirnames, _filenames in os.walk(base_dir):
            for dirname in dirnames:
                full_path = os.path.join(root, dirname)
                token = self._normalize_operator_match_token(dirname)
                if not token:
                    continue
                depth = max(0, full_path.rstrip("/\\").count(os.sep) - base_depth)
                folder_candidates.append((full_path, token, depth))

        if not folder_candidates:
            QMessageBox.information(
                self,
                "Betreiberliste",
                "Im gewaehlten Ueberordner wurden keine Unterordner gefunden.",
            )
            return

        sorting_enabled = self.operator_table.isSortingEnabled()
        if sorting_enabled:
            self.operator_table.setSortingEnabled(False)

        matched_rows = 0
        changed_rows = 0
        skipped_with_existing_path = 0
        try:
            for row in range(self.operator_table.rowCount()):
                operator_item = self.operator_table.item(row, 1)
                operator_name = operator_item.text().strip() if operator_item else ""
                if not operator_name:
                    continue

                current_path = self._operator_path_value(row)
                if current_path:
                    skipped_with_existing_path += 1
                    continue

                operator_token = self._normalize_operator_match_token(operator_name)
                if not operator_token:
                    continue

                best_match_path = ""
                best_score = None
                for folder_path, folder_token, depth in folder_candidates:
                    if operator_token in folder_token:
                        match_type = 0
                    elif folder_token in operator_token:
                        match_type = 1
                    else:
                        continue
                    score = (match_type, abs(len(folder_token) - len(operator_token)), depth, len(folder_token))
                    if best_score is None or score < best_score:
                        best_score = score
                        best_match_path = folder_path

                if not best_match_path:
                    continue

                matched_rows += 1
                if current_path != best_match_path:
                    self._set_operator_path_item(row, best_match_path)
                    changed_rows += 1
        finally:
            if sorting_enabled:
                self.operator_table.setSortingEnabled(True)

        self._apply_table_text_filter(self.operator_table, self.operator_search_input.text())

        QMessageBox.information(
            self,
            "Betreiberliste",
            (
                f"{matched_rows} Betreiber mit Ordner abgeglichen, "
                f"{changed_rows} Pfade neu gesetzt, "
                f"{skipped_with_existing_path} Zeilen mit bestehendem Pfad uebersprungen."
            ),
        )

    def _choose_folder_for_selected_row(self):
        selected = self.operator_table.selectionModel().selectedRows()
        if not selected:
            QMessageBox.information(
                self,
                "Betreiberliste",
                "Bitte zuerst eine Zeile in der Betreiberliste auswaehlen.",
            )
            return
        self._choose_folder_for_row(selected[0].row())

    def _norm_header_token(self, value: str) -> str:
        token = str(value or "").strip().lower()
        token = (
            token.replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
        )
        return "".join(ch for ch in token if ch.isalnum())

    def _csv_header_mapping(self, headers: list[str]) -> dict[str, str]:
        aliases = {
            "source_name": [
                "source_name",
                "datenquelle",
                "quelle",
            ],
            "operator_name": [
                "operator_name",
                "betreibername",
                "betreiber",
                "name",
            ],
            "validity": [
                "validity",
                "gueltigkeit",
                "gültigkeit",
                "gueltigk",
                "gültigk",
            ],
            "stand": [
                "stand",
                "stand_datum",
                "statusdatum",
            ],
            "contact_name": [
                "contact_name",
                "ansprechpartner",
                "kontakt",
                "kontaktperson",
            ],
            "phone": [
                "phone",
                "telefon",
                "telefonnummer",
                "betr_tel",
                "tel",
            ],
            "email": [
                "email",
                "mail",
                "e-mail",
                "e_mail",
                "betr_email",
            ],
            "fault_number": [
                "fault_number",
                "stoernummer",
                "stoernr",
                "stoernummern",
                "stornummer",
                "betr_stoer",
            ],
            "folder_path": [
                "folder_path",
                "ordnerpfad",
                "ordner",
                "path",
                "pfad",
            ],
        }

        normalized_headers = {
            self._norm_header_token(header): header for header in headers if header is not None
        }

        mapping = {}
        for key, candidates in aliases.items():
            found = ""
            for candidate in candidates:
                token = self._norm_header_token(candidate)
                if token in normalized_headers:
                    found = normalized_headers[token]
                    break
            mapping[key] = found
        return mapping

    def _read_operators_from_csv(self, file_path: str) -> list[dict]:
        with open(file_path, "r", encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(4096)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t,")
            except Exception:
                dialect = csv.excel
            reader = csv.DictReader(handle, dialect=dialect)
            if not reader.fieldnames:
                return []

            mapping = self._csv_header_mapping(list(reader.fieldnames))
            operators = []
            for row in reader:
                entry = {
                    "source_name": str(row.get(mapping["source_name"], "") or "").strip()
                    if mapping.get("source_name")
                    else "",
                    "operator_name": str(row.get(mapping["operator_name"], "") or "").strip()
                    if mapping["operator_name"]
                    else "",
                    "validity": str(row.get(mapping["validity"], "") or "").strip()
                    if mapping.get("validity")
                    else "",
                    "stand": str(row.get(mapping["stand"], "") or "").strip()
                    if mapping.get("stand")
                    else "",
                    "contact_name": str(row.get(mapping["contact_name"], "") or "").strip()
                    if mapping["contact_name"]
                    else "",
                    "phone": str(row.get(mapping["phone"], "") or "").strip()
                    if mapping["phone"]
                    else "",
                    "email": str(row.get(mapping["email"], "") or "").strip()
                    if mapping["email"]
                    else "",
                    "fault_number": str(row.get(mapping["fault_number"], "") or "").strip()
                    if mapping["fault_number"]
                    else "",
                    "folder_path": str(row.get(mapping["folder_path"], "") or "").strip()
                    if mapping["folder_path"]
                    else "",
                }
                normalized = _normalize_operator_entry(entry)
                if any(
                    [
                        normalized["operator_name"],
                        normalized["validity"],
                        normalized["stand"],
                        normalized["contact_name"],
                        normalized["phone"],
                        normalized["email"],
                        normalized["fault_number"],
                        normalized["folder_path"],
                    ]
                ):
                    operators.append(normalized)
            return operators

    def _write_operators_to_csv(self, file_path: str, operators: list[dict]):
        fieldnames = [
            "Datenquelle",
            "Betreibername",
            "Gültigkeit",
            "Stand",
            "Ansprechpartner",
            "Telefonnummer",
            "E-Mail",
            "Störnummer",
            "Ordnerpfad",
        ]
        with open(file_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";")
            writer.writeheader()
            for row in operators:
                normalized = _normalize_operator_entry(row)
                writer.writerow(
                    {
                        "Datenquelle": normalized["source_name"],
                        "Betreibername": normalized["operator_name"],
                        "Gültigkeit": normalized["validity"],
                        "Stand": normalized["stand"],
                        "Ansprechpartner": normalized["contact_name"],
                        "Telefonnummer": normalized["phone"],
                        "E-Mail": normalized["email"],
                        "Störnummer": normalized["fault_number"],
                        "Ordnerpfad": normalized["folder_path"],
                    }
                )

    def _import_operators(self):
        start_dir = ""
        roots = self._global_nextcloud_roots()
        if roots:
            start_dir = roots[0]
        elif os.path.expanduser("~"):
            start_dir = os.path.expanduser("~")

        file_path, selected_filter = QFileDialog.getOpenFileName(
            self,
            "Betreiberliste importieren",
            start_dir,
            "JSON-Datei (*.json);;CSV-Datei (*.csv);;Alle Dateien (*)",
        )
        if not file_path:
            return

        try:
            lower_path = file_path.lower()
            operators = []
            if lower_path.endswith(".csv"):
                operators = self._read_operators_from_csv(file_path)
            elif lower_path.endswith(".json"):
                with open(file_path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if not isinstance(loaded, list):
                    raise ValueError("JSON muss eine Liste von Betreiber-Eintraegen enthalten.")
                for entry in loaded:
                    normalized = _normalize_operator_entry(entry)
                    if any(
                        [
                            normalized["operator_name"],
                            normalized["validity"],
                            normalized["stand"],
                            normalized["contact_name"],
                            normalized["phone"],
                            normalized["email"],
                            normalized["fault_number"],
                            normalized["folder_path"],
                        ]
                    ):
                        operators.append(normalized)
            elif "CSV" in selected_filter:
                operators = self._read_operators_from_csv(file_path)
            else:
                # Fallback: erst JSON, dann CSV versuchen.
                try:
                    with open(file_path, "r", encoding="utf-8") as handle:
                        loaded = json.load(handle)
                    if isinstance(loaded, list):
                        for entry in loaded:
                            normalized = _normalize_operator_entry(entry)
                            if any(
                                [
                                    normalized["operator_name"],
                                    normalized["validity"],
                                    normalized["stand"],
                                    normalized["contact_name"],
                                    normalized["phone"],
                                    normalized["email"],
                                    normalized["fault_number"],
                                    normalized["folder_path"],
                                ]
                            ):
                                operators.append(normalized)
                    else:
                        raise ValueError("Unbekanntes Importformat.")
                except Exception:
                    operators = self._read_operators_from_csv(file_path)

            self._set_operators(operators)
            QMessageBox.information(
                self,
                "Import erfolgreich",
                f"{len(operators)} Betreiber-Eintraege importiert.",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Import fehlgeschlagen", str(exc))

    def _export_operators(self):
        operators = self._operators()

        start_dir = ""
        roots = self._global_nextcloud_roots()
        if roots:
            start_dir = roots[0]
        elif os.path.expanduser("~"):
            start_dir = os.path.expanduser("~")

        suggested_path = os.path.join(start_dir, "betreiberliste.json") if start_dir else "betreiberliste.json"
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Betreiberliste exportieren",
            suggested_path,
            "JSON-Datei (*.json);;CSV-Datei (*.csv)",
        )
        if not file_path:
            return

        try:
            lower_path = file_path.lower()
            if lower_path.endswith(".csv"):
                self._write_operators_to_csv(file_path, operators)
            elif lower_path.endswith(".json"):
                with open(file_path, "w", encoding="utf-8") as handle:
                    json.dump(operators, handle, ensure_ascii=False, indent=2)
            elif "CSV" in selected_filter:
                if not lower_path.endswith(".csv"):
                    file_path += ".csv"
                self._write_operators_to_csv(file_path, operators)
            else:
                if not lower_path.endswith(".json"):
                    file_path += ".json"
                with open(file_path, "w", encoding="utf-8") as handle:
                    json.dump(operators, handle, ensure_ascii=False, indent=2)

            QMessageBox.information(
                self,
                "Export erfolgreich",
                f"{len(operators)} Betreiber-Eintraege exportiert.",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Export fehlgeschlagen", str(exc))

    def _set_operators(self, operators):
        self.operator_table.setRowCount(0)
        for entry in operators or []:
            if isinstance(entry, dict):
                values = [
                    str(
                        entry.get(
                            "source_name",
                            entry.get("_source_name", entry.get("data_source", entry.get("datenquelle", ""))),
                        )
                        or ""
                    ),
                    str(entry.get("operator_name", entry.get("betreiber", "")) or ""),
                    str(
                        entry.get(
                            "validity",
                            entry.get(
                                "gueltigkeit",
                                entry.get("gültigkeit", entry.get("gueltigk", entry.get("gültigk", ""))),
                            ),
                        )
                        or ""
                    ),
                    str(entry.get("stand", entry.get("operator_stand", entry.get("stand_datum", ""))) or ""),
                    str(
                        entry.get("contact_name", entry.get("ansprechpartner", entry.get("kontakt", "")))
                        or ""
                    ),
                    str(entry.get("phone", entry.get("telefonnummer", "")) or ""),
                    str(entry.get("email", entry.get("mail", "")) or ""),
                    str(entry.get("fault_number", entry.get("stoernummer", "")) or ""),
                    str(
                        entry.get(
                            "folder_path",
                            entry.get("ordnerpfad", entry.get("ordner", entry.get("path", ""))),
                        )
                        or ""
                    ),
                ]
            elif isinstance(entry, (list, tuple)):
                raw_values = [str(x or "") for x in list(entry)]
                if len(raw_values) >= 9:
                    values = raw_values[:9]
                elif len(raw_values) >= 7:
                    values = [
                        raw_values[0],
                        raw_values[1],
                        "",
                        "",
                        raw_values[2],
                        raw_values[3],
                        raw_values[4],
                        raw_values[5],
                        raw_values[6],
                    ]
                else:
                    values = [""] + raw_values[:8]
                while len(values) < 9:
                    values.append("")
            else:
                values = ["", str(entry or ""), "", "", "", "", "", "", ""]
            self._add_operator_row(values)
        self._refilter_external_operator_table()

    def _operators(self):
        result = []
        for row in range(self.operator_table.rowCount()):
            values = []
            for col in range(9):
                if col == 8:
                    values.append(self._operator_path_value(row))
                    continue
                item = self.operator_table.item(row, col)
                values.append(item.text().strip() if item else "")
            if any(values[1:]):
                result.append(
                    {
                        "source_name": values[0],
                        "operator_name": values[1],
                        "validity": values[2],
                        "stand": values[3],
                        "contact_name": values[4],
                        "phone": values[5],
                        "email": values[6],
                        "fault_number": values[7],
                        "folder_path": values[8],
                    }
                )
        return result

    def _source_display_name(self, source: dict, fallback_index: int | None = None) -> str:
        normalized = _normalize_data_source_entry(source)
        name = str(normalized.get("name", "") or "").strip()
        if not name:
            name = self._source_label_from_path(str(normalized.get("source", "") or ""))
        if not name:
            if fallback_index is None:
                return "Quelle"
            return f"Quelle {fallback_index + 1}"
        return name

    def _refresh_operator_source_selector(self):
        current_key = ""
        if hasattr(self, "operator_source_combo") and self.operator_source_combo is not None:
            current_key = str(self.operator_source_combo.currentData() or "")

        self.operator_source_combo.blockSignals(True)
        self.operator_source_combo.clear()
        self.operator_source_combo.addItem("Projektliste (lokal)", "local")

        for idx, source in enumerate(self._data_sources()):
            normalized = _normalize_data_source_entry(source)
            source_name = self._source_display_name(normalized, idx)
            suffix = "" if _to_bool(normalized.get("enabled", True), True) else " (inaktiv)"
            self.operator_source_combo.addItem(f"Datenquelle: {source_name}{suffix}", f"external:{idx}")

        restore_index = self.operator_source_combo.findData(current_key)
        if restore_index < 0:
            restore_index = 0
        self.operator_source_combo.setCurrentIndex(restore_index)
        self.operator_source_combo.blockSignals(False)
        self._on_operator_source_changed()

    def _on_data_source_table_item_changed(self, item):
        del item
        self._refresh_operator_source_selector()

    def _selected_external_source_entry(self):
        key = str(self.operator_source_combo.currentData() or "")
        if not key.startswith("external:"):
            return None
        try:
            source_index = int(key.split(":", 1)[1])
        except Exception:
            return None
        sources = self._data_sources()
        if source_index < 0 or source_index >= len(sources):
            return None
        normalized = _normalize_data_source_entry(sources[source_index])
        return normalized, source_index

    def _on_operator_source_changed(self):
        key = str(self.operator_source_combo.currentData() or "")
        if key == "local":
            self.operator_view_stack.setCurrentIndex(0)
            self._external_operator_context = None
            self.external_operator_add_to_local_button.setEnabled(False)
            self.external_operator_suggest_missing_button.setEnabled(False)
            self.external_operator_remove_row_button.setEnabled(False)
            return

        self.operator_view_stack.setCurrentIndex(1)
        self.external_operator_add_to_local_button.setEnabled(True)
        self._reload_selected_external_operator_source()

    def _external_operator_context_from_source(self, source: dict) -> tuple[dict | None, str]:
        normalized_source = _normalize_data_source_entry(source)
        layer = self._load_external_source_layer(normalized_source)
        if layer is None:
            return None, "Quelle konnte nicht geladen werden."

        fallback_name = (
            str(normalized_source.get("operator_name_field", "") or "").strip()
            or self._combo_text(self.operator_name_field)
            or str(DEFAULT_CONFIG.get("operator_name_field_name", "") or "")
        )
        fallback_contact = (
            str(normalized_source.get("contact_name_field", "") or "").strip()
            or self._combo_text(self.operator_contact_field)
            or str(DEFAULT_CONFIG.get("operator_contact_field_name", "") or "")
        )
        fallback_phone = (
            str(normalized_source.get("phone_field", "") or "").strip()
            or self._combo_text(self.operator_phone_field)
            or str(DEFAULT_CONFIG.get("operator_phone_field_name", "") or "")
        )
        fallback_email = (
            str(normalized_source.get("email_field", "") or "").strip()
            or self._combo_text(self.operator_email_field)
            or str(DEFAULT_CONFIG.get("operator_email_field_name", "") or "")
        )
        fallback_fault = (
            str(normalized_source.get("fault_number_field", "") or "").strip()
            or self._combo_text(self.operator_fault_field)
            or str(DEFAULT_CONFIG.get("operator_fault_field_name", "") or "")
        )
        fallback_validity = (
            self._combo_text(self.operator_validity_field)
            or str(DEFAULT_CONFIG.get("operator_validity_field_name", "") or "")
        )
        fallback_stand = (
            self._combo_text(self.operator_stand_field)
            or str(DEFAULT_CONFIG.get("operator_stand_field_name", "") or "")
        )

        field_indices = {
            "operator_name": -1,
            "contact_name": -1,
            "phone": -1,
            "email": -1,
            "fault_number": -1,
            "validity": -1,
        }

        generic_fields = self._layer_uses_generic_fields(layer)
        header_tokens = self._header_tokens_from_first_feature(layer) if generic_fields else []

        if generic_fields and header_tokens:
            name_col = self._resolve_column_index(
                header_tokens,
                fallback_name,
                ["operator_name", "betreibername", "betreiber", "name"],
            )
            if name_col < 0 and header_tokens:
                name_col = 0
            if name_col < 0:
                return None, "Spalte Betreibername wurde in der Quelle nicht gefunden."

            field_indices["operator_name"] = name_col
            field_indices["contact_name"] = self._resolve_column_index(
                header_tokens,
                fallback_contact,
                ["contact_name", "ansprechpartner", "kontakt", "kontaktperson", "betr_anspr"],
            )
            field_indices["phone"] = self._resolve_column_index(
                header_tokens,
                fallback_phone,
                ["phone", "telefon", "telefonnummer", "betr_tel", "tel"],
            )
            field_indices["email"] = self._resolve_column_index(
                header_tokens,
                fallback_email,
                ["email", "mail", "e-mail", "e_mail", "betr_email"],
            )
            field_indices["fault_number"] = self._resolve_column_index(
                header_tokens,
                fallback_fault,
                ["fault_number", "stoernummer", "stoernr", "stornummer", "betr_stoer", "stoer_nr", "stoernr"],
            )
            field_indices["validity"] = self._resolve_column_index(
                header_tokens,
                fallback_validity,
                ["validity", "gueltigkeit", "gültigkeit", "gueltigk", "gültigk"],
            )
        else:
            name_field = self._resolve_field_name_in_layer(
                layer,
                fallback_name,
                ["operator_name", "betreibername", "betreiber", "name"],
            )
            if not name_field and layer.fields():
                name_field = layer.fields()[0].name()
            if not name_field:
                return None, "Spalte Betreibername wurde in der Quelle nicht gefunden."

            field_indices["operator_name"] = layer.fields().indexOf(name_field)

            contact_field = self._resolve_field_name_in_layer(
                layer,
                fallback_contact,
                ["contact_name", "ansprechpartner", "kontakt", "kontaktperson", "betr_anspr"],
            )
            if contact_field:
                field_indices["contact_name"] = layer.fields().indexOf(contact_field)

            phone_field = self._resolve_field_name_in_layer(
                layer,
                fallback_phone,
                ["phone", "telefon", "telefonnummer", "betr_tel", "tel"],
            )
            if phone_field:
                field_indices["phone"] = layer.fields().indexOf(phone_field)

            email_field = self._resolve_field_name_in_layer(
                layer,
                fallback_email,
                ["email", "mail", "e-mail", "e_mail", "betr_email"],
            )
            if email_field:
                field_indices["email"] = layer.fields().indexOf(email_field)

            fault_field = self._resolve_field_name_in_layer(
                layer,
                fallback_fault,
                ["fault_number", "stoernummer", "stoernr", "stornummer", "betr_stoer", "stoer_nr", "stoernr"],
            )
            if fault_field:
                field_indices["fault_number"] = layer.fields().indexOf(fault_field)

            validity_field = self._resolve_field_name_in_layer(
                layer,
                fallback_validity,
                ["validity", "gueltigkeit", "gültigkeit", "gueltigk", "gültigk"],
            )
            if validity_field:
                field_indices["validity"] = layer.fields().indexOf(validity_field)

        rows = []
        for row_idx, feature in enumerate(layer.getFeatures()):
            if row_idx >= 50000:
                break

            if generic_fields and header_tokens and row_idx == 0:
                continue

            values = {}
            for key, field_idx in field_indices.items():
                value = self._safe_attribute_by_index(feature, field_idx)
                values[key] = "" if value is None else str(value)
            rows.append(
                {
                    "feature_id": feature.id(),
                    "values": values,
                }
            )

        source_name = self._source_display_name(normalized_source)

        editable = False
        addable = False
        deletable = False
        provider_name = ""
        try:
            provider = layer.dataProvider()
            if provider is not None:
                provider_name = str(provider.name() or "").strip()
                caps = int(provider.capabilities())
                editable = bool(caps & QgsVectorDataProvider.ChangeAttributeValues)
                addable = bool(caps & QgsVectorDataProvider.AddFeatures)
                deletable = bool(caps & QgsVectorDataProvider.DeleteFeatures)
        except Exception:
            editable = False
            addable = False
            deletable = False

        return (
            {
                "source": normalized_source,
                "source_name": source_name,
                "provider_name": provider_name,
                "layer": layer,
                "rows": rows,
                "field_indices": field_indices,
                "editable": editable,
                "addable": addable,
                "deletable": deletable,
                "generic_fields": generic_fields,
                "field_count": len(layer.fields()),
            },
            "",
        )

    def _reload_selected_external_operator_source(self):
        self.external_operator_table.setRowCount(0)
        self._external_operator_context = None

        selected = self._selected_external_source_entry()
        if selected is None:
            self.external_operator_hint.setText("Waehle oben eine angebundene Datenquelle aus.")
            self.external_operator_add_to_local_button.setEnabled(False)
            self.external_operator_suggest_missing_button.setEnabled(False)
            self.external_operator_save_button.setEnabled(False)
            self.external_operator_add_row_button.setEnabled(False)
            self.external_operator_remove_row_button.setEnabled(False)
            return

        source, source_index = selected
        context, error = self._external_operator_context_from_source(source)
        if context is None:
            self.external_operator_hint.setText(
                f"{self._source_display_name(source, source_index)}: {error}"
            )
            self.external_operator_add_to_local_button.setEnabled(False)
            self.external_operator_suggest_missing_button.setEnabled(False)
            self.external_operator_save_button.setEnabled(False)
            self.external_operator_add_row_button.setEnabled(False)
            self.external_operator_remove_row_button.setEnabled(False)
            return

        self._external_operator_context = context
        rows = context["rows"]
        sorting_enabled = self.external_operator_table.isSortingEnabled()
        if sorting_enabled:
            self.external_operator_table.setSortingEnabled(False)
        old_block = self.external_operator_table.blockSignals(True)
        try:
            self.external_operator_table.setRowCount(0)
            for row_data in rows:
                row = self.external_operator_table.rowCount()
                self.external_operator_table.insertRow(row)
                values = row_data["values"]

                select_item = QTableWidgetItem("")
                select_item.setFlags(
                    Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
                )
                select_item.setCheckState(Qt.Unchecked)
                self.external_operator_table.setItem(row, 0, select_item)

                operator_item = QTableWidgetItem(str(values.get("operator_name", "") or ""))
                operator_item.setData(
                    Qt.UserRole,
                    {
                        "feature_id": row_data.get("feature_id"),
                        "is_new": False,
                        "original": {
                            "operator_name": str(values.get("operator_name", "") or ""),
                            "contact_name": str(values.get("contact_name", "") or ""),
                            "phone": str(values.get("phone", "") or ""),
                            "email": str(values.get("email", "") or ""),
                            "fault_number": str(values.get("fault_number", "") or ""),
                            "validity": str(values.get("validity", "") or ""),
                        },
                    },
                )
                self.external_operator_table.setItem(row, 1, operator_item)
                self.external_operator_table.setItem(
                    row, 2, QTableWidgetItem(str(values.get("contact_name", "") or ""))
                )
                self.external_operator_table.setItem(row, 3, QTableWidgetItem(str(values.get("phone", "") or "")))
                self.external_operator_table.setItem(row, 4, QTableWidgetItem(str(values.get("email", "") or "")))
                self.external_operator_table.setItem(
                    row, 5, QTableWidgetItem(str(values.get("fault_number", "") or ""))
                )
                self.external_operator_table.setItem(
                    row, 6, QTableWidgetItem(str(values.get("validity", "") or ""))
                )
        finally:
            self.external_operator_table.blockSignals(old_block)
            if sorting_enabled:
                self.external_operator_table.setSortingEnabled(True)

        provider_name = context.get("provider_name", "") or "unbekannt"
        mode = "schreibbar" if context["editable"] else "nur lesbar"
        add_mode = "neue Zeilen moeglich" if context.get("addable", False) else "keine neuen Zeilen"
        self.external_operator_hint.setText(
            f"{context['source_name']} ({provider_name}, {mode}, {add_mode}) - {len(rows)} Zeilen geladen."
        )
        self.external_operator_add_to_local_button.setEnabled(True)
        self.external_operator_suggest_missing_button.setEnabled(
            bool(context.get("editable", False) and context.get("addable", False))
        )
        self.external_operator_save_button.setEnabled(bool(context["editable"]))
        self.external_operator_add_row_button.setEnabled(
            bool(context.get("editable", False) and context.get("addable", False))
        )
        self.external_operator_remove_row_button.setEnabled(
            bool(context.get("editable", False) and context.get("deletable", False))
        )
        self._apply_table_text_filter(
            self.external_operator_table,
            self._external_search_text(),
        )

    def _add_selected_external_rows_to_local(self):
        checked_rows = []
        for row_index in range(self.external_operator_table.rowCount()):
            item = self.external_operator_table.item(row_index, 0)
            if item is not None and item.checkState() == Qt.Checked:
                checked_rows.append(row_index)

        if not checked_rows:
            QMessageBox.information(
                self,
                "Betreiberliste",
                "Bitte in der externen Liste mindestens eine Checkbox aktivieren.",
            )
            return

        row_indices = sorted(set(checked_rows))
        added = 0
        source_name = ""
        if isinstance(self._external_operator_context, dict):
            source_name = str(self._external_operator_context.get("source_name", "") or "").strip()
        if not source_name:
            selected_source = self._selected_external_source_entry()
            if selected_source is not None:
                source, source_index = selected_source
                source_name = self._source_display_name(source, source_index)
        if not source_name:
            combo_text = str(self.operator_source_combo.currentText() or "").strip()
            if combo_text.lower().startswith("data:"):
                source_name = combo_text.split(":", 1)[1].strip()
        if not source_name:
            source_name = "Externe Quelle"
        for row_index in row_indices:
            values = [
                source_name,
                self.external_operator_table.item(row_index, 1).text().strip()
                if self.external_operator_table.item(row_index, 1)
                else "",
                self.external_operator_table.item(row_index, 6).text().strip()
                if self.external_operator_table.item(row_index, 6)
                else "",
                "",
                self.external_operator_table.item(row_index, 2).text().strip()
                if self.external_operator_table.item(row_index, 2)
                else "",
                self.external_operator_table.item(row_index, 3).text().strip()
                if self.external_operator_table.item(row_index, 3)
                else "",
                self.external_operator_table.item(row_index, 4).text().strip()
                if self.external_operator_table.item(row_index, 4)
                else "",
                self.external_operator_table.item(row_index, 5).text().strip()
                if self.external_operator_table.item(row_index, 5)
                else "",
                "",
            ]
            if any(values[1:8]):
                self._add_operator_row(values)
                added += 1

        if added <= 0:
            QMessageBox.information(
                self,
                "Betreiberliste",
                "In der Auswahl wurden keine verwertbaren Datensaetze gefunden.",
            )
            return

        local_index = self.operator_source_combo.findData("local")
        if local_index >= 0:
            self.operator_source_combo.setCurrentIndex(local_index)

        QMessageBox.information(
            self,
            "Betreiberliste",
            f"{added} Eintraege zur Projektliste hinzugefuegt.",
        )

    def _add_external_operator_row(self):
        context = self._external_operator_context
        if not isinstance(context, dict):
            QMessageBox.information(
                self,
                "Betreiberliste",
                "Bitte zuerst eine Datenquelle auswaehlen und laden.",
            )
            return

        if not context.get("editable", False):
            QMessageBox.warning(
                self,
                "Betreiberliste",
                "Diese Quelle ist aktuell nur lesbar.",
            )
            return
        if not context.get("addable", False):
            QMessageBox.warning(
                self,
                "Betreiberliste",
                "Diese Quelle unterstuetzt keine neuen Zeilen.",
            )
            return

        row = self._append_external_operator_row()
        self.external_operator_table.setCurrentCell(row, 1)
        self._apply_table_text_filter(
            self.external_operator_table,
            self._external_search_text(),
        )

    def _remove_selected_external_operator_row(self):
        context = self._external_operator_context
        if not isinstance(context, dict):
            QMessageBox.information(
                self,
                "Betreiberliste",
                "Bitte zuerst eine Datenquelle auswaehlen und laden.",
            )
            return

        selected = self.external_operator_table.selectionModel().selectedRows()
        if not selected:
            QMessageBox.information(
                self,
                "Betreiberliste",
                "Bitte zuerst eine Zeile in der externen Liste auswaehlen.",
            )
            return

        row_index = selected[0].row()
        operator_item = self.external_operator_table.item(row_index, 1)
        payload = operator_item.data(Qt.UserRole) if operator_item else None
        if not isinstance(payload, dict):
            payload = {}

        # Noch nicht gespeicherte neue Zeile: nur aus der Tabelle entfernen.
        if payload.get("feature_id") is None:
            self.external_operator_table.removeRow(row_index)
            self._apply_table_text_filter(
                self.external_operator_table,
                self._external_search_text(),
            )
            return

        if not context.get("editable", False) or not context.get("deletable", False):
            QMessageBox.warning(
                self,
                "Betreiberliste",
                "Diese Quelle unterstuetzt kein Loeschen von Zeilen.",
            )
            return

        answer = QMessageBox.question(
            self,
            "Betreiberliste",
            "Ausgewaehlte Zeile in der Quelle wirklich loeschen?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        layer = context.get("layer")
        feature_id = payload.get("feature_id")
        if layer is None or feature_id is None:
            QMessageBox.warning(
                self,
                "Betreiberliste",
                "Zeile konnte nicht geloescht werden (ungueltige Quelle).",
            )
            return

        started_editing = False
        if not layer.isEditable():
            if not layer.startEditing():
                QMessageBox.warning(
                    self,
                    "Betreiberliste",
                    "Quelle konnte nicht in den Bearbeitungsmodus gesetzt werden.",
                )
                return
            started_editing = True

        if not layer.deleteFeature(feature_id):
            if started_editing and layer.isEditable():
                layer.rollBack()
            QMessageBox.warning(
                self,
                "Betreiberliste",
                "Loeschen fehlgeschlagen.",
            )
            return

        if started_editing:
            if not layer.commitChanges():
                errors = []
                if hasattr(layer, "commitErrors"):
                    try:
                        errors = layer.commitErrors()
                    except Exception:
                        errors = []
                if layer.isEditable():
                    layer.rollBack()
                detail = "; ".join(errors) if errors else "Unbekannter Fehler."
                QMessageBox.warning(
                    self,
                    "Betreiberliste",
                    f"Loeschen fehlgeschlagen: {detail}",
                )
                return
            QMessageBox.information(
                self,
                "Betreiberliste",
                "Zeile wurde in der Quelle geloescht.",
            )
        else:
            QMessageBox.information(
                self,
                "Betreiberliste",
                "Zeile wurde geloescht. Bitte die Quelle separat speichern.",
            )

        self.external_operator_table.removeRow(row_index)
        self._apply_table_text_filter(
            self.external_operator_table,
            self._external_search_text(),
        )

    def _save_external_operator_changes(self):
        context = self._external_operator_context
        if not isinstance(context, dict):
            QMessageBox.information(
                self,
                "Betreiberliste",
                "Bitte zuerst eine Datenquelle auswaehlen und laden.",
            )
            return

        if not context.get("editable", False):
            QMessageBox.warning(
                self,
                "Betreiberliste",
                "Diese Quelle unterstuetzt keine Attribut-Aenderungen (nur lesbar).",
            )
            return

        layer = context.get("layer")
        field_indices = context.get("field_indices", {})
        if layer is None:
            QMessageBox.information(self, "Betreiberliste", "Keine Daten zum Speichern vorhanden.")
            return

        started_editing = False
        if not layer.isEditable():
            if not layer.startEditing():
                QMessageBox.warning(
                    self,
                    "Betreiberliste",
                    "Quelle konnte nicht in den Bearbeitungsmodus gesetzt werden.",
                )
                return
            started_editing = True

        def _row_values(row_index: int) -> dict:
            return {
                "operator_name": self.external_operator_table.item(row_index, 1).text().strip()
                if self.external_operator_table.item(row_index, 1)
                else "",
                "contact_name": self.external_operator_table.item(row_index, 2).text().strip()
                if self.external_operator_table.item(row_index, 2)
                else "",
                "phone": self.external_operator_table.item(row_index, 3).text().strip()
                if self.external_operator_table.item(row_index, 3)
                else "",
                "email": self.external_operator_table.item(row_index, 4).text().strip()
                if self.external_operator_table.item(row_index, 4)
                else "",
                "fault_number": self.external_operator_table.item(row_index, 5).text().strip()
                if self.external_operator_table.item(row_index, 5)
                else "",
                "validity": self.external_operator_table.item(row_index, 6).text().strip()
                if self.external_operator_table.item(row_index, 6)
                else "",
            }

        table_columns = [
            ("operator_name", 1),
            ("contact_name", 2),
            ("phone", 3),
            ("email", 4),
            ("fault_number", 5),
            ("validity", 6),
        ]

        pending_new_rows = []
        for row_index in range(self.external_operator_table.rowCount()):
            operator_item = self.external_operator_table.item(row_index, 1)
            payload = operator_item.data(Qt.UserRole) if operator_item else None
            if not isinstance(payload, dict) or payload.get("feature_id") is None:
                values = _row_values(row_index)
                if any(str(v).strip() for v in values.values()):
                    pending_new_rows.append((row_index, values))

        if pending_new_rows and not context.get("addable", False):
            if started_editing:
                layer.rollBack()
            QMessageBox.warning(
                self,
                "Betreiberliste",
                "Diese Quelle unterstuetzt keine neuen Zeilen.",
            )
            return

        missing_name_rows = [str(row_index + 1) for row_index, values in pending_new_rows if not values["operator_name"]]
        if missing_name_rows:
            if started_editing:
                layer.rollBack()
            QMessageBox.warning(
                self,
                "Betreiberliste",
                "Neue Zeilen brauchen einen Betreibername. Betroffene Zeilen: " + ", ".join(missing_name_rows),
            )
            return

        changed_values = 0
        added_rows = 0

        for row_index in range(self.external_operator_table.rowCount()):
            operator_item = self.external_operator_table.item(row_index, 1)
            payload = operator_item.data(Qt.UserRole) if operator_item else None
            values = _row_values(row_index)

            if not isinstance(payload, dict):
                payload = {
                    "feature_id": None,
                    "is_new": True,
                    "original": {
                        "operator_name": "",
                        "contact_name": "",
                        "phone": "",
                        "email": "",
                        "fault_number": "",
                        "validity": "",
                    },
                }

            feature_id = payload.get("feature_id")
            if feature_id is None:
                if not any(str(v).strip() for v in values.values()):
                    continue

                new_feature = QgsFeature(layer.fields())
                attributes = [None] * int(context.get("field_count", len(layer.fields())))
                for key, _ in table_columns:
                    field_idx = int(field_indices.get(key, -1))
                    if field_idx < 0 or field_idx >= len(attributes):
                        continue
                    attributes[field_idx] = values[key]
                new_feature.setAttributes(attributes)
                if layer.addFeature(new_feature):
                    added_rows += 1
                continue

            original = payload.get("original", {}) if isinstance(payload, dict) else {}
            for key, col in table_columns:
                field_idx = int(field_indices.get(key, -1))
                if field_idx < 0:
                    continue
                item = self.external_operator_table.item(row_index, col)
                new_value = item.text().strip() if item else ""
                old_value = str(original.get(key, "") or "")
                if new_value == old_value:
                    continue
                if layer.changeAttributeValue(feature_id, field_idx, new_value):
                    changed_values += 1

        if changed_values == 0 and added_rows == 0:
            if started_editing:
                layer.rollBack()
            QMessageBox.information(self, "Betreiberliste", "Keine Aenderungen zum Speichern gefunden.")
            return

        if started_editing:
            if not layer.commitChanges():
                errors = []
                if hasattr(layer, "commitErrors"):
                    try:
                        errors = layer.commitErrors()
                    except Exception:
                        errors = []
                if layer.isEditable():
                    layer.rollBack()
                detail = "; ".join(errors) if errors else "Unbekannter Fehler."
                QMessageBox.warning(
                    self,
                    "Betreiberliste",
                    f"Speichern fehlgeschlagen: {detail}",
                )
                return
            QMessageBox.information(
                self,
                "Betreiberliste",
                f"{changed_values} Feldwerte aktualisiert, {added_rows} neue Zeilen in '{context['source_name']}' gespeichert.",
            )
        else:
            QMessageBox.information(
                self,
                "Betreiberliste",
                f"{changed_values} Feldwerte aktualisiert, {added_rows} neue Zeilen erstellt. Bitte die Quelle separat speichern.",
            )

        self._reload_selected_external_operator_source()

    def _source_uri_and_provider(self, source: dict) -> tuple[str, str]:
        source_type = str(source.get("source_type", "file") or "file").strip().lower()
        provider = str(source.get("provider", "ogr") or "ogr").strip() or "ogr"
        source_value = self._resolved_source_value(str(source.get("source", "") or "").strip())
        table_value = str(source.get("table", "") or "").strip()

        if source_type == "file":
            uri = source_value
            if uri.startswith("file://"):
                parsed = urllib.parse.urlparse(uri)
                uri = urllib.parse.unquote(parsed.path or "")
            if table_value and provider == "ogr" and "|layername=" not in uri.lower():
                uri = f"{uri}|layername={table_value}"
            return uri, provider

        if table_value and provider == "ogr" and "|layername=" not in source_value.lower():
            return f"{source_value}|layername={table_value}", provider
        return source_value, provider

    def _load_external_source_layer(self, source: dict):
        normalized = _normalize_data_source_entry(source)
        source_type = str(normalized.get("source_type", "file") or "file").strip().lower()
        table_value = str(normalized.get("table", "") or "").strip()
        source_value = self._resolved_source_value(str(normalized.get("source", "") or "").strip())
        if not source_value:
            return None

        provider_token = str(normalized.get("provider", "ogr") or "ogr").strip().lower()
        source_token = str(source_value or "").strip().lower()
        is_pg_like = source_type == "qgis_uri" and (
            source_token.startswith("pg:")
            or "dbname=" in source_token
            or provider_token in ("ogr", "postgres")
        )

        db_parts = {}
        has_pg_connection = False
        schema_hint = ""
        table_hint = table_value
        ogr_base_uri = ""

        if is_pg_like:
            db_parts = self._db_source_parts_from_uri(source_value, table_value)
            host_value = str(db_parts.get("host", "") or "").strip()
            database_value = str(db_parts.get("database", "") or "").strip()
            has_pg_connection = bool(host_value and database_value)
            schema_hint = str(db_parts.get("schema", "") or "").strip()
            table_hint = str(table_value or db_parts.get("table", "") or "").strip()

            if has_pg_connection:
                ogr_base_uri = self._build_postgres_ogr_source_uri(
                    host_value,
                    str(db_parts.get("port", "") or "").strip(),
                    database_value,
                    str(db_parts.get("ssl_mode", "") or "prefer"),
                    schema_hint,
                    str(db_parts.get("username", "") or "").strip(),
                    str(db_parts.get("password", "") or ""),
                )
                if not schema_hint:
                    schema_hint = self._pg_schema_from_uri(ogr_base_uri)
            else:
                schema_hint = self._pg_schema_from_uri(source_value)

            if not table_hint:
                detect_uri = ogr_base_uri or source_value
                auto_table = self._auto_detect_pg_table_for_source(normalized, detect_uri)
                if auto_table:
                    table_hint = auto_table

            if schema_hint and table_hint and "." not in table_hint:
                table_hint = f"{schema_hint}.{table_hint}"

            if table_hint and table_hint != table_value:
                normalized = dict(normalized)
                normalized["table"] = table_hint
                table_value = table_hint

        uri, provider = self._source_uri_and_provider(normalized)
        attempts = [(uri, provider)]

        if source_type == "qgis_uri" and has_pg_connection:
            key_from_source = self._pg_uri_option_value(source_value, "key")
            pku_from_source = self._pg_uri_option_value(source_value, "checkPrimaryKeyUnicity")
            for key_candidate in self._pg_key_candidates(key_from_source):
                postgres_uri = self._build_postgres_provider_source_uri(
                    str(db_parts.get("host", "") or "").strip(),
                    str(db_parts.get("port", "") or "").strip(),
                    str(db_parts.get("database", "") or "").strip(),
                    str(db_parts.get("ssl_mode", "") or "prefer"),
                    schema_hint,
                    table_hint,
                    str(db_parts.get("username", "") or "").strip(),
                    str(db_parts.get("password", "") or ""),
                    key_candidate,
                    pku_from_source,
                )
                attempts.append((postgres_uri, "postgres"))

            layer_candidates = self._pg_layer_name_candidates(table_hint, schema_hint)
            for base_uri in self._pg_ogr_uri_variants(ogr_base_uri):
                for layer_name in layer_candidates:
                    attempts.append((f"{base_uri}|layername={layer_name}", "ogr"))
                attempts.append((base_uri, "ogr"))

        if source_type == "qgis_uri" and not has_pg_connection and provider == "ogr":
            schema_hint = self._pg_schema_from_uri(source_value)
            layer_candidates = self._pg_layer_name_candidates(table_value, schema_hint)
            for base_uri in self._pg_ogr_uri_variants(uri):
                for layer_name in layer_candidates:
                    attempts.append((f"{base_uri}|layername={layer_name}", "ogr"))
                attempts.append((base_uri, "ogr"))

        if source_type == "file" and table_value and provider == "ogr":
            attempts.append((source_value, provider))

        tried = set()
        debug_attempts = []
        for attempt_uri, attempt_provider in attempts:
            uri_key = f"{attempt_provider}::{attempt_uri}"
            if uri_key in tried:
                continue
            tried.add(uri_key)
            if len(debug_attempts) < 20:
                debug_attempts.append(
                    (
                        str(attempt_provider or "").strip(),
                        self._sanitize_source_uri_for_display(str(attempt_uri or "").strip()),
                    )
                )
            ext_layer = QgsVectorLayer(attempt_uri, "attributionbutler_external_source", attempt_provider)
            if ext_layer.isValid():
                self._last_external_load_debug = debug_attempts
                return ext_layer

        self._last_external_load_debug = debug_attempts
        return None

    def _sanitize_source_uri_for_display(self, uri: str) -> str:
        text = str(uri or "").strip()
        if not text:
            return ""
        text = re.sub(r"password\s*=\s*'([^'\\]|\\.)*'", "password='***'", text, flags=re.IGNORECASE)
        text = re.sub(r"password\s*=\s*\"([^\"\\]|\\.)*\"", 'password="***"', text, flags=re.IGNORECASE)
        text = re.sub(r"password\s*=\s*[^\s|]+", "password=***", text, flags=re.IGNORECASE)
        return text

    def _pg_key_candidates(self, preferred_key: str = "") -> list[str]:
        candidates = [str(preferred_key or "").strip(), "tid", "id", "gid", "fid", "pk"]
        result = []
        seen = set()
        for value in candidates:
            key = str(value or "").strip()
            norm = key.lower()
            if norm in seen:
                continue
            seen.add(norm)
            result.append(key)
        return result

    def _pg_layer_name_candidates(self, table_name: str, schema_hint: str = "") -> list[str]:
        token = str(table_name or "").strip()
        schema_token = str(schema_hint or "").strip().strip('"')
        if not token:
            return []

        candidates = []
        for raw in (token, token.replace('"', "")):
            value = str(raw or "").strip()
            if not value:
                continue
            candidates.append(value)
            if "." in value:
                schema_part, table_part = value.split(".", 1)
                schema_part = schema_part.strip().strip('"')
                table_part = table_part.strip().strip('"')
                if table_part:
                    candidates.append(table_part)
                if schema_part and table_part:
                    candidates.append(f"{schema_part}.{table_part}")
                    candidates.append(f'"{schema_part}"."{table_part}"')
            else:
                bare = value.strip().strip('"')
                if bare:
                    if schema_token:
                        candidates.append(f"{schema_token}.{bare}")
                        candidates.append(f'"{schema_token}"."{bare}"')
                    candidates.append(bare)
                    candidates.append(f'"{bare}"')

        unique_candidates = []
        seen = set()
        for candidate in candidates:
            key = str(candidate or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            unique_candidates.append(str(candidate).strip())
        return unique_candidates

    def _pg_uri_option_value(self, source_uri: str, option_name: str) -> str:
        option = re.escape(str(option_name or "").strip())
        if not option:
            return ""
        match = re.search(
            rf"(?:^|\s){option}\s*=\s*(?:'((?:[^'\\\\]|\\\\.)*)'|\"((?:[^\"\\\\]|\\\\.)*)\"|([^\s]+))",
            str(source_uri or ""),
            flags=re.IGNORECASE,
        )
        if not match:
            return ""
        raw_value = ""
        for group in match.groups():
            if group is not None:
                raw_value = str(group)
                break
        return (
            raw_value.replace("\\'", "'")
            .replace('\\"', '"')
            .replace("\\\\", "\\")
            .strip()
            .strip('"')
            .strip("'")
        )

    def _pg_schema_table_from_source_uri(self, source_uri: str) -> tuple[str, str]:
        text = str(source_uri or "")
        if not text:
            return "", ""

        quoted_match = re.search(
            r'table\s*=\s*"([^"]+)"\s*\.\s*"([^"]+)"',
            text,
            flags=re.IGNORECASE,
        )
        if quoted_match:
            return (
                str(quoted_match.group(1) or "").strip(),
                str(quoted_match.group(2) or "").strip(),
            )

        generic_match = re.search(
            r"table\s*=\s*(?:'([^']+)'|\"([^\"]+)\"|([^\s]+))",
            text,
            flags=re.IGNORECASE,
        )
        if not generic_match:
            return "", ""

        raw_value = ""
        for group in generic_match.groups():
            if group is not None:
                raw_value = str(group).strip()
                break
        raw_value = raw_value.strip().strip('"').strip("'")
        raw_value = raw_value.replace('"', "")
        if not raw_value:
            return "", ""
        if "." in raw_value:
            schema_name, table_name = raw_value.split(".", 1)
            return schema_name.strip(), table_name.strip()
        return "", raw_value.strip()

    def _pg_schema_from_uri(self, source_uri: str) -> str:
        active_schema = self._pg_uri_option_value(source_uri, "active_schema").strip().strip('"')
        if active_schema:
            return active_schema
        schemas = self._pg_uri_option_value(source_uri, "schemas")
        if schemas:
            first = str(schemas).split(",", 1)[0].strip().strip('"')
            if first:
                return first
        schema_from_table, _table_from_uri = self._pg_schema_table_from_source_uri(source_uri)
        return str(schema_from_table or "").strip()

    def _schema_qualified_layer_name(self, layer_name: str, schema_hint: str = "") -> str:
        token = str(layer_name or "").strip()
        if not token:
            return ""

        normalized = token.replace('"', "").strip()
        if not normalized:
            return ""

        schema_token = str(schema_hint or "").strip().strip('"')
        if "." in normalized:
            schema_part, table_part = normalized.split(".", 1)
            schema_part = schema_part.strip()
            table_part = table_part.strip()
            if not table_part:
                return ""
            return f"{schema_part}.{table_part}" if schema_part else table_part

        if schema_token:
            return f"{schema_token}.{normalized}"
        return normalized

    def _layer_matches_operator_name(self, layer, configured_operator_name: str) -> bool:
        aliases = ["operator_name", "betreibername", "betreiber", "name"]
        if self._layer_uses_generic_fields(layer):
            header_tokens = self._header_tokens_from_first_feature(layer)
            if not header_tokens:
                return False
            idx = self._resolve_column_index(header_tokens, configured_operator_name, aliases)
            if idx >= 0:
                return True
            return bool(header_tokens)

        field_name = self._resolve_field_name_in_layer(layer, configured_operator_name, aliases)
        return bool(field_name)

    def _load_pg_layer_by_name(
        self,
        source_uri: str,
        layer_name: str,
        schema_hint: str = "",
        strict_schema: bool = False,
    ):
        base_uri = re.sub(r"\|layername=.*$", "", str(source_uri or ""), flags=re.IGNORECASE).strip()
        target = str(layer_name or "").strip()
        if not base_uri or not target:
            return None

        schema_token = str(schema_hint or "").strip().strip('"')
        normalized_target = target.replace('"', "").strip()
        explicit_schema = ""
        table_name = normalized_target
        if "." in normalized_target:
            explicit_schema, table_name = normalized_target.split(".", 1)
            explicit_schema = explicit_schema.strip()
            table_name = table_name.strip()

        effective_schema = explicit_schema or schema_token
        candidates = []
        if effective_schema and table_name:
            candidates.append(f"{effective_schema}.{table_name}")
            candidates.append(f'"{effective_schema}"."{table_name}"')

        if not strict_schema:
            for token in (target, normalized_target):
                value = str(token or "").strip()
                if not value:
                    continue
                candidates.append(value)
                if "." in value:
                    _, table_part = value.split(".", 1)
                    table_part = table_part.strip().strip('"')
                    if table_part:
                        candidates.append(table_part)
                else:
                    bare = value.strip().strip('"')
                    if bare:
                        candidates.append(bare)
                        candidates.append(f'"{bare}"')

        unique_candidates = []
        seen = set()
        for candidate in candidates:
            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            unique_candidates.append(candidate)

        for variant in self._pg_ogr_uri_variants(base_uri):
            for candidate in unique_candidates:
                layer = QgsVectorLayer(
                    f"{variant}|layername={candidate}",
                    "attributionbutler_external_source",
                    "ogr",
                )
                if layer.isValid():
                    return layer
        return None

    def _auto_detect_pg_table_for_source(self, source: dict, source_uri: str) -> str:
        base_uri = re.sub(r"\|layername=.*$", "", str(source_uri or ""), flags=re.IGNORECASE).strip()
        if not base_uri:
            return ""

        configured_operator_name = (
            str(source.get("operator_name_field", "") or "").strip()
            or self._combo_text(self.operator_name_field)
            or str(DEFAULT_CONFIG.get("operator_name_field_name", "") or "")
        )
        cache_key = f"{base_uri}::{configured_operator_name}".lower()
        cached = str(self._auto_pg_table_cache.get(cache_key, "") or "").strip()
        if cached:
            return cached

        schema_hint = self._pg_schema_from_uri(base_uri)
        layer_names = self._list_pg_layers_via_ogr(base_uri, schema_hint)
        if not layer_names:
            return ""

        normalized_names = []
        seen = set()
        schema_token = str(schema_hint or "").strip().lower()
        for raw_name in layer_names:
            qualified_name = self._schema_qualified_layer_name(raw_name, schema_hint)
            if not qualified_name:
                continue
            if schema_token and "." in qualified_name:
                schema_name = qualified_name.split(".", 1)[0].strip().lower()
                if schema_name and schema_name != schema_token:
                    continue
            key = qualified_name.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized_names.append(qualified_name)

        if not normalized_names:
            return ""

        def _table_priority(name: str) -> int:
            token = str(name or "").replace('"', "").strip().lower()
            schema_token = str(schema_hint or "").strip().lower()
            table_token = token.split(".", 1)[1] if "." in token else token
            score = 0
            if schema_token:
                if token.startswith(f"{schema_token}."):
                    score += 1000
                else:
                    score -= 1000
            if table_token == "betreiber":
                score += 300
            if "betreiber" in table_token:
                score += 200
            if "operator" in table_token:
                score += 80
            if "liste" in table_token:
                score += 40
            if "backup" in table_token or "archiv" in table_token:
                score -= 80
            return score

        ordered_names = sorted(
            normalized_names,
            key=lambda value: (-_table_priority(value), str(value or "").lower()),
        )

        fallback = str(ordered_names[0] or "").strip()
        for layer_name in ordered_names:
            layer = self._load_pg_layer_by_name(
                base_uri,
                layer_name,
                schema_hint=schema_hint,
                strict_schema=bool(schema_hint),
            )
            if layer is None:
                continue
            if self._layer_matches_operator_name(layer, configured_operator_name):
                picked = str(layer_name or "").strip()
                if picked:
                    self._auto_pg_table_cache[cache_key] = picked
                    return picked

        if fallback:
            self._auto_pg_table_cache[cache_key] = fallback
        return fallback

    def _pg_ogr_uri_variants(self, source_uri: str) -> list[str]:
        base_uri = re.sub(r"\|layername=.*$", "", str(source_uri or ""), flags=re.IGNORECASE).strip()
        if not base_uri:
            return []

        candidates = [base_uri]
        option_groups = [
            ["active_schema"],
            ["schemas"],
            ["active_schema", "schemas"],
        ]
        for options in option_groups:
            candidate = base_uri
            for option_name in options:
                candidate = re.sub(
                    rf"\s+{option_name}\s*=\s*'([^'\\\\]|\\\\.)*'",
                    "",
                    candidate,
                    flags=re.IGNORECASE,
                )
            candidate = re.sub(r"\s+", " ", candidate).strip()
            if candidate:
                candidates.append(candidate)

        unique = []
        seen = set()
        for candidate in candidates:
            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)
        return unique

    def _resolve_field_name_in_layer(self, layer, configured_name: str, aliases: list[str]) -> str:
        field_names = [field.name() for field in layer.fields()]
        lowered = {name.lower(): name for name in field_names}
        normalized = {self._normalize_field_token(name): name for name in field_names}

        token = str(configured_name or "").strip()
        if token:
            if token in field_names:
                return token
            if token.lower() in lowered:
                return lowered[token.lower()]
            norm_token = self._normalize_field_token(token)
            if norm_token in normalized:
                return normalized[norm_token]
            for field_name in field_names:
                norm_field = self._normalize_field_token(field_name)
                if norm_token and (norm_token in norm_field or norm_field in norm_token):
                    return field_name

        for alias in aliases:
            alias_token = str(alias or "").strip().lower()
            if alias_token and alias_token in lowered:
                return lowered[alias_token]
            norm_alias = self._normalize_field_token(alias)
            if norm_alias and norm_alias in normalized:
                return normalized[norm_alias]
            for field_name in field_names:
                norm_field = self._normalize_field_token(field_name)
                if norm_alias and (norm_alias in norm_field or norm_field in norm_alias):
                    return field_name

        return ""

    def _normalize_field_token(self, value: str) -> str:
        token = str(value or "").strip().lower()
        token = (
            token.replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
        )
        return "".join(ch for ch in token if ch.isalnum())

    def _is_generic_field_name(self, value: str) -> bool:
        return bool(re.fullmatch(r"field\d+", str(value or "").strip().lower()))

    def _layer_uses_generic_fields(self, layer) -> bool:
        names = [field.name() for field in layer.fields()]
        return bool(names) and all(self._is_generic_field_name(name) for name in names)

    def _header_tokens_from_first_feature(self, layer) -> list[str]:
        for feature in layer.getFeatures():
            return [str(value or "").strip() for value in feature.attributes()]
        return []

    def _resolve_column_index(self, header_tokens: list[str], configured_name: str, aliases: list[str]) -> int:
        normalized = {}
        lowered = {}
        for idx, token in enumerate(header_tokens):
            text = str(token or "").strip()
            if not text:
                continue
            lowered[text.lower()] = idx
            norm_token = self._normalize_field_token(text)
            if norm_token and norm_token not in normalized:
                normalized[norm_token] = idx

        value = str(configured_name or "").strip()
        if value:
            if value.lower() in lowered:
                return lowered[value.lower()]
            norm_value = self._normalize_field_token(value)
            if norm_value in normalized:
                return normalized[norm_value]
            for idx, token in enumerate(header_tokens):
                norm_token = self._normalize_field_token(token)
                if norm_value and (norm_value in norm_token or norm_token in norm_value):
                    return idx

        for alias in aliases:
            alias_text = str(alias or "").strip()
            if not alias_text:
                continue
            if alias_text.lower() in lowered:
                return lowered[alias_text.lower()]
            norm_alias = self._normalize_field_token(alias_text)
            if norm_alias in normalized:
                return normalized[norm_alias]
            for idx, token in enumerate(header_tokens):
                norm_token = self._normalize_field_token(token)
                if norm_alias and (norm_alias in norm_token or norm_token in norm_alias):
                    return idx
        return -1

    def _token_by_column_index(self, header_tokens: list[str], idx: int) -> str:
        if idx < 0 or idx >= len(header_tokens):
            return ""
        return str(header_tokens[idx] or "").strip()

    def _safe_attribute_by_index(self, feature, idx: int):
        if idx < 0:
            return ""
        attrs = feature.attributes()
        if idx >= len(attrs):
            return ""
        return attrs[idx]

    def _operator_entries_from_external_source(self, source: dict) -> list[dict]:
        normalized_source = _normalize_data_source_entry(source)
        if not _to_bool(normalized_source.get("enabled", True), True):
            return []

        layer = self._load_external_source_layer(normalized_source)
        if layer is None:
            return []

        fallback_name = (
            str(normalized_source.get("operator_name_field", "") or "").strip()
            or self._combo_text(self.operator_name_field)
            or str(DEFAULT_CONFIG.get("operator_name_field_name", "") or "")
        )
        fallback_contact = (
            str(normalized_source.get("contact_name_field", "") or "").strip()
            or self._combo_text(self.operator_contact_field)
            or str(DEFAULT_CONFIG.get("operator_contact_field_name", "") or "")
        )
        fallback_phone = (
            str(normalized_source.get("phone_field", "") or "").strip()
            or self._combo_text(self.operator_phone_field)
            or str(DEFAULT_CONFIG.get("operator_phone_field_name", "") or "")
        )
        fallback_email = (
            str(normalized_source.get("email_field", "") or "").strip()
            or self._combo_text(self.operator_email_field)
            or str(DEFAULT_CONFIG.get("operator_email_field_name", "") or "")
        )
        fallback_fault = (
            str(normalized_source.get("fault_number_field", "") or "").strip()
            or self._combo_text(self.operator_fault_field)
            or str(DEFAULT_CONFIG.get("operator_fault_field_name", "") or "")
        )
        fallback_validity = (
            self._combo_text(self.operator_validity_field)
            or str(DEFAULT_CONFIG.get("operator_validity_field_name", "") or "")
        )
        fallback_stand = (
            self._combo_text(self.operator_stand_field)
            or str(DEFAULT_CONFIG.get("operator_stand_field_name", "") or "")
        )

        generic_fields = self._layer_uses_generic_fields(layer)
        header_tokens = self._header_tokens_from_first_feature(layer) if generic_fields else []

        if generic_fields and header_tokens:
            name_col = self._resolve_column_index(
                header_tokens,
                fallback_name,
                ["operator_name", "betreibername", "betreiber", "name"],
            )
            if name_col < 0 and header_tokens:
                name_col = 0
            if name_col < 0:
                return []

            contact_col = self._resolve_column_index(
                header_tokens,
                fallback_contact,
                ["contact_name", "ansprechpartner", "kontakt", "kontaktperson", "betr_anspr"],
            )
            phone_col = self._resolve_column_index(
                header_tokens,
                fallback_phone,
                ["phone", "telefon", "telefonnummer", "betr_tel", "tel"],
            )
            email_col = self._resolve_column_index(
                header_tokens,
                fallback_email,
                ["email", "mail", "e-mail", "e_mail", "betr_email"],
            )
            fault_col = self._resolve_column_index(
                header_tokens,
                fallback_fault,
                ["fault_number", "stoernummer", "stoernr", "stornummer", "betr_stoer", "stoer_nr", "stoernr"],
            )
            validity_col = self._resolve_column_index(
                header_tokens,
                fallback_validity,
                ["validity", "gueltigkeit", "gültigkeit", "gueltigk", "gültigk"],
            )
            stand_col = self._resolve_column_index(
                header_tokens,
                fallback_stand,
                ["stand", "stand_datum", "statusdatum"],
            )
        else:
            name_field = self._resolve_field_name_in_layer(
                layer,
                fallback_name,
                ["operator_name", "betreibername", "betreiber", "name"],
            )
            if not name_field and layer.fields():
                name_field = layer.fields()[0].name()
            if not name_field:
                return []

            contact_field = self._resolve_field_name_in_layer(
                layer,
                fallback_contact,
                ["contact_name", "ansprechpartner", "kontakt", "kontaktperson", "betr_anspr"],
            )
            phone_field = self._resolve_field_name_in_layer(
                layer,
                fallback_phone,
                ["phone", "telefon", "telefonnummer", "betr_tel", "tel"],
            )
            email_field = self._resolve_field_name_in_layer(
                layer,
                fallback_email,
                ["email", "mail", "e-mail", "e_mail", "betr_email"],
            )
            fault_field = self._resolve_field_name_in_layer(
                layer,
                fallback_fault,
                ["fault_number", "stoernummer", "stoernr", "stornummer", "betr_stoer", "stoer_nr", "stoernr"],
            )
            validity_field = self._resolve_field_name_in_layer(
                layer,
                fallback_validity,
                ["validity", "gueltigkeit", "gültigkeit", "gueltigk", "gültigk"],
            )
            stand_field = self._resolve_field_name_in_layer(
                layer,
                fallback_stand,
                ["stand", "stand_datum", "statusdatum"],
            )

        source_name = self._source_display_name(normalized_source)

        entries = []
        for idx, feature in enumerate(layer.getFeatures()):
            if idx >= 50000:
                break

            if generic_fields and idx == 0:
                # Erste Zeile enthaelt die Headernamen.
                continue

            entry = _normalize_operator_entry(
                {
                    "operator_name": self._safe_attribute_by_index(feature, name_col)
                    if generic_fields
                    else (feature[name_field] if name_field else ""),
                    "contact_name": self._safe_attribute_by_index(feature, contact_col)
                    if generic_fields
                    else (feature[contact_field] if contact_field else ""),
                    "phone": self._safe_attribute_by_index(feature, phone_col)
                    if generic_fields
                    else (feature[phone_field] if phone_field else ""),
                    "email": self._safe_attribute_by_index(feature, email_col)
                    if generic_fields
                    else (feature[email_field] if email_field else ""),
                    "fault_number": self._safe_attribute_by_index(feature, fault_col)
                    if generic_fields
                    else (feature[fault_field] if fault_field else ""),
                    "validity": self._safe_attribute_by_index(feature, validity_col)
                    if generic_fields
                    else (feature[validity_field] if validity_field else ""),
                    "stand": self._safe_attribute_by_index(feature, stand_col)
                    if generic_fields
                    else (feature[stand_field] if stand_field else ""),
                    "folder_path": "",
                }
            )
            if entry.get("operator_name"):
                entry["_source_name"] = source_name
                entries.append(entry)
        return entries

    def _all_external_operator_entries(self) -> list[dict]:
        result = []
        for source in self._data_sources():
            result.extend(self._operator_entries_from_external_source(source))
        return result

    def _prompt_pick_external_operator(self, entries: list[dict]):
        dialog = QDialog(self)
        dialog.setWindowTitle("Betreiber aus Datenquelle uebernehmen")
        dialog.resize(760, 460)

        layout = QVBoxLayout(dialog)
        search = QLineEdit()
        search.setPlaceholderText("Suche nach Betreibername ...")
        layout.addWidget(search)

        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(
            [
                "Betreibername",
                "Ansprechpartner",
                "Telefonnummer",
                "E-Mail",
                "Stoernummer",
                "Quelle",
            ]
        )
        self._configure_standard_table(table, editable=False, sortable=False)
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        header.setSectionResizeMode(4, QHeaderView.Interactive)
        header.setSectionResizeMode(5, QHeaderView.Interactive)
        header.resizeSection(0, 180)
        header.resizeSection(1, 180)
        header.resizeSection(2, 150)
        header.resizeSection(3, 220)
        header.resizeSection(4, 150)
        header.resizeSection(5, 160)
        layout.addWidget(table, 1)

        for entry in entries:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(str(entry.get("operator_name", "") or "")))
            table.setItem(row, 1, QTableWidgetItem(str(entry.get("contact_name", "") or "")))
            table.setItem(row, 2, QTableWidgetItem(str(entry.get("phone", "") or "")))
            table.setItem(row, 3, QTableWidgetItem(str(entry.get("email", "") or "")))
            table.setItem(row, 4, QTableWidgetItem(str(entry.get("fault_number", "") or "")))
            table.setItem(row, 5, QTableWidgetItem(str(entry.get("_source_name", "") or "")))
            table.item(row, 0).setData(Qt.UserRole, entry)

        def apply_filter():
            token = search.text().strip().lower()
            for row in range(table.rowCount()):
                row_text = " | ".join(
                    table.item(row, col).text().lower() if table.item(row, col) else ""
                    for col in range(table.columnCount())
                )
                table.setRowHidden(row, bool(token) and token not in row_text)

        search.textChanged.connect(lambda _: apply_filter())
        apply_filter()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return None
        selected = table.selectionModel().selectedRows()
        if not selected:
            QMessageBox.warning(dialog, "Betreiber", "Bitte einen Betreiber auswaehlen.")
            return None
        item = table.item(selected[0].row(), 0)
        return item.data(Qt.UserRole) if item else None

    def _add_operator_from_data_dialog(self):
        entries = self._all_external_operator_entries()
        if not entries:
            QMessageBox.information(
                self,
                "Betreiber",
                "Keine Betreiberdaten aus verbundenen Datenquellen gefunden.",
            )
            return

        picked = self._prompt_pick_external_operator(entries)
        if not isinstance(picked, dict):
            return
        self._add_operator_row(
            [
                str(
                    picked.get("source_name", picked.get("_source_name", picked.get("data_source", "")))
                    or ""
                ),
                str(picked.get("operator_name", "") or ""),
                str(
                    picked.get(
                        "validity",
                        picked.get(
                            "gueltigkeit",
                            picked.get("gültigkeit", picked.get("gueltigk", picked.get("gültigk", ""))),
                        ),
                    )
                    or ""
                ),
                str(picked.get("stand", picked.get("operator_stand", picked.get("stand_datum", ""))) or ""),
                str(picked.get("contact_name", "") or ""),
                str(picked.get("phone", "") or ""),
                str(picked.get("email", "") or ""),
                str(picked.get("fault_number", "") or ""),
                "",
            ]
        )

    def _make_data_source_type_combo(self, source_type: str = "file") -> QComboBox:
        combo = QComboBox()
        combo.addItem("Datei / Excel", "file")
        combo.addItem("QGIS URI / SQL", "qgis_uri")
        idx = combo.findData(source_type)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        return combo

    def _make_data_provider_combo(self, provider: str = "ogr") -> QComboBox:
        combo = QComboBox()
        for value in ["ogr", "postgres", "spatialite", "mssql", "oracle"]:
            combo.addItem(value)
        idx = combo.findText(str(provider or "ogr"))
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        return combo

    def _create_data_source_table(self, source_type: str = "file") -> QTableWidget:
        is_db = source_type == "qgis_uri"
        if is_db:
            table = QTableWidget(0, 17)
            table.setHorizontalHeaderLabels(
                [
                    "Aktiv",
                    "Name",
                    "Provider",
                    "Host",
                    "Port",
                    "Datenbank",
                    "Benutzername",
                    "Passwort",
                    "SSL-Modus",
                    "Schema",
                    "Tabelle / Layer",
                    "Quelle / URI",
                    "Spalte Betreibername",
                    "Spalte Ansprechpartner",
                    "Spalte Telefonnummer",
                    "Spalte E-Mail",
                    "Spalte Stoernummer",
                ]
            )
        else:
            table = QTableWidget(0, 10)
            table.setHorizontalHeaderLabels(
                [
                    "Aktiv",
                    "Name",
                    "Provider",
                    "Quelle / URI",
                    "Tabelle / Blatt",
                    "Spalte Betreibername",
                    "Spalte Ansprechpartner",
                    "Spalte Telefonnummer",
                    "Spalte E-Mail",
                    "Spalte Stoernummer",
                ]
            )
        self._configure_standard_table(table)
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(100 if is_db else 120)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if is_db:
            for col_idx in range(17):
                header.setSectionResizeMode(col_idx, QHeaderView.Interactive)
            header.resizeSection(0, 70)
            header.resizeSection(1, 150)
            header.resizeSection(2, 90)
            header.resizeSection(3, 180)
            header.resizeSection(4, 85)
            header.resizeSection(5, 120)
            header.resizeSection(6, 120)
            header.resizeSection(7, 120)
            header.resizeSection(8, 100)
            header.resizeSection(9, 120)
            header.resizeSection(10, 170)
            header.resizeSection(11, 320)
            header.resizeSection(12, 190)
            header.resizeSection(13, 200)
            header.resizeSection(14, 190)
            header.resizeSection(15, 180)
            header.resizeSection(16, 190)
        else:
            for col_idx in range(10):
                header.setSectionResizeMode(col_idx, QHeaderView.Interactive)
            header.resizeSection(0, 80)
            header.resizeSection(1, 160)
            header.resizeSection(2, 120)
            header.resizeSection(3, 320)
            header.resizeSection(4, 180)
            header.resizeSection(5, 190)
            header.resizeSection(6, 200)
            header.resizeSection(7, 190)
            header.resizeSection(8, 180)
            header.resizeSection(9, 190)
        header.setTextElideMode(Qt.ElideNone)
        return table

    def _db_source_parts_from_uri(self, source_uri: str, table_value: str = "") -> dict:
        source_text = str(source_uri or "").strip()
        table_text = str(table_value or "").strip()
        parsed_schema, parsed_table = self._pg_schema_table_from_source_uri(source_text)

        schema_from_table = ""
        if "." in table_text:
            schema_from_table = table_text.split(".", 1)[0].strip().strip('"')

        parts = {
            "host": "",
            "port": "",
            "database": "",
            "username": "",
            "password": "",
            "ssl_mode": "",
            "schema": "",
            "table": table_text,
            "source": source_text,
        }
        if not source_text:
            parts["schema"] = schema_from_table
            if not parts["table"] and parsed_table:
                parts["table"] = (
                    f"{parsed_schema}.{parsed_table}" if parsed_schema else parsed_table
                )
            return parts

        parts["host"] = self._pg_uri_option_value(source_text, "host")
        parts["port"] = self._pg_uri_option_value(source_text, "port")
        parts["database"] = self._pg_uri_option_value(source_text, "dbname")
        parts["username"] = self._pg_uri_option_value(source_text, "user")
        parts["password"] = self._pg_uri_option_value(source_text, "password")
        parts["ssl_mode"] = self._pg_uri_option_value(source_text, "sslmode")
        parts["schema"] = self._pg_uri_option_value(source_text, "active_schema")
        if not parts["schema"]:
            schemas = self._pg_uri_option_value(source_text, "schemas")
            if schemas:
                parts["schema"] = str(schemas).split(",", 1)[0].strip().strip('"')
        if not parts["schema"] and parsed_schema:
            parts["schema"] = parsed_schema
        if not parts["schema"] and schema_from_table:
            parts["schema"] = schema_from_table
        if not parts["table"] and parsed_table:
            parts["table"] = f"{parsed_schema}.{parsed_table}" if parsed_schema else parsed_table
        return parts

    def _source_label_from_path(self, source_value: str) -> str:
        value = str(source_value or "").strip()
        if value.startswith("file://"):
            parsed = urllib.parse.urlparse(value)
            value = urllib.parse.unquote(parsed.path or "")
        base = os.path.basename(value)
        stem, _ = os.path.splitext(base)
        return stem or base

    def _resolved_source_value(self, source_value: str) -> str:
        roots = self._global_nextcloud_roots()
        return _expand_local_root_placeholder(source_value, roots)

    def _build_postgres_ogr_source_uri(
        self,
        host: str,
        port: str,
        database: str,
        ssl_mode: str,
        schema: str,
        username: str = "",
        password: str = "",
    ) -> str:
        def _quote_pg_value(raw_value: str) -> str:
            text = str(raw_value or "")
            text = text.replace("\\", "\\\\").replace("'", "\\'")
            return f"'{text}'"

        host_value = str(host or "").strip()
        port_value = str(port or "").strip() or "5432"
        database_value = str(database or "").strip()
        ssl_value = str(ssl_mode or "").strip() or "prefer"
        schema_value = str(schema or "").strip()
        user_value = str(username or "").strip()
        pass_value = str(password or "")

        parts = [
            f"host={_quote_pg_value(host_value)}",
            f"port={_quote_pg_value(port_value)}",
            f"dbname={_quote_pg_value(database_value)}",
            f"sslmode={_quote_pg_value(ssl_value)}",
        ]
        if user_value:
            parts.append(f"user={_quote_pg_value(user_value)}")
        if pass_value:
            parts.append(f"password={_quote_pg_value(pass_value)}")
        if schema_value:
            parts.append(f"schemas={_quote_pg_value(schema_value)}")
            parts.append(f"active_schema={_quote_pg_value(schema_value)}")
        return "PG:" + " ".join(parts)

    def _build_postgres_provider_source_uri(
        self,
        host: str,
        port: str,
        database: str,
        ssl_mode: str,
        schema: str,
        table: str = "",
        username: str = "",
        password: str = "",
        key: str = "",
        check_primary_key_unicity: str = "",
    ) -> str:
        def _quote_conn_value(raw_value: str) -> str:
            text = str(raw_value or "")
            text = text.replace("\\", "\\\\").replace("'", "\\'")
            return f"'{text}'"

        def _quote_identifier(raw_value: str) -> str:
            return str(raw_value or "").replace('"', '""')

        host_value = str(host or "").strip()
        port_value = str(port or "").strip() or "5432"
        database_value = str(database or "").strip()
        ssl_value = str(ssl_mode or "").strip() or "prefer"
        schema_value = str(schema or "").strip().strip('"')
        user_value = str(username or "").strip()
        pass_value = str(password or "")
        key_value = str(key or "").strip()
        pk_unicity_value = str(check_primary_key_unicity or "").strip()

        parts = [
            f"dbname={_quote_conn_value(database_value)}",
            f"host={_quote_conn_value(host_value)}",
            f"port={_quote_conn_value(port_value)}",
            f"sslmode={_quote_conn_value(ssl_value)}",
        ]
        if user_value:
            parts.append(f"user={_quote_conn_value(user_value)}")
        if pass_value:
            parts.append(f"password={_quote_conn_value(pass_value)}")

        table_token = self._schema_qualified_layer_name(table, schema_value)
        if table_token:
            if "." in table_token:
                schema_part, table_part = table_token.split(".", 1)
                schema_part = schema_part.strip().strip('"')
                table_part = table_part.strip().strip('"')
                if schema_part and table_part:
                    parts.append(
                        f'table="{_quote_identifier(schema_part)}"."{_quote_identifier(table_part)}"'
                    )
                elif table_part:
                    parts.append(f'table="{_quote_identifier(table_part)}"')
            else:
                clean_table = table_token.strip().strip('"')
                parts.append(f'table="{_quote_identifier(clean_table)}"')

        if key_value:
            parts.append(f"key={_quote_conn_value(key_value)}")
        if pk_unicity_value:
            parts.append(f"checkPrimaryKeyUnicity={_quote_conn_value(pk_unicity_value)}")

        return " ".join(parts)

    def _list_pg_layers_via_ogr(self, source_uri: str, schema: str = "") -> list[str]:
        connection_string = str(source_uri or "").strip()
        if not connection_string:
            return []
        if "|" in connection_string:
            connection_string = connection_string.split("|", 1)[0].strip()
        if not connection_string:
            return []

        try:
            from osgeo import ogr
        except Exception:
            return []

        schema_token = str(schema or "").strip().strip('"').lower()
        names = []
        seen = set()

        def _append_name(raw_name):
            name = str(raw_name or "").strip()
            if not name:
                return
            normalized = name.replace('"', "")
            if schema_token and "." in normalized:
                schema_name = normalized.split(".", 1)[0].strip().lower()
                if schema_name and schema_name != schema_token:
                    return
            key = normalized.lower()
            if key in seen:
                return
            seen.add(key)
            names.append(name)

        variants = self._pg_ogr_uri_variants(connection_string) or [connection_string]
        for variant in variants:
            datasource = None
            try:
                open_ex = getattr(ogr, "OpenEx", None)
                if callable(open_ex):
                    try:
                        datasource = open_ex(
                            variant,
                            0,
                            open_options=["LIST_ALL_TABLES=YES", "SKIP_VIEWS=NO"],
                        )
                    except Exception:
                        datasource = None
                if datasource is None:
                    datasource = ogr.Open(variant, 0)
                if datasource is None:
                    continue

                for idx in range(int(datasource.GetLayerCount())):
                    layer = datasource.GetLayerByIndex(idx)
                    if layer is None:
                        continue
                    _append_name(layer.GetName())

                if names:
                    continue

                for table_name in self._list_pg_tables_via_sql(datasource, schema_token):
                    _append_name(table_name)
            except Exception:
                continue
            finally:
                datasource = None

        return sorted(names, key=lambda value: value.lower())

    def _list_pg_tables_via_sql(self, datasource, schema_token: str = "") -> list[str]:
        if datasource is None:
            return []

        schema_value = str(schema_token or "").strip().strip('"')
        escaped_schema = schema_value.replace("'", "''")
        if schema_value:
            schema_filter = f"LOWER(table_schema) = LOWER('{escaped_schema}')"
            namespace_filter = f"LOWER(n.nspname) = LOWER('{escaped_schema}')"
        else:
            schema_filter = "table_schema NOT IN ('pg_catalog', 'information_schema')"
            namespace_filter = "n.nspname NOT IN ('pg_catalog', 'information_schema')"

        queries = [
            (
                "SELECT table_schema, table_name "
                "FROM information_schema.tables "
                f"WHERE {schema_filter} "
                "AND table_type IN ('BASE TABLE', 'VIEW', 'FOREIGN TABLE') "
                "ORDER BY table_schema, table_name"
            ),
            (
                "SELECT n.nspname AS table_schema, c.relname AS table_name "
                "FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                f"WHERE {namespace_filter} "
                "AND c.relkind IN ('r', 'v', 'm', 'f', 'p') "
                "ORDER BY n.nspname, c.relname"
            ),
        ]

        names = []
        seen = set()
        for query in queries:
            result_set = None
            try:
                result_set = datasource.ExecuteSQL(query)
            except Exception:
                result_set = None
            if result_set is None:
                continue

            try:
                feature = result_set.GetNextFeature()
                while feature is not None:
                    schema_name = ""
                    table_name = ""

                    for field_name in ("table_schema", "TABLE_SCHEMA", "schema", "SCHEMA", "nspname"):
                        field_idx = feature.GetFieldIndex(field_name)
                        if field_idx >= 0:
                            schema_name = str(feature.GetField(field_idx) or "").strip().strip('"')
                            if schema_name:
                                break
                    for field_name in ("table_name", "TABLE_NAME", "name", "NAME", "relname"):
                        field_idx = feature.GetFieldIndex(field_name)
                        if field_idx >= 0:
                            table_name = str(feature.GetField(field_idx) or "").strip().strip('"')
                            if table_name:
                                break

                    if table_name:
                        if schema_name:
                            candidate = f"{schema_name}.{table_name}"
                        else:
                            candidate = table_name
                        key = candidate.replace('"', "").lower()
                        if key not in seen:
                            seen.add(key)
                            names.append(candidate)

                    feature = result_set.GetNextFeature()
            finally:
                try:
                    datasource.ReleaseResultSet(result_set)
                except Exception:
                    pass

            if names:
                break

        return names

    def _pick_db_layer_name(self, layer_names: list[str]) -> str:
        candidates = [str(name or "").strip() for name in layer_names if str(name or "").strip()]
        if not candidates:
            return ""
        if len(candidates) == 1:
            return candidates[0]

        value, accepted = QInputDialog.getItem(
            self,
            "Datenbankquelle",
            "Tabelle / Layer auswaehlen:",
            candidates,
            0,
            False,
        )
        if not accepted:
            return ""
        return str(value or "").strip()

    def _choose_file_for_line_edit(self, line_edit: QLineEdit, name_line_edit: QLineEdit | None = None):
        start_dir = ""
        current_text = line_edit.text().strip()
        if current_text:
            if os.path.isdir(current_text):
                start_dir = current_text
            else:
                start_dir = os.path.dirname(current_text)
        else:
            roots = self._global_nextcloud_roots()
            if roots:
                start_dir = roots[0]

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Datenquelle waehlen",
            start_dir,
            "Unterstuetzte Dateien (*.xlsx *.xls *.csv *.ods *.sqlite *.gpkg *.db);;Alle Dateien (*)",
        )
        if file_path:
            line_edit.setText(file_path)
            if name_line_edit is not None:
                name_line_edit.setText(self._source_label_from_path(file_path))

    def _default_data_source_columns(self) -> dict:
        return {
            "operator_name_field": self._combo_text(self.operator_name_field)
            or str(DEFAULT_CONFIG.get("operator_name_field_name", "") or ""),
            "contact_name_field": self._combo_text(self.operator_contact_field)
            or str(DEFAULT_CONFIG.get("operator_contact_field_name", "") or ""),
            "phone_field": self._combo_text(self.operator_phone_field)
            or str(DEFAULT_CONFIG.get("operator_phone_field_name", "") or ""),
            "email_field": self._combo_text(self.operator_email_field)
            or str(DEFAULT_CONFIG.get("operator_email_field_name", "") or ""),
            "fault_number_field": self._combo_text(self.operator_fault_field)
            or str(DEFAULT_CONFIG.get("operator_fault_field_name", "") or ""),
        }

    def _prompt_data_source_dialog(self, source_type: str) -> dict | None:
        is_file = source_type == "file"
        dialog = QDialog(self)
        dialog.setWindowTitle("Dateiquelle verbinden" if is_file else "Datenbank verbinden")
        dialog.resize(700, 560 if not is_file else 520)

        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        layout.addLayout(form)

        enabled = QCheckBox("Aktiv")
        enabled.setChecked(True)
        name = QLineEdit()
        name.setPlaceholderText("z. B. Betreiberliste Trasse Nord")

        table = QLineEdit()
        source = None
        host = None
        port = None
        database = None
        username = None
        password = None
        ssl_mode = None
        schema = None

        if is_file:
            source = QLineEdit()
            source.setPlaceholderText("/pfad/datei.xlsx oder /pfad/datei.csv")
            source_row = QHBoxLayout()
            source_row.setContentsMargins(0, 0, 0, 0)
            source_row.addWidget(source, 1)
            browse_button = QPushButton("Datei waehlen...")
            browse_button.clicked.connect(lambda: self._choose_file_for_line_edit(source, name))
            source_row.addWidget(browse_button)
            source_widget = QWidget()
            source_widget.setLayout(source_row)
            table.setPlaceholderText("Blattname / Tabellenname (optional)")
        else:
            host = QLineEdit()
            host.setText("168.119.214.156")
            host.setPlaceholderText("z. B. 168.119.214.156")
            port = QLineEdit("9132")
            port.setPlaceholderText("9132")
            database = QLineEdit()
            database.setText("postgres")
            database.setPlaceholderText("z. B. postgres")
            username = QLineEdit()
            username.setText("geoserver")
            username.setPlaceholderText("z. B. qgis_user")
            password = QLineEdit()
            password.setEchoMode(QLineEdit.Password)
            password.setText("Atnzhol4zlCqKTUc")
            password.setPlaceholderText("Passwort (optional)")
            ssl_mode = QComboBox()
            ssl_mode.addItem("deaktiviert", "disable")
            ssl_mode.addItem("erlauben", "allow")
            ssl_mode.addItem("bevorzugen", "prefer")
            ssl_mode.addItem("erforderlich", "require")
            ssl_mode.addItem("verify-ca", "verify-ca")
            ssl_mode.addItem("verify-full", "verify-full")
            ssl_mode.setCurrentIndex(2)
            schema = QLineEdit()
            schema.setText("Plugin_Liste")
            schema.setPlaceholderText("z. B. public")
            table.setPlaceholderText("Tabelle / Layer (optional, fuer Direktzugriff)")

        default_columns = self._default_data_source_columns()
        op_name = QLineEdit()
        op_name.setPlaceholderText("Pflicht: Spalte Betreibername")
        op_name.setText(default_columns["operator_name_field"])
        contact = QLineEdit()
        contact.setText(default_columns["contact_name_field"])
        phone = QLineEdit()
        phone.setText(default_columns["phone_field"])
        email = QLineEdit()
        email.setText(default_columns["email_field"])
        fault = QLineEdit()
        fault.setText(default_columns["fault_number_field"])

        form.addRow("Aktiv", enabled)
        form.addRow("Name", name)
        if is_file:
            form.addRow("Quelle / URI", source_widget)
            form.addRow("Tabelle / Blatt", table)
        else:
            name.setText("Geoserver_DB")
            form.addRow("Host", host)
            form.addRow("Port", port)
            form.addRow("Datenbank", database)
            form.addRow("Benutzername", username)
            form.addRow("Passwort", password)
            form.addRow("SSL-Modus", ssl_mode)
            form.addRow("Schema", schema)
            form.addRow("Tabelle / Layer", table)
        form.addRow("Spalte Betreibername", op_name)
        form.addRow("Spalte Ansprechpartner", contact)
        form.addRow("Spalte Telefonnummer", phone)
        form.addRow("Spalte E-Mail", email)
        form.addRow("Spalte Stoernummer", fault)

        if is_file:
            info_text = "Pflicht: 'Quelle / URI' und 'Spalte Betreibername'. Alle anderen Felder sind optional."
        else:
            info_text = (
                "Pflicht: Name, Host, Port, Datenbank, SSL-Modus, Schema und Spalte Betreibername. "
                "Benutzername/Passwort nach Bedarf. "
                "Wenn 'Tabelle / Layer' leer bleibt, wird automatisch eine passende Tabelle im Schema verwendet."
            )
        info = QLabel(info_text)
        info.setWordWrap(True)
        layout.addWidget(info)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        while True:
            if dialog.exec_() != QDialog.Accepted:
                return None

            operator_name_field = op_name.text().strip()
            if not operator_name_field:
                QMessageBox.warning(dialog, "Datenquelle", "Bitte 'Spalte Betreibername' ausfuellen.")
                continue

            host_value = ""
            port_value = ""
            database_value = ""
            username_value = ""
            password_value = ""
            schema_value = ""
            table_value = table.text().strip()
            provider_value = "ogr"

            if is_file:
                source_value = source.text().strip() if source is not None else ""
                if not source_value:
                    QMessageBox.warning(dialog, "Datenquelle", "Bitte 'Quelle / URI' ausfuellen.")
                    continue
            else:
                source_name = name.text().strip()
                host_value = host.text().strip() if host is not None else ""
                port_value = port.text().strip() if port is not None else ""
                database_value = database.text().strip() if database is not None else ""
                username_value = username.text().strip() if username is not None else ""
                password_value = password.text() if password is not None else ""
                schema_value = schema.text().strip() if schema is not None else ""
                ssl_value = ssl_mode.currentData() if ssl_mode is not None else "prefer"

                if not source_name:
                    QMessageBox.warning(dialog, "Datenquelle", "Bitte 'Name' ausfuellen.")
                    continue
                if not host_value:
                    QMessageBox.warning(dialog, "Datenquelle", "Bitte 'Host' ausfuellen.")
                    continue
                if not port_value:
                    QMessageBox.warning(dialog, "Datenquelle", "Bitte 'Port' ausfuellen.")
                    continue
                if not database_value:
                    QMessageBox.warning(dialog, "Datenquelle", "Bitte 'Datenbank' ausfuellen.")
                    continue
                if not schema_value:
                    QMessageBox.warning(dialog, "Datenquelle", "Bitte 'Schema' ausfuellen.")
                    continue

                source_value = self._build_postgres_ogr_source_uri(
                    host_value,
                    port_value,
                    database_value,
                    str(ssl_value or "prefer"),
                    schema_value,
                    username_value,
                    password_value,
                )
                if schema_value and "." not in table_value:
                    table_value = f"{schema_value}.{table_value}"

            candidate = _normalize_data_source_entry(
                {
                    "enabled": enabled.isChecked(),
                    "name": name.text().strip(),
                    "source_type": source_type,
                    "provider": provider_value,
                    "source": source_value,
                    "table": table_value,
                    "operator_name_field": operator_name_field,
                    "contact_name_field": contact.text().strip(),
                    "phone_field": phone.text().strip(),
                    "email_field": email.text().strip(),
                    "fault_number_field": fault.text().strip(),
                    "folder_path_field": "",
                }
            )
            should_test = is_file or source_type == "qgis_uri" or bool(table_value)
            if should_test:
                test_layer = self._load_external_source_layer(candidate)
                if test_layer is None:
                    QMessageBox.warning(
                        dialog,
                        "Datenquelle",
                        "Quelle konnte nicht geladen werden. Bitte Verbindung pruefen.",
                    )
                    continue

                generic_fields = self._layer_uses_generic_fields(test_layer)
                header_tokens = self._header_tokens_from_first_feature(test_layer) if generic_fields else []

                if generic_fields and header_tokens:
                    resolved_name_col = self._resolve_column_index(
                        header_tokens,
                        operator_name_field,
                        ["operator_name", "betreibername", "betreiber", "name"],
                    )
                    if resolved_name_col < 0 and header_tokens:
                        resolved_name_col = 0
                    resolved_name_field = self._token_by_column_index(header_tokens, resolved_name_col)
                    available = ", ".join(header_tokens[:20])
                    resolved_contact = self._token_by_column_index(
                        header_tokens,
                        self._resolve_column_index(
                            header_tokens,
                            contact.text().strip(),
                            ["contact_name", "ansprechpartner", "kontakt", "kontaktperson", "betr_anspr"],
                        ),
                    )
                    resolved_phone = self._token_by_column_index(
                        header_tokens,
                        self._resolve_column_index(
                            header_tokens,
                            phone.text().strip(),
                            ["phone", "telefon", "telefonnummer", "betr_tel", "tel"],
                        ),
                    )
                    resolved_email = self._token_by_column_index(
                        header_tokens,
                        self._resolve_column_index(
                            header_tokens,
                            email.text().strip(),
                            ["email", "mail", "e-mail", "e_mail", "betr_email"],
                        ),
                    )
                    resolved_fault = self._token_by_column_index(
                        header_tokens,
                        self._resolve_column_index(
                            header_tokens,
                            fault.text().strip(),
                            ["fault_number", "stoernummer", "stoernr", "stornummer", "betr_stoer"],
                        ),
                    )
                else:
                    resolved_name_field = self._resolve_field_name_in_layer(
                        test_layer,
                        operator_name_field,
                        ["operator_name", "betreibername", "betreiber", "name"],
                    )
                    available = ", ".join([field.name() for field in test_layer.fields()][:20])
                    resolved_contact = self._resolve_field_name_in_layer(
                        test_layer,
                        contact.text().strip(),
                        ["contact_name", "ansprechpartner", "kontakt", "kontaktperson"],
                    )
                    resolved_phone = self._resolve_field_name_in_layer(
                        test_layer,
                        phone.text().strip(),
                        ["phone", "telefon", "telefonnummer", "betr_tel", "tel"],
                    )
                    resolved_email = self._resolve_field_name_in_layer(
                        test_layer,
                        email.text().strip(),
                        ["email", "mail", "e-mail", "e_mail", "betr_email"],
                    )
                    resolved_fault = self._resolve_field_name_in_layer(
                        test_layer,
                        fault.text().strip(),
                        ["fault_number", "stoernummer", "stoernr", "stornummer", "betr_stoer"],
                    )

                if not resolved_name_field:
                    QMessageBox.warning(
                        dialog,
                        "Datenquelle",
                        "Spalte Betreibername wurde in der Quelle nicht gefunden.\n"
                        f"Verfuegbare Spalten: {available}",
                    )
                    continue
            else:
                resolved_name_field = operator_name_field
                resolved_contact = contact.text().strip()
                resolved_phone = phone.text().strip()
                resolved_email = email.text().strip()
                resolved_fault = fault.text().strip()

            source_name = name.text().strip()
            if is_file:
                auto_name = self._source_label_from_path(source_value)
                if auto_name:
                    source_name = auto_name

            return _normalize_data_source_entry(
                {
                    "enabled": enabled.isChecked(),
                    "name": source_name,
                    "source_type": source_type,
                    "provider": provider_value,
                    "source": source_value,
                    "table": table_value,
                    "operator_name_field": resolved_name_field,
                    "contact_name_field": resolved_contact,
                    "phone_field": resolved_phone,
                    "email_field": resolved_email,
                    "fault_number_field": resolved_fault,
                    "folder_path_field": "",
                }
            )

    def _append_data_source_to_table(
        self,
        table: QTableWidget,
        source_entry: dict,
        refresh_selector: bool = True,
    ):
        normalized = _normalize_data_source_entry(source_entry)
        sorting_enabled = table.isSortingEnabled()
        if sorting_enabled:
            table.setSortingEnabled(False)
        row = table.rowCount()
        old_block = table.blockSignals(True)
        try:
            table.insertRow(row)

            enabled_item = QTableWidgetItem("")
            enabled_item.setFlags(
                enabled_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable
            )
            enabled_item.setCheckState(Qt.Checked if normalized.get("enabled", True) else Qt.Unchecked)
            table.setItem(row, 0, enabled_item)

            table.setItem(row, 1, QTableWidgetItem(str(normalized.get("name", "") or "")))
            if table is self.db_data_source_table:
                db_parts = self._db_source_parts_from_uri(
                    str(normalized.get("source", "") or ""),
                    str(normalized.get("table", "") or ""),
                )
                table.setItem(row, 2, QTableWidgetItem(str(normalized.get("provider", "ogr") or "ogr")))
                table.setItem(row, 3, QTableWidgetItem(str(db_parts.get("host", "") or "")))
                table.setItem(row, 4, QTableWidgetItem(str(db_parts.get("port", "") or "")))
                table.setItem(row, 5, QTableWidgetItem(str(db_parts.get("database", "") or "")))
                table.setItem(row, 6, QTableWidgetItem(str(db_parts.get("username", "") or "")))
                table.setItem(row, 7, QTableWidgetItem(str(db_parts.get("password", "") or "")))
                table.setItem(row, 8, QTableWidgetItem(str(db_parts.get("ssl_mode", "") or "")))
                table.setItem(row, 9, QTableWidgetItem(str(db_parts.get("schema", "") or "")))
                table.setItem(row, 10, QTableWidgetItem(str(db_parts.get("table", "") or "")))
                table.setItem(row, 11, QTableWidgetItem(str(normalized.get("source", "") or "")))
                table.setItem(row, 12, QTableWidgetItem(str(normalized.get("operator_name_field", "") or "")))
                table.setItem(row, 13, QTableWidgetItem(str(normalized.get("contact_name_field", "") or "")))
                table.setItem(row, 14, QTableWidgetItem(str(normalized.get("phone_field", "") or "")))
                table.setItem(row, 15, QTableWidgetItem(str(normalized.get("email_field", "") or "")))
                table.setItem(row, 16, QTableWidgetItem(str(normalized.get("fault_number_field", "") or "")))
            else:
                table.setItem(row, 2, QTableWidgetItem(str(normalized.get("provider", "ogr") or "ogr")))
                table.setItem(row, 3, QTableWidgetItem(str(normalized.get("source", "") or "")))
                table.setItem(row, 4, QTableWidgetItem(str(normalized.get("table", "") or "")))
                table.setItem(row, 5, QTableWidgetItem(str(normalized.get("operator_name_field", "") or "")))
                table.setItem(row, 6, QTableWidgetItem(str(normalized.get("contact_name_field", "") or "")))
                table.setItem(row, 7, QTableWidgetItem(str(normalized.get("phone_field", "") or "")))
                table.setItem(row, 8, QTableWidgetItem(str(normalized.get("email_field", "") or "")))
                table.setItem(row, 9, QTableWidgetItem(str(normalized.get("fault_number_field", "") or "")))
            table.setCurrentCell(row, 1)
        finally:
            table.blockSignals(old_block)
            if sorting_enabled:
                table.setSortingEnabled(True)
        if table is self.file_data_source_table:
            self._apply_table_text_filter(table, self.file_data_source_search_input.text())
        elif table is self.db_data_source_table:
            self._apply_table_text_filter(table, self.db_data_source_search_input.text())
        if refresh_selector:
            self._refresh_operator_source_selector()

    def _add_data_source_row(self, values=None):
        if isinstance(values, bool):
            values = None
        normalized = _normalize_data_source_entry(values or {})
        target_table = (
            self.file_data_source_table
            if normalized.get("source_type", "file") == "file"
            else self.db_data_source_table
        )
        self._append_data_source_to_table(target_table, normalized)

    def _add_file_source_via_dialog(self):
        entry = self._prompt_data_source_dialog("file")
        if entry is None:
            return
        self._append_data_source_to_table(self.file_data_source_table, entry)

    def _add_db_source_via_dialog(self):
        entry = self._prompt_data_source_dialog("qgis_uri")
        if entry is None:
            return
        self._append_data_source_to_table(self.db_data_source_table, entry)

    def _remove_selected_row_from_table(self, table: QTableWidget):
        selected = table.selectionModel().selectedRows()
        if not selected:
            return
        table.removeRow(selected[0].row())
        if table is self.file_data_source_table:
            self._apply_table_text_filter(table, self.file_data_source_search_input.text())
        elif table is self.db_data_source_table:
            self._apply_table_text_filter(table, self.db_data_source_search_input.text())
        self._refresh_operator_source_selector()

    def _remove_selected_file_source_row(self):
        self._remove_selected_row_from_table(self.file_data_source_table)

    def _remove_selected_db_source_row(self):
        self._remove_selected_row_from_table(self.db_data_source_table)

    def _selected_row_index(self, table: QTableWidget) -> int:
        selected = table.selectionModel().selectedRows()
        if not selected:
            return -1
        return selected[0].row()

    def _preview_selected_source(self, table: QTableWidget, source_type: str, title: str):
        row_index = self._selected_row_index(table)
        if row_index < 0:
            QMessageBox.information(self, "Datenvorschau", "Bitte zuerst eine Quelle auswaehlen.")
            return

        source_entry = self._entry_from_table_row(table, row_index, source_type)
        layer = self._load_external_source_layer(source_entry)
        if layer is None:
            debug_lines = []
            for provider_name, uri_text in self._last_external_load_debug[:6]:
                debug_lines.append(f"- {provider_name}: {uri_text}")
            debug_block = "\n".join(debug_lines)
            detail = ""
            if debug_block:
                detail = f"\n\nGetestete Verbindungsversuche:\n{debug_block}"
            QMessageBox.warning(
                self,
                "Datenvorschau",
                "Quelle konnte nicht geladen werden. Bitte Verbindung und Mapping pruefen."
                + detail,
            )
            return

        field_names = [field.name() for field in layer.fields()]
        if not field_names:
            QMessageBox.information(self, "Datenvorschau", "Quelle hat keine Felder.")
            return

        rows = []
        max_rows = 1000
        for idx, feature in enumerate(layer.getFeatures()):
            if idx >= max_rows:
                break
            row_values = []
            for field_name in field_names:
                value = feature[field_name]
                row_values.append("" if value is None else str(value))
            rows.append(row_values)

        preview = QDialog(self)
        preview.setWindowTitle(title)
        preview.resize(920, 560)
        layout = QVBoxLayout(preview)

        hint = QLabel(
            f"Zeige bis zu {max_rows} Zeilen aus: {source_entry.get('name') or source_entry.get('source')}"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        table_widget = QTableWidget(len(rows), len(field_names))
        table_widget.setHorizontalHeaderLabels(field_names)
        table_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        table_widget.setAlternatingRowColors(True)
        table_widget.horizontalHeader().setStretchLastSection(False)
        table_widget.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table_widget.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        for r_idx, values in enumerate(rows):
            for c_idx, value in enumerate(values):
                table_widget.setItem(r_idx, c_idx, QTableWidgetItem(value))
        layout.addWidget(table_widget, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(preview.reject)
        buttons.accepted.connect(preview.accept)
        layout.addWidget(buttons)
        preview.exec_()

    def _preview_selected_file_source(self):
        self._preview_selected_source(
            self.file_data_source_table,
            "file",
            "Dateiquelle - Datenvorschau",
        )

    def _preview_selected_db_source(self):
        self._preview_selected_source(
            self.db_data_source_table,
            "qgis_uri",
            "Datenbankquelle - Datenvorschau",
        )

    def _table_row_text(self, table: QTableWidget, row: int, col: int) -> str:
        item = table.item(row, col)
        return item.text().strip() if item else ""

    def _entry_from_table_row(self, table: QTableWidget, row: int, source_type: str) -> dict:
        enabled_item = table.item(row, 0)
        enabled = bool(enabled_item and enabled_item.checkState() == Qt.Checked)
        if source_type == "qgis_uri":
            provider = self._table_row_text(table, row, 2) or "ogr"
            host = self._table_row_text(table, row, 3)
            port = self._table_row_text(table, row, 4)
            database = self._table_row_text(table, row, 5)
            username = self._table_row_text(table, row, 6)
            password = self._table_row_text(table, row, 7)
            ssl_mode = self._table_row_text(table, row, 8) or "prefer"
            schema = self._table_row_text(table, row, 9)
            table_name = self._table_row_text(table, row, 10)
            raw_source_uri = self._table_row_text(table, row, 11)
            if not table_name and raw_source_uri:
                uri_schema, uri_table = self._pg_schema_table_from_source_uri(raw_source_uri)
                if uri_table:
                    table_name = f"{uri_schema}.{uri_table}" if uri_schema else uri_table

            if schema and table_name and "." not in table_name:
                table_name = f"{schema}.{table_name}"

            source_value = raw_source_uri
            provider_token = str(provider or "").strip().lower()
            if provider_token == "ogr" and (host or database):
                source_value = self._build_postgres_ogr_source_uri(
                    host,
                    port,
                    database,
                    ssl_mode,
                    schema,
                    username,
                    password,
                )
            elif provider_token == "postgres" and (host or database or raw_source_uri):
                source_value = self._build_postgres_provider_source_uri(
                    host,
                    port,
                    database,
                    ssl_mode,
                    schema,
                    table_name,
                    username,
                    password,
                    self._pg_uri_option_value(raw_source_uri, "key"),
                    self._pg_uri_option_value(raw_source_uri, "checkPrimaryKeyUnicity"),
                )

            return _normalize_data_source_entry(
                {
                    "enabled": enabled,
                    "name": self._table_row_text(table, row, 1),
                    "source_type": source_type,
                    "provider": provider,
                    "source": source_value,
                    "table": table_name,
                    "operator_name_field": self._table_row_text(table, row, 12),
                    "contact_name_field": self._table_row_text(table, row, 13),
                    "phone_field": self._table_row_text(table, row, 14),
                    "email_field": self._table_row_text(table, row, 15),
                    "fault_number_field": self._table_row_text(table, row, 16),
                    "folder_path_field": "",
                }
            )

        return _normalize_data_source_entry(
            {
                "enabled": enabled,
                "name": self._table_row_text(table, row, 1),
                "source_type": source_type,
                "provider": self._table_row_text(table, row, 2) or "ogr",
                "source": self._table_row_text(table, row, 3),
                "table": self._table_row_text(table, row, 4),
                "operator_name_field": self._table_row_text(table, row, 5),
                "contact_name_field": self._table_row_text(table, row, 6),
                "phone_field": self._table_row_text(table, row, 7),
                "email_field": self._table_row_text(table, row, 8),
                "fault_number_field": self._table_row_text(table, row, 9),
                "folder_path_field": "",
            }
        )

    def _set_data_sources(self, data_sources):
        self.file_data_source_table.setRowCount(0)
        self.db_data_source_table.setRowCount(0)
        for entry in data_sources or []:
            normalized = _normalize_data_source_entry(entry)
            target_table = (
                self.file_data_source_table
                if normalized.get("source_type", "file") == "file"
                else self.db_data_source_table
            )
            self._append_data_source_to_table(target_table, normalized, refresh_selector=False)
        self._refresh_operator_source_selector()

    def _data_sources(self):
        result = []
        for row in range(self.file_data_source_table.rowCount()):
            entry = self._entry_from_table_row(self.file_data_source_table, row, "file")
            if any(
                [
                    entry["name"],
                    entry["source"],
                    entry["table"],
                    entry["operator_name_field"],
                    entry["contact_name_field"],
                    entry["phone_field"],
                    entry["email_field"],
                    entry["fault_number_field"],
                    entry["folder_path_field"],
                ]
            ):
                result.append(entry)
        for row in range(self.db_data_source_table.rowCount()):
            entry = self._entry_from_table_row(self.db_data_source_table, row, "qgis_uri")
            if any(
                [
                    entry["name"],
                    entry["source"],
                    entry["table"],
                    entry["operator_name_field"],
                    entry["contact_name_field"],
                    entry["phone_field"],
                    entry["email_field"],
                    entry["fault_number_field"],
                    entry["folder_path_field"],
                ]
            ):
                result.append(entry)
        return result

    def set_values(self, config: dict):
        self._set_global_nextcloud_config(config)
        self._set_combo_text(self.path_field, str(config.get("path_field_name", "")))
        self._set_combo_text(self.file_field, str(config.get("file_link_field_name", "")))
        self._set_combo_text(self.folder_field, str(config.get("folder_link_field_name", "")))
        self._set_combo_text(self.name_field, str(config.get("name_field_name", "")))
        self._set_combo_text(self.stand_field, str(config.get("stand_field_name", "")))
        self._set_combo_text(self.operator_name_field, str(config.get("operator_name_field_name", "")))
        self._set_combo_text(
            self.operator_contact_field, str(config.get("operator_contact_field_name", ""))
        )
        self._set_combo_text(self.operator_phone_field, str(config.get("operator_phone_field_name", "")))
        self._set_combo_text(self.operator_email_field, str(config.get("operator_email_field_name", "")))
        self._set_combo_text(self.operator_fault_field, str(config.get("operator_fault_field_name", "")))
        self._set_combo_text(self.operator_validity_field, str(config.get("operator_validity_field_name", "")))
        self._set_combo_text(self.operator_stand_field, str(config.get("operator_stand_field_name", "")))
        self.overwrite.setChecked(bool(config.get("overwrite_existing_values", True)))
        self.fill_on_open.setChecked(bool(config.get("fill_on_form_open", False)))
        self._set_operators(config.get("operators", []))
        self._set_data_sources(config.get("external_data_sources", []))

    def values(self) -> dict:
        roots = self._global_nextcloud_roots()
        return {
            "nextcloud_base_url": str(
                self._global_nextcloud_config.get("nextcloud_base_url", "")
            ).strip(),
            "nextcloud_user": str(
                self._global_nextcloud_config.get("nextcloud_user", "")
            ).strip(),
            "nextcloud_app_password": str(
                self._global_nextcloud_config.get("nextcloud_app_password", "")
            ),
            "local_nextcloud_roots": roots,
            "nextcloud_folder_marker": str(
                self._global_nextcloud_config.get("nextcloud_folder_marker", "")
            ).strip(),
            "path_field_name": self._combo_text(self.path_field),
            "file_link_field_name": self._combo_text(self.file_field),
            "folder_link_field_name": self._combo_text(self.folder_field),
            "name_field_name": self._combo_text(self.name_field),
            "stand_field_name": self._combo_text(self.stand_field),
            "operator_name_field_name": self._combo_text(self.operator_name_field),
            "operator_contact_field_name": self._combo_text(self.operator_contact_field),
            "operator_phone_field_name": self._combo_text(self.operator_phone_field),
            "operator_email_field_name": self._combo_text(self.operator_email_field),
            "operator_fault_field_name": self._combo_text(self.operator_fault_field),
            "operator_validity_field_name": self._combo_text(self.operator_validity_field),
            "operator_stand_field_name": self._combo_text(self.operator_stand_field),
            "overwrite_existing_values": self.overwrite.isChecked(),
            "fill_on_form_open": self.fill_on_open.isChecked(),
            "operators": self._operators(),
            "external_data_sources": self._data_sources(),
        }


def _property_key(name: str) -> str:
    return f"{PROPERTY_PREFIX}{name}"


def _master_setting_key(name: str) -> str:
    return f"{MASTER_SETTINGS_PREFIX}/{name}"


def _load_nextcloud_settings_for_prefix(prefix_key_builder) -> dict:
    settings = QSettings()
    cfg = {}
    for key in USER_CONFIG_KEYS:
        setting_key = prefix_key_builder(key)
        if not settings.contains(setting_key):
            continue
        raw = settings.value(setting_key, None)
        if key == "local_nextcloud_roots":
            cfg[key] = _parse_roots(raw)
        else:
            cfg[key] = str(raw or "").strip()
    return cfg


def _to_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "ja", "on")


def _parse_roots(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
        except Exception:
            pass
    return [line.strip() for line in text.splitlines() if line.strip()]


def _load_user_config() -> dict:
    return _load_nextcloud_settings_for_prefix(_master_setting_key)


def _normalize_operator_entry(entry) -> dict:
    if isinstance(entry, dict):
        return {
            "source_name": str(
                entry.get(
                    "source_name",
                    entry.get("_source_name", entry.get("data_source", entry.get("datenquelle", ""))),
                )
                or ""
            ).strip(),
            "operator_name": str(
                entry.get("operator_name", entry.get("betreiber", ""))
                or ""
            ).strip(),
            "validity": str(
                entry.get(
                    "validity",
                    entry.get(
                        "gueltigkeit",
                        entry.get("gültigkeit", entry.get("gueltigk", entry.get("gültigk", ""))),
                    ),
                )
                or ""
            ).strip(),
            "stand": str(entry.get("stand", entry.get("operator_stand", entry.get("stand_datum", ""))) or "").strip(),
            "contact_name": str(
                entry.get("contact_name", entry.get("ansprechpartner", entry.get("kontakt", "")))
                or ""
            ).strip(),
            "phone": str(entry.get("phone", entry.get("telefonnummer", "")) or "").strip(),
            "email": str(entry.get("email", entry.get("mail", "")) or "").strip(),
            "fault_number": str(
                entry.get("fault_number", entry.get("stoernummer", ""))
                or ""
            ).strip(),
            "folder_path": str(
                entry.get(
                    "folder_path",
                    entry.get("ordnerpfad", entry.get("ordner", entry.get("path", ""))),
                )
                or ""
            ).strip(),
        }
    if isinstance(entry, (list, tuple)):
        raw_values = [str(v or "").strip() for v in list(entry)]
        if len(raw_values) >= 9:
            values = raw_values[:9]
        elif len(raw_values) >= 7:
            values = [
                raw_values[0],
                raw_values[1],
                "",
                "",
                raw_values[2],
                raw_values[3],
                raw_values[4],
                raw_values[5],
                raw_values[6],
            ]
        else:
            values = [""] + raw_values[:8]
        while len(values) < 9:
            values.append("")
        return {
            "source_name": values[0],
            "operator_name": values[1],
            "validity": values[2],
            "stand": values[3],
            "contact_name": values[4],
            "phone": values[5],
            "email": values[6],
            "fault_number": values[7],
            "folder_path": values[8],
        }
    return {
        "source_name": "",
        "operator_name": str(entry or "").strip(),
        "validity": "",
        "stand": "",
        "contact_name": "",
        "phone": "",
        "email": "",
        "fault_number": "",
        "folder_path": "",
    }


def _normalize_data_source_entry(entry) -> dict:
    if isinstance(entry, dict):
        source_type = str(entry.get("source_type", entry.get("type", "file")) or "file").strip().lower()
        if source_type not in ("file", "qgis_uri"):
            source_type = "file"

        provider = str(entry.get("provider", "ogr") or "ogr").strip() or "ogr"
        source_value = str(
            entry.get("source", entry.get("path", entry.get("uri", ""))) or ""
        ).strip()
        table_value = str(
            entry.get("table", entry.get("layer_name", entry.get("sheet", ""))) or ""
        ).strip()

        return {
            "enabled": _to_bool(entry.get("enabled", entry.get("active", True)), True),
            "name": str(entry.get("name", entry.get("label", "")) or "").strip(),
            "source_type": source_type,
            "provider": provider,
            "source": source_value,
            "table": table_value,
            "operator_name_field": str(
                entry.get("operator_name_field", entry.get("operator_name_column", ""))
                or ""
            ).strip(),
            "contact_name_field": str(
                entry.get("contact_name_field", entry.get("contact_column", ""))
                or ""
            ).strip(),
            "phone_field": str(entry.get("phone_field", entry.get("phone_column", "")) or "").strip(),
            "email_field": str(entry.get("email_field", entry.get("email_column", "")) or "").strip(),
            "fault_number_field": str(
                entry.get("fault_number_field", entry.get("fault_number_column", ""))
                or ""
            ).strip(),
            "folder_path_field": str(
                entry.get("folder_path_field", entry.get("folder_path_column", ""))
                or ""
            ).strip(),
        }

    return {
        "enabled": True,
        "name": "",
        "source_type": "file",
        "provider": "ogr",
        "source": str(entry or "").strip(),
        "table": "",
        "operator_name_field": "",
        "contact_name_field": "",
        "phone_field": "",
        "email_field": "",
        "fault_number_field": "",
        "folder_path_field": "",
    }


def _parse_operators(value) -> list[dict]:
    if value is None:
        return []

    parsed = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = [text]

    if not isinstance(parsed, list):
        return []

    result = []
    for entry in parsed:
        normalized = _normalize_operator_entry(entry)
        if any(
            [
                normalized["operator_name"],
                normalized["validity"],
                normalized["stand"],
                normalized["contact_name"],
                normalized["phone"],
                normalized["email"],
                normalized["fault_number"],
                normalized["folder_path"],
            ]
        ):
            result.append(normalized)
    return result


def _parse_data_sources(value) -> list[dict]:
    if value is None:
        return []

    parsed = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = [text]

    if not isinstance(parsed, list):
        return []

    result = []
    for entry in parsed:
        normalized = _normalize_data_source_entry(entry)
        if any(
            [
                normalized["name"],
                normalized["source"],
                normalized["table"],
                normalized["operator_name_field"],
                normalized["contact_name_field"],
                normalized["phone_field"],
                normalized["email_field"],
                normalized["fault_number_field"],
                normalized["folder_path_field"],
            ]
        ):
            result.append(normalized)
    return result


def _load_layer_config(layer) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    for key, default in DEFAULT_CONFIG.items():
        raw = layer.customProperty(_property_key(key), default)
        if key in ("overwrite_existing_values", "fill_on_form_open"):
            cfg[key] = _to_bool(raw, bool(default))
        elif key == "local_nextcloud_roots":
            cfg[key] = _parse_roots(raw)
        elif key == "operators":
            cfg[key] = _parse_operators(raw)
        elif key == "external_data_sources":
            cfg[key] = _parse_data_sources(raw)
        else:
            cfg[key] = str(raw or "").strip()
    return cfg


def _merged_with_user_config(config: dict, user_config: dict | None = None) -> dict:
    merged = dict(config or {})
    source = user_config if isinstance(user_config, dict) else _load_user_config()
    for key in USER_CONFIG_KEYS:
        if key in source:
            merged[key] = source[key]
    return merged


def _effective_layer_config(layer) -> dict:
    return _merged_with_user_config(_load_layer_config(layer))


def _save_layer_config(layer, config: dict):
    for key in DEFAULT_CONFIG.keys():
        value = config.get(key, DEFAULT_CONFIG[key])
        if key in ("local_nextcloud_roots", "operators", "external_data_sources"):
            layer.setCustomProperty(_property_key(key), json.dumps(value))
        elif key in ("overwrite_existing_values", "fill_on_form_open"):
            layer.setCustomProperty(_property_key(key), bool(value))
        else:
            layer.setCustomProperty(_property_key(key), str(value))


def _clear_layer_config(layer):
    for key in DEFAULT_CONFIG.keys():
        prop = _property_key(key)
        if hasattr(layer, "removeCustomProperty"):
            layer.removeCustomProperty(prop)
        else:
            layer.setCustomProperty(prop, "")


def _field_names_to_validate(config: dict) -> list[str]:
    names = [
        config.get("path_field_name", ""),
        config.get("file_link_field_name", ""),
        config.get("folder_link_field_name", ""),
        config.get("name_field_name", ""),
        config.get("stand_field_name", ""),
        config.get("operator_name_field_name", ""),
        config.get("operator_contact_field_name", ""),
        config.get("operator_phone_field_name", ""),
        config.get("operator_email_field_name", ""),
        config.get("operator_fault_field_name", ""),
        config.get("operator_validity_field_name", ""),
        config.get("operator_stand_field_name", ""),
    ]
    return [str(name).strip() for name in names if str(name).strip()]


def _missing_fields(layer, config: dict) -> list[str]:
    return [name for name in _field_names_to_validate(config) if layer.fields().indexOf(name) < 0]


def _normalized_operator_name(value) -> str:
    return str(value or "").strip().casefold()


def _local_unique_operator_entry(config: dict, operator_name_value) -> dict | None:
    needle = _normalized_operator_name(operator_name_value)
    if not needle:
        return None

    matches = []
    for entry in config.get("operators", []):
        normalized = _normalize_operator_entry(entry)
        if not normalized.get("operator_name"):
            continue
        if _normalized_operator_name(normalized.get("operator_name")) == needle:
            matches.append(normalized)

    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    def _signature(entry: dict):
        return (
            str(entry.get("validity", "") or "").strip().lower(),
            str(entry.get("stand", "") or "").strip().lower(),
            str(entry.get("contact_name", "") or "").strip().lower(),
            str(entry.get("phone", "") or "").strip().lower(),
            str(entry.get("email", "") or "").strip().lower(),
            str(entry.get("fault_number", "") or "").strip().lower(),
            str(entry.get("folder_path", "") or "").strip().lower(),
        )

    signatures = {_signature(entry) for entry in matches}
    if len(signatures) == 1:
        return matches[0]

    def _score(entry: dict) -> int:
        values = [
            str(entry.get("validity", "") or "").strip(),
            str(entry.get("stand", "") or "").strip(),
            str(entry.get("contact_name", "") or "").strip(),
            str(entry.get("phone", "") or "").strip(),
            str(entry.get("email", "") or "").strip(),
            str(entry.get("fault_number", "") or "").strip(),
            str(entry.get("folder_path", "") or "").strip(),
        ]
        return sum(1 for value in values if value)

    best = max(_score(entry) for entry in matches)
    best_entries = [entry for entry in matches if _score(entry) == best]
    if len(best_entries) == 1 and best > 0:
        return best_entries[0]
    return None


def _sync_layer_operator_fields(layer, config: dict) -> dict:
    operator_name_field = str(config.get("operator_name_field_name", "") or "").strip()
    operator_name_index = layer.fields().indexOf(operator_name_field)
    if not operator_name_field or operator_name_index < 0:
        return {
            "processed": 0,
            "updated_rows": 0,
            "updated_values": 0,
            "committed": False,
            "pending_edits": False,
        }

    target_specs = [
        ("operator_contact_field_name", "contact_name"),
        ("operator_phone_field_name", "phone"),
        ("operator_email_field_name", "email"),
        ("operator_fault_field_name", "fault_number"),
        ("operator_validity_field_name", "validity"),
        ("operator_stand_field_name", "stand"),
    ]
    targets = []
    for config_key, entry_key in target_specs:
        field_name = str(config.get(config_key, "") or "").strip()
        if not field_name:
            continue
        field_idx = layer.fields().indexOf(field_name)
        if field_idx < 0:
            continue
        targets.append((field_name, field_idx, entry_key))

    if not targets:
        return {
            "processed": 0,
            "updated_rows": 0,
            "updated_values": 0,
            "committed": False,
            "pending_edits": False,
        }

    started_editing = False
    if not layer.isEditable():
        if not layer.startEditing():
            raise RuntimeError("Layer konnte nicht in den Bearbeitungsmodus gesetzt werden.")
        started_editing = True

    def _same_value(current, new_value) -> bool:
        if new_value is None:
            if current is None:
                return True
            return str(current).strip() == ""
        return str(current or "").strip() == str(new_value).strip()

    processed = 0
    updated_rows = 0
    updated_values = 0

    for feature in layer.getFeatures():
        processed += 1
        operator_entry = _local_unique_operator_entry(config, feature[operator_name_field])
        row_changed = False

        for field_name, field_idx, entry_key in targets:
            new_value = None
            if operator_entry:
                candidate = str(operator_entry.get(entry_key, "") or "").strip()
                if candidate:
                    new_value = candidate

            current_value = feature[field_name]
            if _same_value(current_value, new_value):
                continue

            if layer.changeAttributeValue(feature.id(), field_idx, new_value):
                row_changed = True
                updated_values += 1

        if row_changed:
            updated_rows += 1

    committed = False
    if started_editing:
        if not layer.commitChanges():
            errors = []
            if hasattr(layer, "commitErrors"):
                try:
                    errors = layer.commitErrors()
                except Exception:
                    errors = []
            if layer.isEditable():
                layer.rollBack()
            detail = "; ".join(errors) if errors else "Unbekannter Fehler."
            raise RuntimeError(f"Aenderungen konnten nicht gespeichert werden: {detail}")
        committed = True

    return {
        "processed": processed,
        "updated_rows": updated_rows,
        "updated_values": updated_values,
        "committed": committed,
        "pending_edits": (not committed and updated_values > 0),
    }


def _init_code_source_dialog_value():
    direct = getattr(QgsEditFormConfig, "CodeSourceDialog", None)
    if direct is not None:
        return direct

    nested = getattr(QgsEditFormConfig, "PythonInitCodeSource", None)
    if nested is not None:
        value = getattr(nested, "CodeSourceDialog", None)
        if value is not None:
            return value

    nested = getattr(QgsEditFormConfig, "CodeSource", None)
    if nested is not None:
        value = getattr(nested, "CodeSourceDialog", None)
        if value is not None:
            return value

    return None


def _apply_form_init_code(layer):
    config = layer.editFormConfig()
    if hasattr(config, "setInitCodeSource"):
        code_source = _init_code_source_dialog_value()
        if code_source is not None:
            config.setInitCodeSource(code_source)
    if hasattr(config, "setInitFilePath"):
        config.setInitFilePath("")
    config.setInitCode(BOOTSTRAP_CODE)
    config.setInitFunction(INIT_FUNCTION_NAME)
    layer.setEditFormConfig(config)


def _remove_form_init_code_if_managed(layer):
    config = layer.editFormConfig()
    current_func = ""
    current_code = ""
    if hasattr(config, "initFunction"):
        current_func = str(config.initFunction() or "")
    if hasattr(config, "initCode"):
        current_code = str(config.initCode() or "")

    if current_func == INIT_FUNCTION_NAME and any(
        marker in current_code for marker in BOOTSTRAP_CODE_MARKERS
    ):
        config.setInitCode("")
        config.setInitFunction("")
        layer.setEditFormConfig(config)


class NextcloudFormPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action_bind = None
        self.action_unbind_hidden = None
        self.icon = None
        self.toolbar = None

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icon-512.png")
        self.icon = QIcon(icon_path)

        self.action_bind = QAction(self.icon, "Layer mit AttributionButler verbinden", self.iface.mainWindow())
        self.action_bind.setToolTip("AttributionButler mit aktivem Layer verbinden")
        self.action_bind.triggered.connect(self.bind_active_layer)
        self.iface.addPluginToMenu(PLUGIN_MENU, self.action_bind)

        # Hidden unbind action: no menu/toolbar entry, only keyboard shortcut.
        self.action_unbind_hidden = QAction(self.iface.mainWindow())
        self.action_unbind_hidden.setShortcut("Ctrl+Alt+Shift+U")
        self.action_unbind_hidden.setShortcutContext(Qt.ApplicationShortcut)
        self.action_unbind_hidden.triggered.connect(self.unbind_active_layer)
        self.action_unbind_hidden.setVisible(False)
        self.iface.mainWindow().addAction(self.action_unbind_hidden)

        # Eigene Toolbar, damit das Symbol direkt sichtbar ist wie bei Standard-Tools.
        self.toolbar = self.iface.addToolBar("AttributionButler")
        self.toolbar.setObjectName("AttributionButlerToolbar")
        self.toolbar.addAction(self.action_bind)
        self.toolbar.setVisible(True)

    def unload(self):
        action_bind = self.action_bind
        action_unbind_hidden = self.action_unbind_hidden
        toolbar = self._find_toolbar()

        self.action_bind = None
        self.action_unbind_hidden = None
        self.toolbar = None

        if self._is_qt_object_alive(action_bind):
            self._safe_qt_call(self.iface.removePluginMenu, PLUGIN_MENU, action_bind)
            self._safe_qt_call(action_bind.deleteLater)
        if self._is_qt_object_alive(action_unbind_hidden):
            self._safe_qt_call(self.iface.mainWindow().removeAction, action_unbind_hidden)
            self._safe_qt_call(action_unbind_hidden.deleteLater)
        if self._is_qt_object_alive(toolbar):
            self._safe_qt_call(self.iface.mainWindow().removeToolBar, toolbar)
            self._safe_qt_call(toolbar.deleteLater)

    def _find_toolbar(self):
        try:
            return self.iface.mainWindow().findChild(QToolBar, "AttributionButlerToolbar")
        except Exception:
            return self.toolbar

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
        except Exception:
            return None

    def _active_vector_layer(self):
        layer = self.iface.activeLayer()
        if layer is None or layer.type() != QgsMapLayerType.VectorLayer:
            return None
        return layer

    def bind_active_layer(self):
        layer = self._active_vector_layer()
        if layer is None:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "AttributionButler",
                "Bitte zuerst einen Vektor-Layer aktivieren.",
            )
            return

        current_cfg = _effective_layer_config(layer)
        dialog = LayerConfigDialog(layer, self.iface.mainWindow())
        dialog.set_values(current_cfg)
        if dialog.exec_() != QDialog.Accepted:
            return

        config = dialog.values()
        if not config["nextcloud_base_url"] or not config["nextcloud_user"] or not config["nextcloud_app_password"]:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "AttributionButler",
                "Nextcloud URL, Benutzer und App-Passwort fehlen. "
                "Bitte in Trassify Master Tools > Einstellungen > Nextcloud setzen.",
            )
            return
        if not config["path_field_name"]:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "AttributionButler",
                "Pfadfeld ist erforderlich.",
            )
            return
        target_fields = [
            config.get("file_link_field_name", ""),
            config.get("folder_link_field_name", ""),
            config.get("name_field_name", ""),
            config.get("stand_field_name", ""),
            config.get("operator_contact_field_name", ""),
            config.get("operator_phone_field_name", ""),
            config.get("operator_email_field_name", ""),
            config.get("operator_fault_field_name", ""),
            config.get("operator_validity_field_name", ""),
            config.get("operator_stand_field_name", ""),
        ]
        if not any(str(name or "").strip() for name in target_fields):
            QMessageBox.warning(
                self.iface.mainWindow(),
                "AttributionButler",
                "Mindestens ein Zielfeld muss gesetzt sein.",
            )
            return

        missing = _missing_fields(layer, config)
        if missing:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "AttributionButler",
                "Diese Felder fehlen im Layer:\n- " + "\n- ".join(missing),
            )
            return

        layer_config = dict(config)
        for key in USER_CONFIG_KEYS:
            if key == "local_nextcloud_roots":
                layer_config[key] = []
            else:
                layer_config[key] = ""
        _save_layer_config(layer, layer_config)
        _apply_form_init_code(layer)

        operator_name_field = str(config.get("operator_name_field_name", "") or "").strip()
        has_operator_targets = any(
            str(config.get(key, "") or "").strip()
            for key in (
                "operator_contact_field_name",
                "operator_phone_field_name",
                "operator_email_field_name",
                "operator_fault_field_name",
                "operator_validity_field_name",
                "operator_stand_field_name",
            )
        )
        can_sync_existing = bool(operator_name_field and has_operator_targets)
        if can_sync_existing:
            answer = QMessageBox.question(
                self.iface.mainWindow(),
                "AttributionButler",
                "Sollen bestehende Datensaetze im Layer jetzt mit der Betreiberliste synchronisiert werden?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer == QMessageBox.Yes:
                try:
                    sync_result = _sync_layer_operator_fields(layer, config)
                    if sync_result["updated_values"] > 0:
                        suffix = ""
                        if sync_result["pending_edits"]:
                            suffix = " (Aenderungen sind noch nicht gespeichert.)"
                        self.iface.messageBar().pushMessage(
                            "AttributionButler",
                            f"Synchronisiert: {sync_result['updated_rows']} Datensaetze, {sync_result['updated_values']} Feldwerte{suffix}",
                            level=Qgis.Info,
                            duration=6,
                        )
                    else:
                        self.iface.messageBar().pushMessage(
                            "AttributionButler",
                            "Keine Aenderungen noetig: Betreiberdaten sind bereits aktuell.",
                            level=Qgis.Info,
                            duration=5,
                        )
                except Exception as exc:
                    QMessageBox.warning(
                        self.iface.mainWindow(),
                        "AttributionButler",
                        f"Synchronisierung fehlgeschlagen: {exc}",
                    )

        self.iface.messageBar().pushMessage(
            "AttributionButler",
            f"Layer '{layer.name()}' ist verbunden.",
            level=Qgis.Success,
            duration=5,
        )

    def unbind_active_layer(self):
        layer = self._active_vector_layer()
        if layer is None:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "AttributionButler",
                "Bitte zuerst einen Vektor-Layer aktivieren.",
            )
            return

        _clear_layer_config(layer)
        _remove_form_init_code_if_managed(layer)
        self.iface.messageBar().pushMessage(
            "AttributionButler",
            f"AttributionButler von Layer '{layer.name()}' entfernt.",
            level=Qgis.Info,
            duration=5,
        )
