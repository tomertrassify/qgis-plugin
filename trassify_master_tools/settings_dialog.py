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

from .shared_settings import (
    DEFAULT_NEXTCLOUD_CATALOG_ROOT,
    DEFAULT_SHARED_SETTINGS,
    build_postgres_ogr_uri,
)


class MasterSettingsWidget(QWidget):
    def __init__(self, plugin_controller, parent=None):
        super().__init__(parent)
        self.plugin_controller = plugin_controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.intro_label = QLabel(self)
        self.intro_label.setWordWrap(True)
        layout.addWidget(self.intro_label)

        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs, 1)

        self._build_general_tab()
        self._build_nextcloud_tab()
        self._build_clickup_tab()
        self._build_database_tab()

        self.apply_language()
        self.set_values(plugin_controller.get_shared_settings())

    def apply_language(self):
        self.intro_label.setText(self._tr("settings.intro"))

        self.general_group.setTitle(self._tr("settings.group.general"))
        self._set_form_label(self.general_form, self.workspace_root, self._tr("settings.field.workspace_root"))
        self.general_hint_label.setText(self._tr("settings.hint.general"))
        self.tabs.setTabText(self.tabs.indexOf(self.general_page), self._tr("settings.tab.general"))

        self.nextcloud_group.setTitle(self._tr("settings.group.nextcloud"))
        self._set_form_label(self.nextcloud_form, self.nextcloud_base_url, self._tr("settings.field.nextcloud_url"))
        self._set_form_label(self.nextcloud_form, self.nextcloud_user, self._tr("settings.field.user"))
        self._set_form_label(self.nextcloud_form, self.nextcloud_app_password, self._tr("settings.field.app_password"))
        self._set_form_label(self.nextcloud_form, self.nextcloud_catalog_root, self._tr("settings.field.catalog_root"))
        self._set_form_label(self.nextcloud_form, self.local_nextcloud_roots, self._tr("settings.field.local_roots"))
        self._set_form_label(self.nextcloud_form, self.nextcloud_folder_marker, self._tr("settings.field.folder_marker"))
        self.nextcloud_info_label.setText(
            self._tr(
                "settings.hint.nextcloud",
                catalog_root=DEFAULT_NEXTCLOUD_CATALOG_ROOT,
            )
        )
        self.tabs.setTabText(self.tabs.indexOf(self.nextcloud_page), self._tr("settings.tab.nextcloud"))

        self.database_group.setTitle(self._tr("settings.group.database"))
        self._set_form_label(self.database_form, self.database_connection_name, self._tr("settings.field.connection_name"))
        self._set_form_label(self.database_form, self.database_host, self._tr("settings.field.host"))
        self._set_form_label(self.database_form, self.database_port, self._tr("settings.field.port"))
        self._set_form_label(self.database_form, self.database_name, self._tr("settings.field.database"))
        self._set_form_label(self.database_form, self.database_schema, self._tr("settings.field.schema"))
        self._set_form_label(self.database_form, self.database_user, self._tr("settings.field.db_user"))
        self._set_form_label(self.database_form, self.database_password, self._tr("settings.field.db_password"))
        self._set_form_label(self.database_form, self.database_sslmode, self._tr("settings.field.ssl_mode"))
        self.database_preview_group.setTitle(self._tr("settings.group.preview"))
        self.database_preview_hint.setText(self._tr("settings.hint.database_preview"))
        self.tabs.setTabText(self.tabs.indexOf(self.database_page), self._tr("settings.tab.database"))

        self.clickup_group.setTitle(self._tr("settings.group.clickup"))
        self._set_form_label(self.clickup_form, self.clickup_api_token, self._tr("settings.field.clickup_token"))
        self._set_form_label(self.clickup_form, self.clickup_list_id, self._tr("settings.field.clickup_list_id"))
        self.clickup_info_label.setText(self._tr("settings.hint.clickup"))
        self.tabs.setTabText(self.tabs.indexOf(self.clickup_page), self._tr("settings.tab.clickup"))

    def _build_general_tab(self):
        self.general_page = QWidget(self)
        layout = QVBoxLayout(self.general_page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.general_group = QGroupBox(self.general_page)
        self.general_form = QFormLayout(self.general_group)

        self.workspace_root = QLineEdit(self.general_group)
        self.workspace_root.setPlaceholderText("/Users/.../Nextcloud/Trassify Allgemein")
        self.general_form.addRow("", self.workspace_root)
        layout.addWidget(self.general_group)

        self.general_hint_label = QLabel(self.general_page)
        self.general_hint_label.setWordWrap(True)
        self.general_hint_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(self.general_hint_label)
        layout.addStretch(1)

        self.tabs.addTab(self.general_page, "")

    def _build_nextcloud_tab(self):
        self.nextcloud_page = QWidget(self)
        layout = QVBoxLayout(self.nextcloud_page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.nextcloud_group = QGroupBox(self.nextcloud_page)
        self.nextcloud_form = QFormLayout(self.nextcloud_group)

        self.nextcloud_base_url = QLineEdit(self.nextcloud_group)
        self.nextcloud_base_url.setPlaceholderText("https://nextcloud.example.com")
        self.nextcloud_user = QLineEdit(self.nextcloud_group)
        self.nextcloud_user.setPlaceholderText("name@example.com")
        self.nextcloud_app_password = QLineEdit(self.nextcloud_group)
        self.nextcloud_app_password.setEchoMode(QLineEdit.Password)
        self.nextcloud_catalog_root = QLineEdit(self.nextcloud_group)
        self.nextcloud_catalog_root.setPlaceholderText(DEFAULT_NEXTCLOUD_CATALOG_ROOT)
        self.nextcloud_folder_marker = QLineEdit(self.nextcloud_group)
        self.nextcloud_folder_marker.setPlaceholderText("Nextcloud")
        self.local_nextcloud_roots = QPlainTextEdit(self.nextcloud_group)
        self.local_nextcloud_roots.setPlaceholderText(
            "/Users/name/Nextcloud\n/Volumes/Team-Nextcloud"
        )
        self.local_nextcloud_roots.setTabChangesFocus(True)
        self.local_nextcloud_roots.setMinimumHeight(110)

        self.nextcloud_form.addRow("", self.nextcloud_base_url)
        self.nextcloud_form.addRow("", self.nextcloud_user)
        self.nextcloud_form.addRow("", self.nextcloud_app_password)
        self.nextcloud_form.addRow("", self.nextcloud_catalog_root)
        self.nextcloud_form.addRow("", self.local_nextcloud_roots)
        self.nextcloud_form.addRow("", self.nextcloud_folder_marker)
        layout.addWidget(self.nextcloud_group)

        self.nextcloud_info_label = QLabel(self.nextcloud_page)
        self.nextcloud_info_label.setWordWrap(True)
        layout.addWidget(self.nextcloud_info_label)
        layout.addStretch(1)

        self.tabs.addTab(self.nextcloud_page, "")

    def _build_database_tab(self):
        self.database_page = QWidget(self)
        layout = QVBoxLayout(self.database_page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.database_group = QGroupBox(self.database_page)
        self.database_form = QFormLayout(self.database_group)

        self.database_connection_name = QLineEdit(self.database_group)
        self.database_connection_name.setPlaceholderText("Standard")
        self.database_host = QLineEdit(self.database_group)
        self.database_host.setPlaceholderText("db.example.com")
        self.database_port = QLineEdit(self.database_group)
        self.database_port.setPlaceholderText("5432")
        self.database_name = QLineEdit(self.database_group)
        self.database_name.setPlaceholderText("postgres")
        self.database_schema = QLineEdit(self.database_group)
        self.database_schema.setPlaceholderText("public")
        self.database_user = QLineEdit(self.database_group)
        self.database_user.setPlaceholderText("geoserver")
        self.database_password = QLineEdit(self.database_group)
        self.database_password.setEchoMode(QLineEdit.Password)
        self.database_sslmode = QComboBox(self.database_group)
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

        self.database_form.addRow("", self.database_connection_name)
        self.database_form.addRow("", self.database_host)
        self.database_form.addRow("", self.database_port)
        self.database_form.addRow("", self.database_name)
        self.database_form.addRow("", self.database_schema)
        self.database_form.addRow("", self.database_user)
        self.database_form.addRow("", self.database_password)
        self.database_form.addRow("", self.database_sslmode)
        layout.addWidget(self.database_group)

        self.database_preview_group = QGroupBox(self.database_page)
        preview_layout = QVBoxLayout(self.database_preview_group)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        preview_layout.setSpacing(8)

        self.database_preview_hint = QLabel(self.database_preview_group)
        self.database_preview_hint.setWordWrap(True)
        preview_layout.addWidget(self.database_preview_hint)

        preview_row = QHBoxLayout()
        self.database_uri_preview = QLineEdit(self.database_preview_group)
        self.database_uri_preview.setReadOnly(True)
        preview_row.addWidget(self.database_uri_preview)
        preview_layout.addLayout(preview_row)

        layout.addWidget(self.database_preview_group)
        layout.addStretch(1)

        self.tabs.addTab(self.database_page, "")

    def _build_clickup_tab(self):
        self.clickup_page = QWidget(self)
        layout = QVBoxLayout(self.clickup_page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.clickup_group = QGroupBox(self.clickup_page)
        self.clickup_form = QFormLayout(self.clickup_group)

        self.clickup_api_token = QLineEdit(self.clickup_group)
        self.clickup_api_token.setEchoMode(QLineEdit.Password)
        self.clickup_api_token.setPlaceholderText("pk_...")
        self.clickup_list_id = QLineEdit(self.clickup_group)
        self.clickup_list_id.setPlaceholderText("901517875704")

        self.clickup_form.addRow("", self.clickup_api_token)
        self.clickup_form.addRow("", self.clickup_list_id)
        layout.addWidget(self.clickup_group)

        self.clickup_info_label = QLabel(self.clickup_page)
        self.clickup_info_label.setWordWrap(True)
        layout.addWidget(self.clickup_info_label)
        layout.addStretch(1)

        self.tabs.addTab(self.clickup_page, "")

    def set_values(self, config: dict):
        values = dict(DEFAULT_SHARED_SETTINGS)
        values.update(config or {})

        self.workspace_root.setText(str(values.get("workspace_root", "")))

        self.nextcloud_base_url.setText(str(values.get("nextcloud_base_url", "")))
        self.nextcloud_user.setText(str(values.get("nextcloud_user", "")))
        self.nextcloud_app_password.setText(
            str(values.get("nextcloud_app_password", ""))
        )
        self.nextcloud_catalog_root.setText(
            str(values.get("nextcloud_catalog_root", ""))
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
            "nextcloud_catalog_root": self.nextcloud_catalog_root.text().strip(),
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

    def restore_defaults(self):
        self.set_values(DEFAULT_SHARED_SETTINGS)

    def _set_combo_text(self, combo_box, text):
        index = combo_box.findText(text, Qt.MatchFixedString)
        if index >= 0:
            combo_box.setCurrentIndex(index)
            return
        combo_box.setCurrentIndex(0)

    def _update_database_preview(self):
        self.database_uri_preview.setText(build_postgres_ogr_uri(self.values()))

    def _set_form_label(self, form_layout, field, text):
        label = form_layout.labelForField(field)
        if label is not None:
            label.setText(text)

    def _tr(self, key, **kwargs):
        return self.plugin_controller.tr(key, **kwargs)


class MasterSettingsDialog(QDialog):
    def __init__(self, plugin_controller, parent=None):
        super().__init__(parent)
        self.plugin_controller = plugin_controller

        self.setWindowIcon(QIcon(str(plugin_controller.plugin_dir / "icon.svg")))
        self.resize(760, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.settings_widget = MasterSettingsWidget(plugin_controller, self)
        layout.addWidget(self.settings_widget, 1)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults,
            self,
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        restore_button = self.button_box.button(QDialogButtonBox.RestoreDefaults)
        if restore_button is not None:
            restore_button.clicked.connect(self.settings_widget.restore_defaults)
        layout.addWidget(self.button_box)

        self.apply_language()

    def apply_language(self):
        self.setWindowTitle(self.plugin_controller.tr("settings.window_title"))
        self.settings_widget.apply_language()

        save_button = self.button_box.button(QDialogButtonBox.Save)
        if save_button is not None:
            save_button.setText(self.plugin_controller.tr("settings.button.save"))

        cancel_button = self.button_box.button(QDialogButtonBox.Cancel)
        if cancel_button is not None:
            cancel_button.setText(self.plugin_controller.tr("settings.button.cancel"))

        restore_button = self.button_box.button(QDialogButtonBox.RestoreDefaults)
        if restore_button is not None:
            restore_button.setText(self.plugin_controller.tr("settings.button.restore"))

    def values(self):
        return self.settings_widget.values()
