import os
import sqlite3

from qgis.PyQt.QtWidgets import QAction, QDialog, QFileDialog, QInputDialog, QMessageBox
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsMapLayerType,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .field_mapping_dialog import FieldMappingDialog


class LayerFuserPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self._context_action_registered = False
        self._plugin_menu_registered = False

    def initGui(self):
        self.action = QAction("Layer Fuser", self.iface.mainWindow())
        self.action.setObjectName("layerFuserAction")
        self.action.triggered.connect(self.run)

        if hasattr(self.iface, "addCustomActionForLayerType"):
            try:
                self.iface.addCustomActionForLayerType(
                    self.action,
                    "",
                    QgsMapLayerType.VectorLayer,
                    False,
                )
                self._context_action_registered = True
            except TypeError:
                self.iface.addCustomActionForLayerType(
                    self.action,
                    "",
                    QgsMapLayerType.VectorLayer,
                )
                self._context_action_registered = True
            except Exception:
                self._context_action_registered = False

        if hasattr(self.iface, "addPluginToMenu"):
            self.iface.addPluginToMenu("&Layer Fuser", self.action)
            self._plugin_menu_registered = True

    def unload(self):
        if self.action is None:
            return

        if self._context_action_registered and hasattr(self.iface, "removeCustomActionForLayerType"):
            try:
                self.iface.removeCustomActionForLayerType(self.action)
            except TypeError:
                try:
                    self.iface.removeCustomActionForLayerType(
                        self.action,
                        QgsMapLayerType.VectorLayer,
                    )
                except Exception:
                    pass
            except Exception:
                pass

        if self._plugin_menu_registered and hasattr(self.iface, "removePluginMenu"):
            self.iface.removePluginMenu("&Layer Fuser", self.action)

        self.action = None

    def run(self):
        target_layer = self._current_vector_layer()
        if target_layer is None:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Layer Fuser",
                "Bitte waehlen Sie in der Layerliste einen Vektorlayer als Ziel aus.",
            )
            return

        source_path = self._select_source_file()
        if not source_path:
            return

        source_layer = self._load_source_layer(source_path)
        if source_layer is None:
            return

        geometry_error = self._geometry_compatibility_error(target_layer, source_layer)
        if geometry_error:
            QMessageBox.warning(self.iface.mainWindow(), "Layer Fuser", geometry_error)
            return

        dialog = FieldMappingDialog(target_layer, source_layer, self.iface.mainWindow())
        if dialog.exec_() != QDialog.Accepted:
            return

        try:
            added_count, skipped_count = self._append_features(
                target_layer,
                source_layer,
                dialog.mapping(),
            )
        except RuntimeError as error:
            QMessageBox.critical(self.iface.mainWindow(), "Layer Fuser", str(error))
            return

        message = (
            f"{added_count} Feature(s) wurden in den Layer '{target_layer.name()}' uebernommen."
        )
        if skipped_count:
            message += (
                f" {skipped_count} Feature(s) wurden wegen nicht passender Einzel-/Multi-Geometrie uebersprungen."
            )

        QMessageBox.information(self.iface.mainWindow(), "Layer Fuser", message)

    def _current_vector_layer(self):
        layer = None
        if hasattr(self.iface, "layerTreeView") and self.iface.layerTreeView() is not None:
            layer = self.iface.layerTreeView().currentLayer()
        if layer is None and hasattr(self.iface, "activeLayer"):
            layer = self.iface.activeLayer()
        return layer if isinstance(layer, QgsVectorLayer) else None

    def _select_source_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            "Quellayer waehlen",
            "",
            "Vektorlayer (*.shp *.gpkg);;Shapefile (*.shp);;GeoPackage (*.gpkg)",
        )
        return file_path

    def _load_source_layer(self, source_path):
        extension = os.path.splitext(source_path)[1].lower()

        if extension == ".gpkg":
            layer_name = self._select_gpkg_layer(source_path)
            if not layer_name:
                return None
            layer_uri = f"{source_path}|layername={layer_name}"
            layer = QgsVectorLayer(layer_uri, layer_name, "ogr")
        else:
            layer_name = os.path.splitext(os.path.basename(source_path))[0]
            layer = QgsVectorLayer(source_path, layer_name, "ogr")

        if layer.isValid():
            return layer

        QMessageBox.warning(
            self.iface.mainWindow(),
            "Layer Fuser",
            "Der ausgewaehlte Layer konnte nicht geladen werden.",
        )
        return None

    def _select_gpkg_layer(self, source_path):
        layer_names = self._list_gpkg_feature_layers(source_path)
        if not layer_names:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Layer Fuser",
                "Im GeoPackage wurden keine Feature-Layer gefunden.",
            )
            return None

        if len(layer_names) == 1:
            return layer_names[0]

        selected_name, confirmed = QInputDialog.getItem(
            self.iface.mainWindow(),
            "Layer Fuser",
            "Welchen GeoPackage-Layer moechten Sie uebernehmen?",
            layer_names,
            0,
            False,
        )
        return selected_name if confirmed and selected_name else None

    def _list_gpkg_feature_layers(self, source_path):
        query = """
            SELECT table_name
            FROM gpkg_contents
            WHERE data_type = 'features'
            ORDER BY table_name
        """

        try:
            with sqlite3.connect(source_path) as connection:
                rows = connection.execute(query).fetchall()
        except sqlite3.Error:
            return []

        return [row[0] for row in rows if row and row[0]]

    def _geometry_compatibility_error(self, target_layer, source_layer):
        target_geometry_type = QgsWkbTypes.geometryType(target_layer.wkbType())
        source_geometry_type = QgsWkbTypes.geometryType(source_layer.wkbType())

        if target_geometry_type != source_geometry_type:
            return (
                "Die Geometrietypen passen nicht zusammen. "
                f"Ziellayer: {QgsWkbTypes.displayString(target_layer.wkbType())}, "
                f"Quellayer: {QgsWkbTypes.displayString(source_layer.wkbType())}."
            )

        return None

    def _append_features(self, target_layer, source_layer, field_mapping):
        started_editing = False
        if not target_layer.isEditable():
            if not target_layer.startEditing():
                raise RuntimeError(
                    "Der Ziellayer konnte nicht in den Bearbeitungsmodus versetzt werden."
                )
            started_editing = True

        transform = None
        if (
            source_layer.crs().isValid()
            and target_layer.crs().isValid()
            and source_layer.crs() != target_layer.crs()
        ):
            transform = QgsCoordinateTransform(
                source_layer.crs(),
                target_layer.crs(),
                QgsProject.instance(),
            )

        target_fields = target_layer.fields()
        target_geometry_type = QgsWkbTypes.geometryType(target_layer.wkbType())
        target_is_multi = QgsWkbTypes.isMultiType(target_layer.wkbType())
        features_to_add = []
        skipped_count = 0

        try:
            for source_feature in source_layer.getFeatures():
                target_feature = QgsFeature(target_fields)
                source_geometry = source_feature.geometry()

                if source_geometry and not source_geometry.isEmpty():
                    geometry = source_feature.geometry()

                    if transform is not None:
                        geometry.transform(transform)

                    geometry = self._prepare_geometry(
                        geometry,
                        target_geometry_type,
                        target_is_multi,
                    )
                    if geometry is None:
                        skipped_count += 1
                        continue

                    target_feature.setGeometry(geometry)

                for source_field_name, target_field_name in field_mapping.items():
                    target_feature.setAttribute(
                        target_field_name,
                        source_feature[source_field_name],
                    )

                features_to_add.append(target_feature)
        except Exception as error:
            if started_editing:
                target_layer.rollBack()
            raise RuntimeError(f"Die Features konnten nicht vorbereitet werden: {error}")

        if features_to_add:
            add_result = target_layer.addFeatures(features_to_add)
            add_success = add_result[0] if isinstance(add_result, tuple) else bool(add_result)
            if not add_success:
                if started_editing:
                    target_layer.rollBack()
                raise RuntimeError("Die Features konnten dem Ziellayer nicht hinzugefuegt werden.")

        if started_editing:
            if not target_layer.commitChanges():
                commit_errors = target_layer.commitErrors()
                error_text = "; ".join(commit_errors) if commit_errors else "Unbekannter Fehler"
                target_layer.rollBack()
                raise RuntimeError(
                    f"Die Aenderungen konnten nicht gespeichert werden: {error_text}"
                )

        target_layer.triggerRepaint()
        return len(features_to_add), skipped_count

    def _prepare_geometry(self, geometry, target_geometry_type, target_is_multi):
        converted_geometry = geometry.convertToType(target_geometry_type, target_is_multi)
        if converted_geometry is None or converted_geometry.isNull():
            return None
        return converted_geometry
