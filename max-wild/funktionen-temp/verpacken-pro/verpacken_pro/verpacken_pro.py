# -*- coding: utf-8 -*-

import os
import re
from datetime import datetime

from qgis.PyQt.QtCore import QFile, QIODevice
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QInputDialog, QMenu, QMessageBox
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsDxfExport,
    QgsLayerTreeLayer,
    QgsMapLayerUtils,
    QgsMapSettings,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsRendererCategory,
    QgsSymbol,
    QgsVectorFileWriter,
)

try:
    import processing
except Exception:  # pragma: no cover - runtime fallback in QGIS
    processing = None


PLUGIN_MENU = "Export Pro"
PLUGIN_TITLE = "Export Pro"
ACTION_TITLE = "Export Pro"
KML_STYLE_FIELD = "Sparte"

EXPORT_FORMATS = (
    ("gpkg", "GeoPackage (*.gpkg)"),
    ("dxf", "DXF (*.dxf)"),
    ("shp", "Ordner mit ESRI Shapefiles"),
    ("kml", "KML (*.kml)"),
    ("geojson", "GeoJSON (*.geojson)"),
)

FORMAT_LABELS = {key: label for key, label in EXPORT_FORMATS}
FILE_EXTENSIONS = {
    "gpkg": ".gpkg",
    "dxf": ".dxf",
    "kml": ".kml",
    "geojson": ".geojson",
}

CATEGORY_COLORS = (
    "#0B6E4F",
    "#C84C09",
    "#275DAD",
    "#A23B72",
    "#3B8B5C",
    "#B56576",
    "#5D576B",
    "#C28840",
    "#2A7F62",
    "#7B3F00",
    "#4E79A7",
    "#D1495B",
)


class ExportProPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.layer_tree_view = None
        self.selection_model = None

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        self.action = QAction(QIcon(icon_path), ACTION_TITLE, self.iface.mainWindow())
        self.action.triggered.connect(self.export_selected_layers)
        self.action.setEnabled(False)

        self.iface.addPluginToMenu(PLUGIN_MENU, self.action)

        self.layer_tree_view = getattr(self.iface, "layerTreeView", lambda: None)()
        if self.layer_tree_view and hasattr(self.layer_tree_view, "contextMenuAboutToShow"):
            self.layer_tree_view.contextMenuAboutToShow.connect(self._on_context_menu_about_to_show)
            self.selection_model = self.layer_tree_view.selectionModel()
            if self.selection_model:
                self.selection_model.selectionChanged.connect(self._refresh_action_state)
            self._refresh_action_state()
        else:
            self.action.setEnabled(True)

    def unload(self):
        if self.selection_model:
            try:
                self.selection_model.selectionChanged.disconnect(self._refresh_action_state)
            except Exception:
                pass
            self.selection_model = None

        if self.layer_tree_view and hasattr(self.layer_tree_view, "contextMenuAboutToShow"):
            try:
                self.layer_tree_view.contextMenuAboutToShow.disconnect(self._on_context_menu_about_to_show)
            except Exception:
                pass
            self.layer_tree_view = None

        if self.action:
            self.iface.removePluginMenu(PLUGIN_MENU, self.action)
            self.action.deleteLater()
            self.action = None

    def _refresh_action_state(self, *_args):
        if self.action:
            self.action.setEnabled(bool(self._selected_layers(allow_active_fallback=False)))

    def _on_context_menu_about_to_show(self, menu: QMenu):
        if not self.action:
            return

        selected_layers = self._selected_layers(allow_active_fallback=False)
        self.action.setEnabled(bool(selected_layers))
        if not selected_layers:
            return

        if self.action not in menu.actions():
            menu.addSeparator()
            menu.addAction(self.action)

    def _selected_layers(self, allow_active_fallback=False):
        layers = []
        seen_ids = set()

        if self.layer_tree_view:
            try:
                selected_nodes = self.layer_tree_view.selectedNodes()
            except Exception:
                selected_nodes = []

            for node in selected_nodes:
                if not isinstance(node, QgsLayerTreeLayer):
                    continue
                layer = node.layer()
                if not layer:
                    continue
                if layer.id() in seen_ids:
                    continue
                seen_ids.add(layer.id())
                layers.append(layer)

        if not layers and allow_active_fallback:
            active_layer = self.iface.activeLayer()
            if active_layer:
                layers.append(active_layer)

        return layers

    def _push_message(self, message, level=Qgis.Info, duration=6):
        self.iface.messageBar().pushMessage(
            PLUGIN_TITLE,
            message,
            level=level,
            duration=duration,
        )

    def _default_output_root(self):
        project_home = QgsProject.instance().homePath()
        base_dir = project_home if project_home else os.path.expanduser("~")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(base_dir, f"export_{stamp}")

    def _default_output_path(self, format_key, layer_count):
        root = self._default_output_root()
        if format_key in FILE_EXTENSIONS and (format_key not in ("kml", "geojson") or layer_count == 1):
            return f"{root}{FILE_EXTENSIONS[format_key]}"
        return f"{root}_{format_key}"

    def _choose_export_format(self):
        items = [label for _key, label in EXPORT_FORMATS]
        choice, accepted = QInputDialog.getItem(
            self.iface.mainWindow(),
            "Exportformat waehlen",
            "Zielformat:",
            items,
            0,
            False,
        )
        if not accepted or not choice:
            return None

        for key, label in EXPORT_FORMATS:
            if label == choice:
                return key

        return None

    def _choose_directory(self, title, default_path):
        dialog = QFileDialog(self.iface.mainWindow(), title, os.path.dirname(default_path) or default_path)
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, False)
        dialog.selectFile(os.path.basename(default_path))
        if not dialog.exec():
            return ""

        selected_files = dialog.selectedFiles()
        return selected_files[0] if selected_files else ""

    def _choose_target_path(self, format_key, layer_count):
        default_path = self._default_output_path(format_key, layer_count)

        if format_key == "gpkg":
            path, _ = QFileDialog.getSaveFileName(
                self.iface.mainWindow(),
                "GeoPackage speichern",
                default_path,
                "GeoPackage (*.gpkg)",
            )
            if path and not path.lower().endswith(".gpkg"):
                path = f"{path}.gpkg"
            return path

        if format_key == "dxf":
            path, _ = QFileDialog.getSaveFileName(
                self.iface.mainWindow(),
                "DXF speichern",
                default_path,
                "DXF (*.dxf)",
            )
            if path and not path.lower().endswith(".dxf"):
                path = f"{path}.dxf"
            return path

        if format_key == "shp":
            return self._choose_directory("Zielordner fuer Shapefiles waehlen", default_path)

        if format_key == "kml" and layer_count == 1:
            path, _ = QFileDialog.getSaveFileName(
                self.iface.mainWindow(),
                "KML speichern",
                default_path,
                "KML (*.kml)",
            )
            if path and not path.lower().endswith(".kml"):
                path = f"{path}.kml"
            return path

        if format_key == "geojson" and layer_count == 1:
            path, _ = QFileDialog.getSaveFileName(
                self.iface.mainWindow(),
                "GeoJSON speichern",
                default_path,
                "GeoJSON (*.geojson)",
            )
            if path and not path.lower().endswith(".geojson"):
                path = f"{path}.geojson"
            return path

        title = "Zielordner waehlen"
        if format_key == "kml":
            title = "Zielordner fuer KML-Dateien waehlen"
        elif format_key == "geojson":
            title = "Zielordner fuer GeoJSON-Dateien waehlen"
        return self._choose_directory(title, default_path)

    def _confirm_overwrite(self, paths, message):
        existing_paths = [path for path in paths if os.path.exists(path)]
        if not existing_paths:
            return True

        answer = QMessageBox.question(
            self.iface.mainWindow(),
            "Datei existiert bereits",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def _safe_name(self, name):
        safe_name = QgsMapLayerUtils.launderLayerName(name or "layer")
        safe_name = safe_name.replace(" ", "_")
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", safe_name)
        safe_name = safe_name.strip("._")
        return safe_name or "layer"

    def _unique_name(self, base_name, used_names):
        candidate = self._safe_name(base_name)
        if candidate.lower() not in used_names:
            used_names.add(candidate.lower())
            return candidate

        suffix = 2
        while True:
            derived = f"{candidate}_{suffix}"
            if derived.lower() not in used_names:
                used_names.add(derived.lower())
                return derived
            suffix += 1

    def _vector_export_layers(self, layers):
        vector_layers = []
        skipped = []

        for layer in layers:
            if layer.type() != Qgis.LayerType.Vector:
                skipped.append(f"{layer.name()} (kein Vektorlayer)")
                continue
            if not layer.isSpatial():
                skipped.append(f"{layer.name()} (ohne Geometrie)")
                continue
            vector_layers.append(layer)

        return vector_layers, skipped

    def _ensure_directory(self, directory):
        try:
            os.makedirs(directory, exist_ok=True)
        except Exception as exc:
            self._push_message(
                f"Ordner konnte nicht erstellt werden: {exc}",
                level=Qgis.Critical,
                duration=10,
            )
            return False

        if not os.path.isdir(directory):
            self._push_message(
                "Zielpfad ist kein Ordner.",
                level=Qgis.Critical,
                duration=8,
            )
            return False

        return True

    def _current_symbology_scale(self):
        canvas = getattr(self.iface, "mapCanvas", lambda: None)()
        if canvas:
            try:
                scale = float(canvas.scale())
                if scale > 0:
                    return scale
            except Exception:
                pass
        return 250.0

    def _write_vector_layer(
        self,
        layer,
        output_path,
        driver_name,
        *,
        layer_name=None,
        file_encoding="UTF-8",
        symbology_export=None,
        symbology_scale=None,
        action_on_existing=None,
        coordinate_transform=None,
        layer_options=None,
        datasource_options=None,
        save_metadata=True,
    ):
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = driver_name
        options.fileEncoding = file_encoding
        options.layerName = layer_name or layer.name()
        options.onlySelectedFeatures = False
        options.saveMetadata = save_metadata

        if symbology_export is not None:
            options.symbologyExport = symbology_export
        if symbology_scale is not None:
            options.symbologyScale = float(symbology_scale)
        if action_on_existing is not None:
            options.actionOnExistingFile = action_on_existing
        if coordinate_transform is not None:
            options.ct = coordinate_transform
        if layer_options:
            options.layerOptions = list(layer_options)
        if datasource_options:
            options.datasourceOptions = list(datasource_options)

        error, _new_file, _new_layer, error_message = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            output_path,
            QgsProject.instance().transformContext(),
            options,
        )
        if int(error) != 0:
            return error_message or "Unbekannter Exportfehler."
        return None

    def _save_qml_sidecar(self, layer, output_path):
        style_path = f"{os.path.splitext(output_path)[0]}.qml"
        _message, ok = layer.saveNamedStyle(style_path)
        return ok

    def _show_detailed_issues(self, title, lines, icon):
        if not lines:
            return

        box = QMessageBox(self.iface.mainWindow())
        box.setWindowTitle(title)
        box.setIcon(icon)
        box.setText("\n".join(lines[:12]))
        if len(lines) > 12:
            box.setInformativeText(f"Weitere Eintraege: {len(lines) - 12}")
        box.exec()

    def _summarize_export(self, format_key, target_path, success_count, errors, skipped):
        label = FORMAT_LABELS.get(format_key, format_key)

        if success_count and not errors:
            message = f"{label} exportiert: {target_path}"
            if skipped:
                message += f" | {len(skipped)} Layer uebersprungen"
            self._push_message(message, level=Qgis.Success, duration=8)
        elif success_count:
            self._push_message(
                f"{label} teilweise exportiert: {target_path}",
                level=Qgis.Warning,
                duration=10,
            )
        else:
            self._push_message(
                f"{label} konnte nicht exportiert werden.",
                level=Qgis.Critical,
                duration=10,
            )

        if errors:
            self._show_detailed_issues("Exportfehler", errors, QMessageBox.Critical)
        if skipped:
            self._show_detailed_issues("Layer uebersprungen", skipped, QMessageBox.Warning)

    def _build_package_params(self, algorithm, layers, output_path, overwrite):
        params = {
            "LAYERS": layers,
            "OUTPUT": output_path,
        }

        available = {definition.name() for definition in algorithm.parameterDefinitions()}
        optional_flags = {
            "OVERWRITE": overwrite,
            "SAVE_STYLES": True,
            "SAVE_METADATA": True,
            "SELECTED_FEATURES_ONLY": False,
        }
        for key, value in optional_flags.items():
            if key in available:
                params[key] = value
        return params

    def _export_geopackage(self, layers, output_path):
        overwrite = os.path.exists(output_path)
        if overwrite and not self._confirm_overwrite(
            [output_path],
            "Die Datei existiert bereits. Ueberschreiben?",
        ):
            return

        if processing is not None:
            algorithm = QgsApplication.processingRegistry().algorithmById("native:package")
            if algorithm is not None:
                params = self._build_package_params(algorithm, layers, output_path, overwrite)
                context = QgsProcessingContext()
                context.setProject(QgsProject.instance())
                feedback = QgsProcessingFeedback()
                try:
                    processing.run("native:package", params, context=context, feedback=feedback)
                except Exception as exc:
                    self._push_message(
                        f"Fehler beim GeoPackage-Export: {exc}",
                        level=Qgis.Critical,
                        duration=10,
                    )
                    return

                self._push_message(
                    f"GeoPackage erstellt: {output_path}",
                    level=Qgis.Success,
                    duration=8,
                )
                return

        vector_layers, skipped = self._vector_export_layers(layers)
        if not vector_layers:
            self._push_message(
                "Kein geeigneter Vektorlayer fuer den GeoPackage-Export vorhanden.",
                level=Qgis.Critical,
                duration=8,
            )
            if skipped:
                self._show_detailed_issues("Layer uebersprungen", skipped, QMessageBox.Warning)
            return

        errors = []
        used_names = set()
        success_count = 0

        for index, layer in enumerate(vector_layers):
            action = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
            if index > 0:
                action = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer

            error = self._write_vector_layer(
                layer,
                output_path,
                "GPKG",
                layer_name=self._unique_name(layer.name(), used_names),
                symbology_export=Qgis.FeatureSymbologyExport.PerSymbolLayer,
                symbology_scale=self._current_symbology_scale(),
                action_on_existing=action,
                save_metadata=True,
            )
            if error:
                errors.append(f"{layer.name()}: {error}")
                continue
            success_count += 1

        self._summarize_export("gpkg", output_path, success_count, errors, skipped)

    def _export_dxf(self, layers, output_path):
        if os.path.exists(output_path) and not self._confirm_overwrite(
            [output_path],
            "Die DXF-Datei existiert bereits. Ueberschreiben?",
        ):
            return

        vector_layers, skipped = self._vector_export_layers(layers)
        if not vector_layers:
            self._push_message(
                "Kein geeigneter Vektorlayer fuer den DXF-Export vorhanden.",
                level=Qgis.Critical,
                duration=8,
            )
            if skipped:
                self._show_detailed_issues("Layer uebersprungen", skipped, QMessageBox.Warning)
            return

        project = QgsProject.instance()
        project_crs = project.crs()
        if not project_crs.isValid():
            project_crs = vector_layers[0].crs()

        map_settings = QgsMapSettings()
        map_settings.setTransformContext(project.transformContext())
        map_settings.setLayers(vector_layers)
        map_settings.setDestinationCrs(project_crs)
        map_settings.setExtent(
            QgsMapLayerUtils.combinedExtent(vector_layers, project_crs, project.transformContext())
        )

        exporter = QgsDxfExport()
        exporter.setMapSettings(map_settings)
        exporter.setDestinationCrs(project_crs)
        exporter.setSymbologyExport(Qgis.FeatureSymbologyExport.PerSymbolLayer)
        exporter.setSymbologyScale(250.0)
        exporter.addLayers([QgsDxfExport.DxfLayer(layer) for layer in vector_layers])

        qfile = QFile(output_path)
        if not qfile.open(QIODevice.WriteOnly | QIODevice.Truncate):
            self._push_message(
                f"DXF-Datei konnte nicht geschrieben werden: {qfile.errorString()}",
                level=Qgis.Critical,
                duration=10,
            )
            return

        dxf_encoding = QgsDxfExport.dxfEncoding("CP1252") or "CP1252"
        result = exporter.writeToFile(qfile, dxf_encoding)
        qfile.close()

        if int(result) != 0:
            feedback = exporter.feedbackMessage() or "Unbekannter DXF-Fehler."
            self._push_message(
                f"Fehler beim DXF-Export: {feedback}",
                level=Qgis.Critical,
                duration=10,
            )
            if skipped:
                self._show_detailed_issues("Layer uebersprungen", skipped, QMessageBox.Warning)
            return

        self._summarize_export("dxf", output_path, 1, [], skipped)

    def _ask_for_kml_style_field(self, layer):
        if layer.fields().indexOf(KML_STYLE_FIELD) >= 0:
            return KML_STYLE_FIELD

        box = QMessageBox(self.iface.mainWindow())
        box.setWindowTitle("KML-Darstellung")
        box.setIcon(QMessageBox.Warning)
        box.setText(f'Layer "{layer.name()}" hat kein Feld "{KML_STYLE_FIELD}".')
        box.setInformativeText("Soll ein anderes Attribut fuer die Darstellung verwendet werden?")
        alternative_button = box.addButton("Alternatives Feld...", QMessageBox.ActionRole)
        ignore_button = box.addButton("Ignorieren", QMessageBox.AcceptRole)
        cancel_button = box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(ignore_button)
        box.exec()

        clicked_button = box.clickedButton()
        if clicked_button == alternative_button:
            field_names = layer.fields().names()
            if not field_names:
                return "__ignore__"
            field_name, accepted = QInputDialog.getItem(
                self.iface.mainWindow(),
                "Alternatives Feld waehlen",
                f'Darstellung fuer "{layer.name()}" nach folgendem Feld:',
                field_names,
                0,
                False,
            )
            if not accepted or not field_name:
                return "__cancel__"
            return field_name

        if clicked_button == ignore_button:
            return "__ignore__"
        if clicked_button == cancel_button:
            return "__cancel__"
        return "__cancel__"

    def _build_categorized_renderer(self, layer, field_name):
        if layer.fields().indexOf(field_name) < 0:
            return None

        values = []
        seen = set()
        for feature in layer.getFeatures():
            value = feature[field_name]
            if value is None or value == "":
                continue
            key = f"{type(value).__name__}:{value}"
            if key in seen:
                continue
            seen.add(key)
            values.append(value)

        values.sort(key=lambda value: str(value).casefold())
        if not values:
            return None

        base_symbol = QgsSymbol.defaultSymbol(layer.geometryType())
        if base_symbol is None:
            return None

        categories = []
        for index, value in enumerate(values):
            symbol = base_symbol.clone()
            symbol.setColor(QColor(CATEGORY_COLORS[index % len(CATEGORY_COLORS)]))
            categories.append(QgsRendererCategory(value, symbol, str(value)))

        renderer = QgsCategorizedSymbolRenderer(field_name, categories)
        renderer.sortByLabel()
        return renderer

    def _prepare_kml_layer(self, layer):
        field_name = self._ask_for_kml_style_field(layer)
        if field_name == "__cancel__":
            return None, False
        if field_name == "__ignore__":
            return layer, True

        export_layer = layer.clone()
        if export_layer is None:
            return layer, True

        renderer = self._build_categorized_renderer(export_layer, field_name)
        if renderer is None:
            self._push_message(
                f'Feld "{field_name}" konnte fuer "{layer.name()}" nicht kategorisiert werden. Aktuelle Darstellung wird verwendet.',
                level=Qgis.Warning,
                duration=8,
            )
            return layer, True

        export_layer.setRenderer(renderer)
        return export_layer, True

    def _coordinate_transform(self, layer, destination_crs):
        if not destination_crs or not destination_crs.isValid():
            return None
        if layer.crs() == destination_crs:
            return None
        return QgsCoordinateTransform(layer.crs(), destination_crs, QgsProject.instance())

    def _export_multi_file_format(
        self,
        layers,
        target_path,
        *,
        format_key,
        driver_name,
        single_file_allowed=False,
        sidecar_style=False,
        prepare_layer=None,
        destination_crs=None,
        symbology_export=None,
    ):
        vector_layers, skipped = self._vector_export_layers(layers)
        if not vector_layers:
            self._push_message(
                f"Kein geeigneter Vektorlayer fuer {FORMAT_LABELS[format_key]} vorhanden.",
                level=Qgis.Critical,
                duration=8,
            )
            if skipped:
                self._show_detailed_issues("Layer uebersprungen", skipped, QMessageBox.Warning)
            return

        extension = FILE_EXTENSIONS[format_key]
        write_to_directory = len(vector_layers) > 1 or not single_file_allowed
        if not write_to_directory and os.path.isdir(target_path):
            write_to_directory = True

        if write_to_directory and not self._ensure_directory(target_path):
            return

        planned_paths = []
        used_names = set()
        for layer in vector_layers:
            if write_to_directory:
                planned_paths.append(
                    os.path.join(target_path, f"{self._unique_name(layer.name(), used_names)}{extension}")
                )
            else:
                planned_paths.append(target_path)

        if not self._confirm_overwrite(planned_paths, "Es existieren bereits Exportdateien. Ueberschreiben?"):
            return

        errors = []
        success_count = 0
        used_names = set()

        for layer in vector_layers:
            export_layer = layer
            if prepare_layer:
                export_layer, should_continue = prepare_layer(layer)
                if not should_continue:
                    return
                if export_layer is None:
                    errors.append(f"{layer.name()}: Layer konnte nicht vorbereitet werden.")
                    continue

            if write_to_directory:
                output_path = os.path.join(
                    target_path,
                    f"{self._unique_name(layer.name(), used_names)}{extension}",
                )
            else:
                output_path = target_path

            if driver_name == "ESRI Shapefile" and os.path.exists(output_path):
                QgsVectorFileWriter.deleteShapeFile(output_path)

            coordinate_transform = None
            if destination_crs is not None:
                coordinate_transform = self._coordinate_transform(export_layer, destination_crs)

            error = self._write_vector_layer(
                export_layer,
                output_path,
                driver_name,
                layer_name=self._safe_name(layer.name()),
                symbology_export=symbology_export,
                symbology_scale=self._current_symbology_scale(),
                action_on_existing=QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile,
                coordinate_transform=coordinate_transform,
                save_metadata=False,
            )
            if error:
                errors.append(f"{layer.name()}: {error}")
                continue

            if sidecar_style:
                self._save_qml_sidecar(export_layer, output_path)

            success_count += 1

            if not write_to_directory:
                break

        summary_target = target_path if write_to_directory else planned_paths[0]
        self._summarize_export(format_key, summary_target, success_count, errors, skipped)

    def export_selected_layers(self):
        layers = self._selected_layers(allow_active_fallback=True)
        if not layers:
            self._push_message("Keine Layer ausgewaehlt.", level=Qgis.Warning, duration=5)
            return

        format_key = self._choose_export_format()
        if not format_key:
            return

        target_path = self._choose_target_path(format_key, len(layers))
        if not target_path:
            return

        if format_key == "gpkg":
            self._export_geopackage(layers, target_path)
            return

        if format_key == "dxf":
            self._export_dxf(layers, target_path)
            return

        if format_key == "shp":
            self._export_multi_file_format(
                layers,
                target_path,
                format_key="shp",
                driver_name="ESRI Shapefile",
            )
            return

        if format_key == "kml":
            self._export_multi_file_format(
                layers,
                target_path,
                format_key="kml",
                driver_name="KML",
                single_file_allowed=True,
                prepare_layer=self._prepare_kml_layer,
                destination_crs=QgsCoordinateReferenceSystem("EPSG:4326"),
                symbology_export=Qgis.FeatureSymbologyExport.PerSymbolLayer,
            )
            return

        if format_key == "geojson":
            self._export_multi_file_format(
                layers,
                target_path,
                format_key="geojson",
                driver_name="GeoJSON",
                single_file_allowed=True,
                sidecar_style=True,
                destination_crs=QgsCoordinateReferenceSystem("EPSG:4326"),
                symbology_export=Qgis.FeatureSymbologyExport.PerSymbolLayer,
            )
