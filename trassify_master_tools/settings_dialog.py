from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .shared_settings import DEFAULT_SHARED_SETTINGS, build_postgres_ogr_uri


class MasterSettingsDialog(QDialog):
    def __init__(self, plugin_controller, parent=None):
        super().__init__(parent)
        self.plugin_controller = plugin_controller

        self.setWindowTitle("Trassify Master Tools | Einstellungen")
        self.setWindowIcon(QIcon(str(plugin_controller.plugin_dir / "icon.svg")))
        self.resize(760, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        intro = QLabel(
            "Zentrale Master-Einstellungen fuer gebuendelte Module. "
            "Nextcloud-Werte werden direkt fuer kompatible Plugins gespiegelt."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs, 1)

        self._build_general_tab()
        self._build_nextcloud_tab()
        self._build_clickup_tab()
        self._build_database_tab()

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults,
            self,
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        restore_button = self.button_box.button(QDialogButtonBox.RestoreDefaults)
        if restore_button is not None:
            restore_button.clicked.connect(self._restore_defaults)
        layout.addWidget(self.button_box)

        self.set_values(plugin_controller.get_shared_settings())

    def _build_general_tab(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        general_group = QGroupBox("Allgemein", page)
        general_form = QFormLayout(general_group)

        self.workspace_root = QLineEdit(general_group)
        self.workspace_root.setPlaceholderText(
            "/Users/.../Nextcloud/Trassify Allgemein"
        )
        general_form.addRow("Standard-Arbeitsordner", self.workspace_root)
        layout.addWidget(general_group)

        hint = QLabel(
            "Nutze den Arbeitsordner als gemeinsame Basis fuer kuenftige Master-Module. "
            "Bestehende Fremdmodule uebernehmen diesen Wert erst, wenn sie explizit dafuer angebunden sind."
        )
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(hint)
        layout.addStretch(1)

        self.tabs.addTab(page, "Allgemein")

    def _build_nextcloud_tab(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        connection_group = QGroupBox("Nextcloud", page)
        connection_form = QFormLayout(connection_group)

        self.nextcloud_base_url = QLineEdit(connection_group)
        self.nextcloud_base_url.setPlaceholderText("https://nextcloud.example.com")
        self.nextcloud_user = QLineEdit(connection_group)
        self.nextcloud_user.setPlaceholderText("name@example.com")
        self.nextcloud_app_password = QLineEdit(connection_group)
        self.nextcloud_app_password.setEchoMode(QLineEdit.Password)
        self.nextcloud_folder_marker = QLineEdit(connection_group)
        self.nextcloud_folder_marker.setPlaceholderText("Nextcloud")
        self.local_nextcloud_roots = QPlainTextEdit(connection_group)
        self.local_nextcloud_roots.setPlaceholderText(
            "/Users/name/Nextcloud\n/Volumes/Team-Nextcloud"
        )
        self.local_nextcloud_roots.setTabChangesFocus(True)
        self.local_nextcloud_roots.setMinimumHeight(110)

        connection_form.addRow("Nextcloud URL", self.nextcloud_base_url)
        connection_form.addRow("Benutzer", self.nextcloud_user)
        connection_form.addRow("App-Passwort", self.nextcloud_app_password)
        connection_form.addRow("Lokale Sync-Roots", self.local_nextcloud_roots)
        connection_form.addRow("Ordner-Marker", self.nextcloud_folder_marker)
        layout.addWidget(connection_group)

        info = QLabel(
            "Diese Werte werden sofort in die globale Nutzerkonfiguration kompatibler Module gespiegelt. "
            "Aktuell betrifft das insbesondere AttributionButler."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addStretch(1)

        self.tabs.addTab(page, "Nextcloud")

    def _build_database_tab(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        connection_group = QGroupBox("Datenbank", page)
        connection_form = QFormLayout(connection_group)

        self.database_connection_name = QLineEdit(connection_group)
        self.database_connection_name.setPlaceholderText("Standard")
        self.database_host = QLineEdit(connection_group)
        self.database_host.setPlaceholderText("db.example.com")
        self.database_port = QLineEdit(connection_group)
        self.database_port.setPlaceholderText("5432")
        self.database_name = QLineEdit(connection_group)
        self.database_name.setPlaceholderText("postgres")
        self.database_schema = QLineEdit(connection_group)
        self.database_schema.setPlaceholderText("public")
        self.database_user = QLineEdit(connection_group)
        self.database_user.setPlaceholderText("geoserver")
        self.database_password = QLineEdit(connection_group)
        self.database_password.setEchoMode(QLineEdit.Password)
        self.database_sslmode = QComboBox(connection_group)
        self.database_sslmode.addItems(["prefer", "require", "disable", "allow", "verify-ca", "verify-full"])

        for widget in (
            self.database_host,
            self.database_port,
            self.database_name,
            self.database_schema,
            self.database_user,
            self.database_password,
        ):
            widget.textChanged.connect(self._update_database_preview)
        self.database_sslmode.currentTextChanged.connect(self._update_database_preview)

        connection_form.addRow("Verbindungsname", self.database_connection_name)
        connection_form.addRow("Host", self.database_host)
        connection_form.addRow("Port", self.database_port)
        connection_form.addRow("Datenbank", self.database_name)
        connection_form.addRow("Schema", self.database_schema)
        connection_form.addRow("Benutzer", self.database_user)
        connection_form.addRow("Passwort", self.database_password)
        connection_form.addRow("SSL-Modus", self.database_sslmode)
        layout.addWidget(connection_group)

        preview_group = QGroupBox("Vorschau", page)
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        preview_layout.setSpacing(8)

        preview_hint = QLabel(
            "Die URI kann von Master-kompatiblen Modulen direkt verwendet werden."
        )
        preview_hint.setWordWrap(True)
        preview_layout.addWidget(preview_hint)

        preview_row = QHBoxLayout()
        self.database_uri_preview = QLineEdit(preview_group)
        self.database_uri_preview.setReadOnly(True)
        preview_row.addWidget(self.database_uri_preview)
        preview_layout.addLayout(preview_row)

        layout.addWidget(preview_group)
        layout.addStretch(1)

        self.tabs.addTab(page, "Datenbank")

    def _build_clickup_tab(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        connection_group = QGroupBox("ClickUp", page)
        connection_form = QFormLayout(connection_group)

        self.clickup_api_token = QLineEdit(connection_group)
        self.clickup_api_token.setEchoMode(QLineEdit.Password)
        self.clickup_api_token.setPlaceholderText("pk_...")
        self.clickup_list_id = QLineEdit(connection_group)
        self.clickup_list_id.setPlaceholderText("901517875704")

        connection_form.addRow("Personal API Token", self.clickup_api_token)
        connection_form.addRow("Listen-ID", self.clickup_list_id)
        layout.addWidget(connection_group)

        info = QLabel(
            "Diese Werte werden lokal in den Master-Einstellungen gespeichert und von "
            "kompatiblen Plugins wie dem Projektstatus Butler verwendet. Der Token wird "
            "nicht im Git-Repository abgelegt."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addStretch(1)

        self.tabs.addTab(page, "ClickUp")

    def set_values(self, config: dict):
        values = dict(DEFAULT_SHARED_SETTINGS)
        values.update(config or {})

        self.workspace_root.setText(str(values.get("workspace_root", "")))

        self.nextcloud_base_url.setText(str(values.get("nextcloud_base_url", "")))
        self.nextcloud_user.setText(str(values.get("nextcloud_user", "")))
        self.nextcloud_app_password.setText(
            str(values.get("nextcloud_app_password", ""))
        )
        self.nextcloud_folder_marker.setText(
            str(values.get("nextcloud_folder_marker", ""))
        )
        self.local_nextcloud_roots.setPlainText(
            "\n".join(values.get("local_nextcloud_roots", []))
        )
        self.clickup_api_token.setText(str(values.get("clickup_api_token", "")))
        self.clickup_list_id.setText(str(values.get("clickup_list_id", "")))

        self.database_connection_name.setText(
            str(values.get("database_connection_name", ""))
        )
        self.database_host.setText(str(values.get("database_host", "")))
        self.database_port.setText(str(values.get("database_port", "")))
        self.database_name.setText(str(values.get("database_name", "")))
        self.database_schema.setText(str(values.get("database_schema", "")))
        self.database_user.setText(str(values.get("database_user", "")))
        self.database_password.setText(str(values.get("database_password", "")))
        self._set_combo_text(
            self.database_sslmode,
            str(values.get("database_sslmode", "prefer")),
        )
        self._update_database_preview()

    def values(self) -> dict:
        return {
            "workspace_root": self.workspace_root.text().strip(),
            "nextcloud_base_url": self.nextcloud_base_url.text().strip(),
            "nextcloud_user": self.nextcloud_user.text().strip(),
            "nextcloud_app_password": self.nextcloud_app_password.text(),
            "local_nextcloud_roots": [
                line.strip()
                for line in self.local_nextcloud_roots.toPlainText().splitlines()
                if line.strip()
            ],
            "nextcloud_folder_marker": self.nextcloud_folder_marker.text().strip(),
            "clickup_api_token": self.clickup_api_token.text().strip(),
            "clickup_list_id": self.clickup_list_id.text().strip(),
            "database_connection_name": self.database_connection_name.text().strip(),
            "database_host": self.database_host.text().strip(),
            "database_port": self.database_port.text().strip(),
            "database_name": self.database_name.text().strip(),
            "database_schema": self.database_schema.text().strip(),
            "database_user": self.database_user.text().strip(),
            "database_password": self.database_password.text(),
            "database_sslmode": self.database_sslmode.currentText().strip(),
        }

    def _restore_defaults(self):
        self.set_values(DEFAULT_SHARED_SETTINGS)

    def _set_combo_text(self, combo_box, text):
        index = combo_box.findText(text, Qt.MatchFixedString)
        if index >= 0:
            combo_box.setCurrentIndex(index)
            return
        combo_box.setCurrentIndex(0)

    def _update_database_preview(self):
        self.database_uri_preview.setText(build_postgres_ogr_uri(self.values()))
