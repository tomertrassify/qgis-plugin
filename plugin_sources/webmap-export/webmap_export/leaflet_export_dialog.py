import os

from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)
from qgis.core import QgsProject
from qgis.gui import QgsProjectionSelectionWidget

try:
    import processing as _processing
except Exception:
    _processing = None


class LeafletExportDialog(QDialog):
    SETTINGS_GROUP = "TrassifyToolbox"
    SETTINGS_KEY = "webmap_export/last_output"

    def __init__(self, icon_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Webmap Export")
        self.setWindowIcon(QIcon(icon_path))

        main_layout = QVBoxLayout(self)

        grid = QGridLayout()
        grid.addWidget(QLabel("Projektname:"), 0, 0)
        self.name_edit = QLineEdit(QgsProject.instance().baseName() or "webmap_export")
        grid.addWidget(self.name_edit, 0, 1, 1, 2)

        grid.addWidget(QLabel("Basisordner:"), 1, 0)
        self.folder_edit = QLineEdit(self._default_base_folder())
        self.browse_button = QPushButton("Ordner waehlen")
        self.browse_button.clicked.connect(self._choose_folder)
        grid.addWidget(self.folder_edit, 1, 1)
        grid.addWidget(self.browse_button, 1, 2)
        main_layout.addLayout(grid)

        self.exports_group = QGroupBox("ZIP-Exporte erzeugen")
        exports_layout = QVBoxLayout(self.exports_group)
        self.shp_checkbox = QCheckBox("Shapefiles (ZIP)")
        self.gpkg_checkbox = QCheckBox("GeoPackage (ZIP)")
        self.dxf_checkbox = QCheckBox("DXF (ZIP)")
        self.kml_checkbox = QCheckBox("KML (ZIP)")
        for checkbox in (
            self.shp_checkbox,
            self.gpkg_checkbox,
            self.dxf_checkbox,
            self.kml_checkbox,
        ):
            checkbox.setChecked(True)
            exports_layout.addWidget(checkbox)
        main_layout.addWidget(self.exports_group)

        status_layout = QGridLayout()
        status_layout.addWidget(QLabel("ClickUp-URL (optional):"), 0, 0)
        self.status_url_edit = QLineEdit()
        status_layout.addWidget(self.status_url_edit, 0, 1)
        main_layout.addLayout(status_layout)

        meta_layout = QGridLayout()
        meta_layout.addWidget(QLabel("Status (optional):"), 0, 0)
        self.status_combo = QComboBox()
        self.status_combo.addItem("Nicht gesetzt", "")
        self.status_combo.addItem("Neu", "Neu")
        self.status_combo.addItem("In Arbeit", "In Arbeit")
        self.status_combo.addItem("Fertig", "Fertig")
        meta_layout.addWidget(self.status_combo, 0, 1)

        meta_layout.addWidget(QLabel("Download-Token (optional):"), 1, 0)
        self.download_token_edit = QLineEdit()
        meta_layout.addWidget(self.download_token_edit, 1, 1)

        meta_layout.addWidget(QLabel("Baubeginn (YYYY-MM-DD):"), 2, 0)
        self.baubeginn_edit = QLineEdit()
        self.baubeginn_edit.setPlaceholderText("YYYY-MM-DD")
        meta_layout.addWidget(self.baubeginn_edit, 2, 1)
        main_layout.addLayout(meta_layout)

        advanced_toggle_layout = QHBoxLayout()
        self.show_advanced_checkbox = QCheckBox("Erweiterte Einstellungen anzeigen")
        advanced_toggle_layout.addWidget(self.show_advanced_checkbox)
        advanced_toggle_layout.addStretch(1)
        main_layout.addLayout(advanced_toggle_layout)

        self.advanced_group = QGroupBox()
        advanced_layout = QVBoxLayout(self.advanced_group)

        self.gpkg_group = QGroupBox("GeoPackage")
        gpkg_layout = QHBoxLayout(self.gpkg_group)
        self.gpkg_overwrite_checkbox = QCheckBox("Ueberschreiben")
        self.gpkg_style_checkbox = QCheckBox("Styles speichern")
        self.gpkg_metadata_checkbox = QCheckBox("Metadaten speichern")
        self.gpkg_overwrite_checkbox.setChecked(True)
        self.gpkg_style_checkbox.setChecked(True)
        self.gpkg_metadata_checkbox.setChecked(True)
        for widget in (
            self.gpkg_overwrite_checkbox,
            self.gpkg_style_checkbox,
            self.gpkg_metadata_checkbox,
        ):
            gpkg_layout.addWidget(widget)
        advanced_layout.addWidget(self.gpkg_group)

        self.dxf_group = QGroupBox("DXF")
        dxf_layout = QGridLayout(self.dxf_group)
        dxf_layout.addWidget(QLabel("Symbologiemodus:"), 0, 0)
        self.symbology_combo = QComboBox()
        self.symbology_combo.addItem("Symbol layer rendering", 2)
        self.symbology_combo.addItem("Feature symbology", 1)
        self.symbology_combo.addItem("No symbology", 0)
        dxf_layout.addWidget(self.symbology_combo, 0, 1)

        dxf_layout.addWidget(QLabel("Symbologieskalierung:"), 1, 0)
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(1, 100000)
        self.scale_spin.setValue(250)
        dxf_layout.addWidget(self.scale_spin, 1, 1)

        dxf_layout.addWidget(QLabel("Encoding:"), 2, 0)
        self.encoding_combo = QComboBox()
        for encoding in ("cp1252", "UTF-8", "ISO-8859-1"):
            self.encoding_combo.addItem(encoding, encoding)
        self.encoding_combo.setCurrentText("cp1252")
        dxf_layout.addWidget(self.encoding_combo, 2, 1)

        dxf_layout.addWidget(QLabel("Namensfeld (optional):"), 3, 0)
        self.dxf_name_field_edit = QLineEdit("Sparte")
        dxf_layout.addWidget(self.dxf_name_field_edit, 3, 1)

        dxf_layout.addWidget(QLabel("KBS (DXF):"), 4, 0)
        self.crs_widget = QgsProjectionSelectionWidget()
        self.crs_widget.setCrs(QgsProject.instance().crs())
        dxf_layout.addWidget(self.crs_widget, 4, 1)

        self.use_layer_title_checkbox = QCheckBox("Layertitel verwenden")
        self.mtext_checkbox = QCheckBox("MTEXT verwenden")
        self.zero_width_checkbox = QCheckBox("Linien mit Breite 0 exportieren")
        self.mtext_checkbox.setChecked(True)
        dxf_layout.addWidget(self.use_layer_title_checkbox, 5, 0, 1, 2)
        dxf_layout.addWidget(self.mtext_checkbox, 6, 0, 1, 2)
        dxf_layout.addWidget(self.zero_width_checkbox, 7, 0, 1, 2)
        advanced_layout.addWidget(self.dxf_group)

        self.kml_group = QGroupBox("KML")
        kml_layout = QGridLayout(self.kml_group)
        kml_layout.addWidget(QLabel("Namensfeld (optional):"), 0, 0)
        self.kml_name_field_edit = QLineEdit("Sparte")
        kml_layout.addWidget(self.kml_name_field_edit, 0, 1)

        kml_layout.addWidget(QLabel("Symbologieskalierung:"), 1, 0)
        self.kml_scale_spin = QSpinBox()
        self.kml_scale_spin.setRange(1, 100000)
        self.kml_scale_spin.setValue(250)
        kml_layout.addWidget(self.kml_scale_spin, 1, 1)
        advanced_layout.addWidget(self.kml_group)

        self.advanced_group.setVisible(False)
        self.show_advanced_checkbox.toggled.connect(self.advanced_group.setVisible)
        main_layout.addWidget(self.advanced_group)

        self.processing_hint_label = QLabel("")
        self.processing_hint_label.setWordWrap(True)
        main_layout.addWidget(self.processing_hint_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        if _processing is None:
            self.gpkg_checkbox.setChecked(False)
            self.dxf_checkbox.setChecked(False)
            self.gpkg_checkbox.setEnabled(False)
            self.dxf_checkbox.setEnabled(False)
            self.gpkg_group.setEnabled(False)
            self.dxf_group.setEnabled(False)
            self.processing_hint_label.setText(
                "Processing-Plugin fehlt: GPKG- und DXF-Export sind deaktiviert."
            )

        self._restore_settings()

    def _default_base_folder(self):
        project_home = str(QgsProject.instance().homePath() or "").strip()
        if project_home:
            return project_home
        return os.path.expanduser("~")

    def _choose_folder(self):
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Basisordner waehlen",
            self.folder_edit.text().strip() or self._default_base_folder(),
            QFileDialog.ShowDirsOnly,
        )
        if selected_dir:
            self.folder_edit.setText(selected_dir)
            self._save_settings(selected_dir)

    def _restore_settings(self):
        settings = QSettings()
        settings.beginGroup(self.SETTINGS_GROUP)
        last_path = str(settings.value(self.SETTINGS_KEY, "") or "").strip()
        settings.endGroup()
        if last_path:
            self.folder_edit.setText(last_path)

    def _save_settings(self, path):
        path = str(path or "").strip()
        if not path:
            return
        settings = QSettings()
        settings.beginGroup(self.SETTINGS_GROUP)
        settings.setValue(self.SETTINGS_KEY, path)
        settings.endGroup()

    def accept(self):
        self._save_settings(self.base_folder())
        super().accept()

    def project_name(self):
        return self.name_edit.text().strip() or "webmap_export"

    def base_folder(self):
        return self.folder_edit.text().strip()

    def export_options(self):
        options = {
            "exports": set(),
            "gpkg": {
                "OVERWRITE": self.gpkg_overwrite_checkbox.isChecked(),
                "SAVE_STYLE": self.gpkg_style_checkbox.isChecked(),
                "SAVE_METADATA": self.gpkg_metadata_checkbox.isChecked(),
            },
            "dxf": {
                "SYMBOLOGY_MODE": self.symbology_combo.currentData(),
                "SYMBOLOGY_SCALE": self.scale_spin.value(),
                "ENCODING": self.encoding_combo.currentData(),
                "CRS": self.crs_widget.crs(),
                "USE_LAYER_TITLE": self.use_layer_title_checkbox.isChecked(),
                "MTEXT": self.mtext_checkbox.isChecked(),
                "EXPORT_LINES_WITH_ZERO_WIDTH": self.zero_width_checkbox.isChecked(),
                "LABEL_FIELD": self.dxf_name_field_edit.text().strip() or None,
            },
            "kml": {
                "DISABLED": not self.kml_checkbox.isChecked(),
                "NAME_FIELD": self.kml_name_field_edit.text().strip() or None,
                "SYMBOLOGY_SCALE": self.kml_scale_spin.value(),
            },
            "status_url": self.status_url_edit.text().strip(),
            "status": self.status_combo.currentData() or "",
            "download_token": self.download_token_edit.text().strip(),
            "baubeginn": self.baubeginn_edit.text().strip(),
            "zip": True,
            "cleanup_after_zip": True,
        }
        if self.shp_checkbox.isChecked():
            options["exports"].add("shp")
        if self.gpkg_checkbox.isChecked():
            options["exports"].add("gpkg")
        if self.dxf_checkbox.isChecked():
            options["exports"].add("dxf")
        return options
