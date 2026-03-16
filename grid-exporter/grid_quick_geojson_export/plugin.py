import json
import os
from functools import partial

from qgis.PyQt.QtCore import QDate, QDateTime, Qt, QTime
from qgis.PyQt.QtWidgets import QAction, QFileDialog
from qgis.core import (
    QgsIdentifyContext,
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsMapLayerType,
    QgsProject,
)
from qgis.gui import QgsMapToolIdentify


class GridQuickGeoJsonExportPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.identify_tool = QgsMapToolIdentify(self.canvas)

    def initGui(self):
        self.canvas.contextMenuAboutToShow.connect(self._on_context_menu_about_to_show)

    def unload(self):
        try:
            self.canvas.contextMenuAboutToShow.disconnect(self._on_context_menu_about_to_show)
        except TypeError:
            # Already disconnected.
            pass

    def _on_context_menu_about_to_show(self, menu, event):
        vector_layers = [
            layer for layer in self.canvas.layers() if layer.type() == QgsMapLayerType.VectorLayer
        ]
        if not vector_layers:
            return

        results = []
        try:
            # QGIS 3.4x signature: identify(x, y, mode, layerType)
            results = self.identify_tool.identify(
                event.x(),
                event.y(),
                QgsMapToolIdentify.TopDownStopAtFirst,
                QgsMapToolIdentify.VectorLayer,
            )
        except TypeError:
            try:
                # Older signature with explicit layer list and context.
                results = self.identify_tool.identify(
                    event.x(),
                    event.y(),
                    vector_layers,
                    QgsMapToolIdentify.TopDownStopAtFirst,
                    QgsIdentifyContext(),
                )
            except TypeError:
                # Oldest known signature with explicit layer list.
                results = self.identify_tool.identify(
                    event.x(),
                    event.y(),
                    vector_layers,
                    QgsMapToolIdentify.TopDownStopAtFirst,
                )

        if not results:
            return

        result = results[0]
        layer = result.mLayer
        feature = result.mFeature

        action = QAction("Schnellexport GeoJSON", menu)
        action.triggered.connect(partial(self._export_feature, layer, feature))
        menu.addSeparator()
        menu.addAction(action)

    def _export_feature(self, layer, feature):
        base_dir = QgsProject.instance().homePath() or os.path.expanduser("~")
        default_name = f"{self._sanitize_filename(layer.name())}_{feature.id()}.geojson"
        default_path = os.path.join(base_dir, default_name)

        out_path, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            "Schnellexport GeoJSON",
            default_path,
            "GeoJSON (*.geojson *.json)",
        )
        if not out_path:
            return

        if not out_path.lower().endswith((".geojson", ".json")):
            out_path = f"{out_path}.geojson"

        try:
            geojson_doc = self._build_geojson(layer, feature)
            with open(out_path, "w", encoding="utf-8") as file_obj:
                json.dump(geojson_doc, file_obj, ensure_ascii=False, indent=2)

            self.iface.messageBar().pushMessage(
                "Schnellexport",
                f"Export erfolgreich: {out_path}",
                level=Qgis.Success,
                duration=4,
            )
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Schnellexport",
                f"Export fehlgeschlagen: {exc}",
                level=Qgis.Critical,
                duration=6,
            )

    def _build_geojson(self, layer, feature):
        geometry = QgsGeometry(feature.geometry())
        source_crs = layer.crs()
        target_crs = QgsCoordinateReferenceSystem("EPSG:4326")

        if source_crs.isValid() and source_crs != target_crs and not geometry.isNull():
            transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())
            geometry.transform(transform)

        geometry_json = None
        if not geometry.isNull() and not geometry.isEmpty():
            geometry_json = json.loads(geometry.asJson())
            geometry_json = self._force_polygon_geojson(geometry_json)

        properties = {}
        for field in layer.fields():
            properties[field.name()] = self._json_safe(feature[field.name()])

        feature_obj = {
            "type": "Feature",
            "id": feature.id(),
            "properties": properties,
            "geometry": geometry_json,
        }

        return {"type": "FeatureCollection", "features": [feature_obj]}

    def _json_safe(self, value):
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (QDate, QDateTime, QTime)):
            return value.toString(Qt.ISODate)
        return str(value)

    @staticmethod
    def _force_polygon_geojson(geometry_json):
        if not isinstance(geometry_json, dict):
            return geometry_json

        geom_type = geometry_json.get("type")
        if geom_type != "MultiPolygon":
            return geometry_json

        coords = geometry_json.get("coordinates")
        if not isinstance(coords, list) or not coords:
            return None

        # Convert MultiPolygon -> Polygon by taking the first polygon part.
        return {"type": "Polygon", "coordinates": coords[0]}

    @staticmethod
    def _sanitize_filename(name):
        safe = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in name.strip())
        return safe or "layer"
