import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import Qgis, QgsMessageLog

from .leaflet_export_dialog import LeafletExportDialog
from .leaflet_exporter import LeafletExporter


class WebmapExportPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self._plugin_menu = "&Webmap Export"
        self._plugin_dir = os.path.dirname(__file__)
        self._toolbar_registered = False
        self._plugin_menu_registered = False

    def initGui(self):
        self.action = QAction(
            QIcon(os.path.join(self._plugin_dir, "icon.svg")),
            "Webmap Export",
            self.iface.mainWindow(),
        )
        self.action.setObjectName("webmapExportAction")
        self.action.triggered.connect(self.run)

        if hasattr(self.iface, "addToolBarIcon"):
            self.iface.addToolBarIcon(self.action)
            self._toolbar_registered = True

        if hasattr(self.iface, "addPluginToMenu"):
            self.iface.addPluginToMenu(self._plugin_menu, self.action)
            self._plugin_menu_registered = True

    def unload(self):
        if self.action is None:
            return

        if self._toolbar_registered and hasattr(self.iface, "removeToolBarIcon"):
            self.iface.removeToolBarIcon(self.action)

        if self._plugin_menu_registered and hasattr(self.iface, "removePluginMenu"):
            self.iface.removePluginMenu(self._plugin_menu, self.action)

        self.action.deleteLater()
        self.action = None

    def run(self):
        dialog = LeafletExportDialog(
            os.path.join(self._plugin_dir, "icon.svg"),
            self.iface.mainWindow(),
        )
        if not dialog.exec_():
            return

        project_name = dialog.project_name()
        base_folder = dialog.base_folder()
        if not base_folder:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Webmap Export",
                "Bitte einen Basisordner auswaehlen.",
            )
            return

        options = dialog.export_options()
        try:
            exporter = LeafletExporter()
            result = exporter.export(project_name, base_folder, options)
        except Exception as exc:
            QgsMessageLog.logMessage(str(exc), "Webmap Export", Qgis.Critical)
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Webmap Export",
                str(exc),
            )
            return

        lines = [
            f"Data: {result['data_folder']}",
            f"SVG: {result['svg_folder']}",
            f"Export: {result['export_folder']}",
        ]
        if result.get("kml"):
            lines.append(f"KML: {result['kml']}")
        if result.get("status_json"):
            lines.append(f"Status JSON: {result['status_json']}")
        for key, path in sorted((result.get("zips") or {}).items()):
            lines.append(f"{key.upper()} ZIP: {path}")
        if result.get("geojson_manifest"):
            lines.append(f"GeoJSON Manifest: {result['geojson_manifest']}")
        if result.get("export_manifest"):
            lines.append(f"Export Manifest: {result['export_manifest']}")

        message = "Export abgeschlossen.\n" + "\n".join(lines)
        QgsMessageLog.logMessage(message, "Webmap Export", Qgis.Info)
        QMessageBox.information(
            self.iface.mainWindow(),
            "Webmap Export",
            message,
        )
