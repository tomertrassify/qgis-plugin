import json
import os
import shutil
import tempfile
import xml.etree.ElementTree as xml_et
import zipfile

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsProject,
    QgsRenderContext,
    QgsRuleBasedRenderer,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

import processing


def visible_vector_layers():
    root = QgsProject.instance().layerTreeRoot()
    layers = []
    for layer in QgsProject.instance().mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        tree_layer = root.findLayer(layer.id())
        if tree_layer and tree_layer.isVisible():
            layers.append(layer)
    return layers


class LeafletExporter:
    def __init__(self):
        self.default_blacklist = ["fid", "OBJECTID", "Shape_Leng", "Shape_Area", "path"]

    def export(self, project_name, base_folder, options=None):
        options = options or {}
        blacklist = options.get("blacklist", self.default_blacklist)
        exports = set(options.get("exports", {"shp", "gpkg", "dxf"}))
        gpkg_options = options.get("gpkg", {})
        dxf_options = options.get("dxf", {})
        kml_options = options.get("kml", {})
        do_zip = options.get("zip", True)
        cleanup_after_zip = options.get("cleanup_after_zip", True)

        base_path = os.path.join(base_folder, project_name)
        data_folder = os.path.join(base_path, "data")
        svg_folder = os.path.join(base_path, "svg")
        export_folder = os.path.join(base_path, "export")
        shp_folder = os.path.join(export_folder, "shapes")
        gpkg_folder = os.path.join(export_folder, "gpkg")
        dxf_folder = os.path.join(export_folder, "dxf")

        for folder in (
            data_folder,
            svg_folder,
            export_folder,
            shp_folder,
            gpkg_folder,
            dxf_folder,
        ):
            os.makedirs(folder, exist_ok=True)

        status_json_path = None
        status_url = str(options.get("status_url") or "").strip()
        if status_url:
            status_json_path = os.path.join(base_path, "status.json")
            with open(status_json_path, "w", encoding="utf-8") as file_obj:
                json.dump({"statusUrl": status_url}, file_obj, ensure_ascii=False, indent=2)

        layers = visible_vector_layers()
        for layer in layers:
            self._export_geojson_layer(layer, data_folder, svg_folder, blacklist)

        created_zips = {}
        if "shp" in exports:
            self._export_shapefiles(layers, shp_folder)
            if do_zip:
                zip_path = os.path.join(export_folder, f"{project_name}_shapes.zip")
                self._zip_folder(shp_folder, zip_path)
                created_zips["shapes"] = zip_path
                if cleanup_after_zip:
                    self._safe_rmtree(shp_folder)

        if "gpkg" in exports:
            gpkg_path = os.path.join(gpkg_folder, f"{project_name}.gpkg")
            processing.run(
                "native:package",
                {
                    "LAYERS": layers,
                    "OUTPUT": gpkg_path,
                    "OVERWRITE": gpkg_options.get("OVERWRITE", True),
                    "SAVE_STYLE": gpkg_options.get("SAVE_STYLE", True),
                    "SAVE_METADATA": gpkg_options.get("SAVE_METADATA", True),
                },
            )
            if do_zip:
                zip_path = os.path.join(export_folder, f"{project_name}_gpkg.zip")
                self._zip_folder(gpkg_folder, zip_path)
                created_zips["gpkg"] = zip_path
                if cleanup_after_zip:
                    self._safe_rmtree(gpkg_folder)

        if "dxf" in exports:
            dxf_path = os.path.join(dxf_folder, f"{project_name}.dxf")
            layer_defs = [
                {
                    "layer": layer.source(),
                    "attributeIndex": -1,
                    "overriddenLayerName": "",
                    "buildDataDefinedBlocks": True,
                    "dataDefinedBlocksMaximumNumberOfClasses": -1,
                }
                for layer in layers
            ]
            processing.run(
                "native:dxfexport",
                {
                    "LAYERS": layer_defs,
                    "SYMBOLOGY_MODE": dxf_options.get("SYMBOLOGY_MODE", 2),
                    "SYMBOLOGY_SCALE": dxf_options.get("SYMBOLOGY_SCALE", 250),
                    "MAP_THEME": dxf_options.get("MAP_THEME"),
                    "ENCODING": dxf_options.get("ENCODING", "cp1252"),
                    "CRS": dxf_options.get("CRS", QgsProject.instance().crs()),
                    "EXTENT": dxf_options.get("EXTENT"),
                    "SELECTED_FEATURES_ONLY": dxf_options.get("SELECTED_FEATURES_ONLY", False),
                    "USE_LAYER_TITLE": dxf_options.get("USE_LAYER_TITLE", False),
                    "MTEXT": dxf_options.get("MTEXT", True),
                    "EXPORT_LINES_WITH_ZERO_WIDTH": dxf_options.get(
                        "EXPORT_LINES_WITH_ZERO_WIDTH", False
                    ),
                    "LABEL_FIELD": dxf_options.get("LABEL_FIELD"),
                    "OUTPUT": dxf_path,
                },
            )
            if do_zip:
                zip_path = os.path.join(export_folder, f"{project_name}_dxf.zip")
                self._zip_folder(dxf_folder, zip_path)
                created_zips["dxf"] = zip_path
                if cleanup_after_zip:
                    self._safe_rmtree(dxf_folder)

        if not kml_options.get("DISABLED", False):
            kml_result = self._export_kml(
                layers,
                export_folder,
                project_name,
                kml_options,
                cleanup_after_zip,
            )
            if kml_result.get("zip_path"):
                created_zips["kml"] = kml_result["zip_path"]

        geojson_manifest_path = os.path.join(data_folder, "geojson-manifest.json")
        export_manifest_path = os.path.join(export_folder, "manifest.json")
        self._write_manifest_file(
            geojson_manifest_path,
            self._collect_manifest_entries(data_folder, {".geojson"}),
        )
        self._write_manifest_file(
            export_manifest_path,
            self._collect_manifest_entries(export_folder, {".zip", ".kml", ".gpkg", ".dxf"}),
        )

        output_kml = os.path.join(export_folder, f"{project_name}.kml")
        return {
            "data_folder": data_folder,
            "svg_folder": svg_folder,
            "export_folder": export_folder,
            "zips": created_zips,
            "kml": output_kml if os.path.exists(output_kml) else None,
            "status_json": status_json_path,
            "geojson_manifest": geojson_manifest_path if os.path.exists(geojson_manifest_path) else None,
            "export_manifest": export_manifest_path if os.path.exists(export_manifest_path) else None,
        }

    def _export_geojson_layer(self, layer, data_folder, svg_folder, blacklist):
        group_path = self._get_layer_group_path(layer)
        relative_folder = os.path.join(data_folder, *group_path)
        os.makedirs(relative_folder, exist_ok=True)

        layer_name = layer.name().replace(" ", "_")
        output_path = os.path.join(relative_folder, f"{layer_name}.geojson")
        style_field_names = ["color", "fillColor", "opacity", "weight", "svg", "size"]
        label_expression = self._get_label_expression(layer)
        fields_to_export = self._visible_fields(layer, blacklist)

        source_crs = layer.sourceCrs()
        target_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())

        fields = QgsFields()
        for field_name in fields_to_export:
            fields.append(QgsField(field_name, QVariant.String))
        for key in style_field_names:
            fields.append(QgsField(key, QVariant.String))
        fields.append(QgsField("label_text", QVariant.String))

        renderer = layer.renderer()
        if isinstance(renderer, QgsRuleBasedRenderer):
            self._export_rule_based_layer(
                layer,
                renderer,
                fields,
                fields_to_export,
                label_expression,
                style_field_names,
                transform,
                relative_folder,
                svg_folder,
                data_folder,
            )
            return

        writer = QgsVectorFileWriter(
            output_path,
            "UTF-8",
            fields,
            layer.wkbType(),
            target_crs,
            "GeoJSON",
        )
        for feature in layer.getFeatures():
            attrs = self._feature_attributes(layer, feature, fields_to_export, label_expression)
            symbol = self._symbol_for_feature(layer, feature)
            style = self._style_from_symbol(symbol, svg_folder, data_folder)
            for key in style_field_names:
                attrs[key] = style.get(key)

            geom = feature.geometry()
            if geom and not geom.isEmpty():
                geom.transform(transform)

            output_feature = QgsFeature(fields)
            if geom and not geom.isEmpty():
                output_feature.setGeometry(geom)
            for key, value in attrs.items():
                if key in [field.name() for field in fields]:
                    output_feature.setAttribute(key, str(value) if value is not None else None)
            writer.addFeature(output_feature)
        del writer

    def _export_rule_based_layer(
        self,
        layer,
        renderer,
        fields,
        fields_to_export,
        label_expression,
        style_field_names,
        transform,
        relative_folder,
        svg_folder,
        data_folder,
    ):
        leaf_rules = []

        def rule_label(rule):
            try:
                label = rule.label()
            except Exception:
                label = ""
            if not label:
                for attr_name in ("filterExpression", "filter"):
                    try:
                        value = getattr(rule, attr_name)()
                    except Exception:
                        value = None
                    if value:
                        try:
                            label = value.expression()
                        except Exception:
                            label = str(value)
                        break
            try:
                if not label and getattr(rule, "isElse")():
                    label = "ELSE"
            except Exception:
                pass
            return label or "Rule"

        def safe_label(text):
            value = str(text or "Rule").strip()
            for char in ("/", "\\", ":", "*", "?", "\"", "<", ">", "|"):
                value = value.replace(char, "_")
            return value[:80] or "Rule"

        def rule_expression(rule):
            for attr_name in ("filterExpression", "filter"):
                try:
                    value = getattr(rule, attr_name)()
                except Exception:
                    value = None
                if value:
                    try:
                        return value.expression()
                    except Exception:
                        return str(value)
            return ""

        def collect_rules(rule, parent_expressions=None):
            parent_expressions = parent_expressions or []
            try:
                children = rule.children()
            except Exception:
                children = []
            current_expression = rule_expression(rule)
            expressions = parent_expressions + ([current_expression] if current_expression else [])
            if not children:
                try:
                    key = rule.ruleKey()
                except Exception:
                    key = id(rule)
                try:
                    symbol = rule.symbol()
                    symbol = symbol.clone() if symbol else None
                except Exception:
                    symbol = None
                is_else = False
                try:
                    is_else = bool(getattr(rule, "isElse")())
                except Exception:
                    pass
                leaf_rules.append(
                    {
                        "key": key,
                        "label": rule_label(rule),
                        "expr": " AND ".join(
                            f"({expr})"
                            for expr in (parent_expressions if is_else else expressions)
                            if expr
                        ),
                        "is_else": is_else,
                        "symbol": symbol,
                    }
                )
                return
            for child in children:
                collect_rules(child, expressions)

        root_rule = renderer.rootRule()
        collect_rules(root_rule)

        writers = {}
        rule_meta = {}
        layer_dir = os.path.join(relative_folder, safe_label(layer.name().replace("-", " ")))
        os.makedirs(layer_dir, exist_ok=True)
        for index, info in enumerate(leaf_rules, start=1):
            safe_name = safe_label(info["label"]) or f"rule_{index}"
            output_path = os.path.join(layer_dir, f"{safe_name}.geojson")
            writers[info["key"]] = QgsVectorFileWriter(
                output_path,
                "UTF-8",
                fields,
                layer.wkbType(),
                QgsCoordinateReferenceSystem("EPSG:4326"),
                "GeoJSON",
            )
            rule_meta[info["key"]] = {
                "label": info["label"],
                "expr": info["expr"],
                "is_else": info["is_else"],
                "symbol": info["symbol"],
            }

        for feature in layer.getFeatures():
            attrs = self._feature_attributes(layer, feature, fields_to_export, label_expression)
            render_context = self._render_context(layer, feature)
            try:
                target_keys = [
                    key for key in renderer.legendKeysForFeature(feature, render_context) if key in writers
                ]
            except Exception:
                target_keys = []

            if not target_keys:
                target_keys = self._fallback_rule_matches(rule_meta, render_context)

            geom = feature.geometry()
            if geom and not geom.isEmpty():
                try:
                    geom.transform(transform)
                except Exception:
                    pass

            for key in target_keys:
                writer = writers.get(key)
                if not writer:
                    continue
                try:
                    symbol = renderer.symbolForFeature(feature, render_context)
                except Exception:
                    symbol = None
                if not symbol:
                    symbol = rule_meta.get(key, {}).get("symbol")
                style = self._style_from_symbol(symbol, svg_folder, data_folder)
                output_feature = QgsFeature(fields)
                if geom and not geom.isEmpty():
                    output_feature.setGeometry(geom)
                merged_attrs = dict(attrs)
                for field_name in style_field_names:
                    merged_attrs[field_name] = style.get(field_name)
                for attr_name, value in merged_attrs.items():
                    if attr_name in [field.name() for field in fields]:
                        output_feature.setAttribute(
                            attr_name,
                            str(value) if value is not None else None,
                        )
                writer.addFeature(output_feature)

        for writer in writers.values():
            del writer

    def _fallback_rule_matches(self, rule_meta, render_context):
        matched_keys = []
        expression_context = render_context.expressionContext() if render_context else None
        for key, meta in rule_meta.items():
            if meta.get("is_else"):
                continue
            expr_string = meta.get("expr") or ""
            if not expr_string:
                continue
            try:
                if bool(QgsExpression(expr_string).evaluate(expression_context)):
                    matched_keys.append(key)
            except Exception:
                continue
        if matched_keys:
            return matched_keys
        for key, meta in rule_meta.items():
            if not meta.get("is_else"):
                continue
            expr_string = meta.get("expr") or ""
            if not expr_string:
                matched_keys.append(key)
                continue
            try:
                if bool(QgsExpression(expr_string).evaluate(expression_context)):
                    matched_keys.append(key)
            except Exception:
                matched_keys.append(key)
        return matched_keys

    def _feature_attributes(self, layer, feature, fields_to_export, label_expression):
        attrs = {
            field_name: feature[field_name]
            for field_name in fields_to_export
            if field_name in feature.fields().names()
        }
        if not label_expression:
            attrs["label_text"] = None
            return attrs
        try:
            expression = QgsExpression(label_expression)
            context = QgsExpressionContext()
            context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
            context.setFeature(feature)
            attrs["label_text"] = expression.evaluate(context)
        except Exception:
            attrs["label_text"] = None
        return attrs

    def _render_context(self, layer, feature):
        render_context = QgsRenderContext()
        expression_context = QgsExpressionContext()
        expression_context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
        expression_context.setFeature(feature)
        render_context.setExpressionContext(expression_context)
        return render_context

    def _symbol_for_feature(self, layer, feature):
        try:
            return layer.renderer().symbolForFeature(feature, self._render_context(layer, feature))
        except Exception:
            return None

    def _export_shapefiles(self, layers, shp_folder):
        for layer in layers:
            output_path = os.path.join(shp_folder, f"{layer.name().replace(' ', '_')}.shp")
            try:
                QgsVectorFileWriter.writeAsVectorFormat(
                    layer,
                    output_path,
                    "CP1252",
                    layer.sourceCrs(),
                    "ESRI Shapefile",
                )
            except Exception:
                continue

    def _export_kml(self, layers, export_folder, project_name, kml_options, cleanup_after_zip):
        temp_dir = tempfile.mkdtemp(prefix="trassify_webmap_kml_")
        exported_kmls = []
        for layer in layers:
            output_name = layer.name().replace(" ", "_")
            temp_kml_path = os.path.join(temp_dir, f"{output_name}.kml")

            save_options = QgsVectorFileWriter.SaveVectorOptions()
            save_options.driverName = "KML"
            save_options.fileEncoding = "UTF-8"
            save_options.symbologyScale = kml_options.get("SYMBOLOGY_SCALE", 250)
            save_options.symbologyExport = kml_options.get(
                "SYMBOLOGY_EXPORT",
                QgsVectorFileWriter.SymbolLayerSymbology,
            )
            name_field = kml_options.get("NAME_FIELD")
            if name_field and name_field in [field.name() for field in layer.fields()]:
                save_options.layerNameAttribute = name_field

            error_code, _error_message = QgsVectorFileWriter.writeAsVectorFormatV2(
                layer,
                temp_kml_path,
                QgsProject.instance().transformContext(),
                save_options,
            )
            if error_code == QgsVectorFileWriter.NoError:
                exported_kmls.append(temp_kml_path)

        output_kml_path = os.path.join(export_folder, f"{project_name}.kml")
        if exported_kmls:
            try:
                root = xml_et.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
                document = xml_et.SubElement(root, "Document")
                for kml_path in exported_kmls:
                    tree = xml_et.parse(kml_path)
                    sub_root = tree.getroot()
                    for element in sub_root.iter():
                        if element.tag.endswith("Placemark") or element.tag.endswith("Style"):
                            document.append(element)
                xml_et.ElementTree(root).write(
                    output_kml_path,
                    encoding="utf-8",
                    xml_declaration=True,
                )
            except Exception:
                if exported_kmls:
                    shutil.copy(exported_kmls[0], output_kml_path)

        zip_path = None
        if kml_options.get("ZIP", True) and os.path.exists(output_kml_path):
            zip_path = os.path.join(export_folder, f"{project_name}_kml.zip")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
                zip_file.write(output_kml_path, os.path.basename(output_kml_path))
            if cleanup_after_zip:
                try:
                    os.remove(output_kml_path)
                except Exception:
                    pass
        self._safe_rmtree(temp_dir)
        return {"zip_path": zip_path}

    def _get_layer_group_path(self, layer):
        tree_layer = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
        if not tree_layer:
            return []
        group_path = []
        parent = tree_layer.parent()
        while parent and parent.name():
            group_path.insert(0, parent.name())
            parent = parent.parent()
        return group_path

    def _style_from_symbol(self, symbol, svg_folder, data_folder):
        if not symbol or getattr(symbol, "symbolLayerCount", lambda: 0)() == 0:
            return {"color": "#000000", "fillColor": "#ffffff", "opacity": 1, "weight": 1}

        try:
            layer_type = symbol.symbolLayer(0).layerType()
        except Exception:
            layer_type = None

        try:
            color = symbol.color().name(QColor.HexRgb)
        except Exception:
            color = "#000000"

        fill_color = "#ffffff"
        weight = 1
        try:
            opacity = symbol.opacity()
        except Exception:
            opacity = 1
        size = None

        if layer_type == "SimpleLine":
            line_layer = symbol.symbolLayer(0)
            try:
                width = getattr(line_layer, "width", lambda: 1)()
            except Exception:
                width = 1
            try:
                unit = getattr(line_layer, "widthUnit", lambda: 2)()
            except Exception:
                unit = 2
            weight = width * 3.78 if unit == 0 else width
        elif layer_type == "SimpleFill":
            try:
                fill_color = symbol.symbolLayer(0).fillColor().name(QColor.HexRgb)
            except Exception:
                pass
            try:
                weight = symbol.symbolLayer(0).borderWidth()
            except Exception:
                pass
        elif layer_type == "SvgMarker":
            svg_layer = symbol.symbolLayer(0)
            try:
                svg_path = svg_layer.path()
            except Exception:
                svg_path = None
            try:
                color = svg_layer.color().name(QColor.HexRgb)
            except Exception:
                pass
            try:
                size = svg_layer.size()
            except Exception:
                size = None

            relative_svg_path = None
            if svg_path and os.path.exists(svg_path):
                target_path = os.path.join(svg_folder, os.path.basename(svg_path))
                try:
                    shutil.copy(svg_path, target_path)
                    relative_svg_path = os.path.relpath(target_path, start=data_folder).replace("\\", "/")
                except Exception:
                    relative_svg_path = None

            return {
                "svg": relative_svg_path,
                "size": size,
                "color": color,
                "opacity": opacity,
            }
        elif layer_type == "SimpleMarker":
            try:
                size = symbol.symbolLayer(0).size()
            except Exception:
                size = None
            return {"size": size, "color": color, "opacity": opacity}

        return {
            "color": color,
            "fillColor": fill_color,
            "opacity": opacity,
            "weight": weight,
        }

    def _visible_fields(self, layer, blacklist):
        config = layer.attributeTableConfig()
        visible = []
        for field in layer.fields():
            hidden = False
            try:
                hidden = config.isColumnHidden(field.name())
            except AttributeError:
                try:
                    hidden = config.columnHidden(field)
                except Exception:
                    hidden = False
            if not hidden and field.name() not in blacklist:
                visible.append(field.name())
        return visible

    def _get_label_expression(self, layer):
        try:
            if layer.labelsEnabled():
                settings = layer.labeling().settings()
                expression = settings.fieldName() or settings.format().expression()
                if not expression and settings.format().expressionString():
                    expression = settings.format().expressionString()
                return expression or None
        except Exception:
            return None
        return None

    def _collect_manifest_entries(self, base_folder, allowed_exts=None):
        normalized_exts = {ext.lower() for ext in allowed_exts} if allowed_exts else None
        entries = []
        for root_dir, _dirs, files in os.walk(base_folder):
            for file_name in files:
                extension = os.path.splitext(file_name)[1].lower()
                if normalized_exts is not None and extension not in normalized_exts:
                    continue
                path = os.path.join(root_dir, file_name)
                relative_path = os.path.relpath(path, start=base_folder)
                entries.append(relative_path.replace("\\", "/"))
        return sorted(dict.fromkeys(entries))

    def _write_manifest_file(self, path, entries):
        with open(path, "w", encoding="utf-8") as file_obj:
            json.dump(entries, file_obj, ensure_ascii=False, indent=2)

    def _zip_folder(self, folder_path, zip_path):
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for root_dir, _dirs, files in os.walk(folder_path):
                for file_name in files:
                    file_path = os.path.join(root_dir, file_name)
                    arcname = os.path.relpath(file_path, start=folder_path)
                    zip_file.write(file_path, arcname)

    def _safe_rmtree(self, folder_path):
        try:
            shutil.rmtree(folder_path)
        except Exception:
            pass
