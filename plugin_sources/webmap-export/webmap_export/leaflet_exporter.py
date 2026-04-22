import json
import os
import shutil
import tempfile
import xml.etree.ElementTree as xml_et
import zipfile
from typing import Any, Dict, List, Optional

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsApplication,
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
)

from .base import BaseExporter
from .utils import visible_vector_layers

try:
    import processing
except Exception:
    processing = None


class LeafletExporter(BaseExporter):
    def __init__(self):
        self.default_blacklist = ["fid", "OBJECTID", "Shape_Leng", "Shape_Area", "path"]

    def export(
        self,
        project_name: str,
        base_folder: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        options = options or {}
        blacklist = options.get("blacklist", self.default_blacklist)
        warnings: List[str] = []

        exports = set(options.get("exports", {"shp", "gpkg", "dxf"}))
        gpkg_opts = options.get("gpkg", {})
        dxf_opts = options.get("dxf", {})
        kml_opts = options.get("kml", {})
        do_zip = options.get("zip", True)
        cleanup_after_zip = options.get("cleanup_after_zip", True)

        base_path = os.path.join(base_folder, project_name)
        data_folder = os.path.join(base_path, "data")
        svg_folder = os.path.join(base_path, "svg")
        export_folder = os.path.join(base_path, "export")
        shp_folder = os.path.join(export_folder, "shapes")
        gpkg_folder = os.path.join(export_folder, "gpkg")
        dxf_folder = os.path.join(export_folder, "dxf")

        status_url = str(options.get("status_url") or "").strip()
        status_value = str(options.get("status") or "").strip()
        download_token = str(options.get("download_token") or "").strip()
        baubeginn = str(options.get("baubeginn") or "").strip()
        status_payload = {
            "statusUrl": status_url,
            "status": status_value,
            "downloadToken": download_token,
            "baubeginn": baubeginn,
        }
        has_status_input = any(status_payload.values())
        preserved_status = None
        status_json_path = None

        if os.path.isdir(base_path):
            existing_status_path = os.path.join(base_path, "status.json")
            if os.path.exists(existing_status_path):
                try:
                    with open(existing_status_path, "r", encoding="utf-8") as handle:
                        preserved_status = json.load(handle)
                except Exception:
                    preserved_status = None
            if not has_status_input and preserved_status is not None:
                status_json_path = existing_status_path
            self._safe_rmtree(data_folder)
            self._safe_rmtree(export_folder)
        else:
            os.makedirs(base_path, exist_ok=True)

        for folder in (
            data_folder,
            svg_folder,
            export_folder,
            shp_folder,
            gpkg_folder,
            dxf_folder,
        ):
            os.makedirs(folder, exist_ok=True)

        if has_status_input:
            merged_status = {}
            if isinstance(preserved_status, dict):
                merged_status.update(preserved_status)
            for key, value in status_payload.items():
                if value:
                    merged_status[key] = value
            try:
                status_json_path = os.path.join(base_path, "status.json")
                with open(status_json_path, "w", encoding="utf-8") as file_obj:
                    json.dump(merged_status, file_obj, ensure_ascii=False, indent=2)
            except Exception:
                status_json_path = None

        layers = visible_vector_layers()

        for layer in layers:
            group_path = self._get_layer_group_path(layer)
            relative_folder = os.path.join(data_folder, *group_path)
            os.makedirs(relative_folder, exist_ok=True)

            layer_name = self._clean_layer_name(layer.name()).replace(" ", "_")
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

            def safe_fs_name(text: str) -> str:
                try:
                    value = self._clean_layer_name(text)
                except Exception:
                    value = ""
                for char in ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]:
                    value = value.replace(char, "_")
                return value or "_"

            if isinstance(renderer, QgsRuleBasedRenderer):
                rule_meta: Dict[Any, Dict[str, Any]] = {}
                leaf_keys: List[Any] = []
                rule_order: List[Any] = []
                ancestors_by_key: Dict[Any, List[Any]] = {}
                root_key = None
                max_depth = 0

                def rule_label(rule):
                    try:
                        label = rule.label()
                    except Exception:
                        label = ""
                    if not label:
                        for attr_name in ("filterExpression", "filter"):
                            try:
                                value = getattr(rule, attr_name)()
                                if value:
                                    label = value
                                    break
                            except Exception:
                                pass
                    try:
                        if not label and getattr(rule, "isElse")():
                            label = "ELSE"
                    except Exception:
                        pass
                    return label or "Rule"

                def safe_label(text: str) -> str:
                    try:
                        value = (text or "Rule").strip()
                    except Exception:
                        value = "Rule"
                    for char in ("/", "\\", ":", "*", "?", "\"", "<", ">", "|"):
                        value = value.replace(char, "_")
                    if len(value) > 80:
                        value = value[:80]
                    return value or "Rule"

                def expression_from_rule(rule) -> str:
                    for attr_name in ("filterExpression", "filter"):
                        try:
                            value = getattr(rule, attr_name)()
                            if value:
                                try:
                                    return value.expression()
                                except Exception:
                                    return str(value)
                        except Exception:
                            pass
                    return ""

                def is_active(rule) -> bool:
                    for attr_name in ("isActive", "active"):
                        try:
                            return bool(getattr(rule, attr_name)())
                        except Exception:
                            pass
                    return True

                try:
                    root_rule = renderer.rootRule()
                except Exception:
                    root_rule = None

                if root_rule is None:
                    writers = {
                        "__single__": QgsVectorFileWriter(
                            output_path,
                            "UTF-8",
                            fields,
                            layer.wkbType(),
                            target_crs,
                            "GeoJSON",
                        )
                    }
                    rule_meta = {
                        "__single__": {
                            "label": layer_name,
                            "label_path": [layer_name],
                            "full_label": layer_name,
                            "expr_raw": "",
                            "expr_combined": "",
                            "is_else": False,
                            "symbol": None,
                            "has_symbol": False,
                            "parent": None,
                            "children": [],
                            "is_leaf": True,
                            "active": True,
                            "is_root": False,
                            "depth": 0,
                        }
                    }
                    leaf_keys = ["__single__"]
                    rule_order = ["__single__"]
                    ancestors_by_key = {"__single__": []}
                else:
                    def collect_rules(
                        rule,
                        parent_key=None,
                        parent_labels=None,
                        parent_expression=None,
                        depth=0,
                    ):
                        nonlocal max_depth
                        parent_labels = parent_labels or []
                        try:
                            children = rule.children()
                        except Exception:
                            children = []
                        expr_raw = expression_from_rule(rule)
                        combined_expr = expr_raw
                        if parent_expression:
                            combined_expr = (
                                f"({parent_expression}) AND ({expr_raw})"
                                if expr_raw
                                else parent_expression
                            )
                        current_label = rule_label(rule)
                        if depth == 0 and (not current_label or current_label == "Rule"):
                            current_label = self._clean_layer_name(layer.name()) or "All"
                        label_path = parent_labels + ([current_label] if current_label else [])
                        try:
                            key = rule.ruleKey()
                        except Exception:
                            key = id(rule)
                        try:
                            is_else = bool(getattr(rule, "isElse")())
                        except Exception:
                            is_else = False
                        try:
                            symbol = rule.symbol()
                            symbol = symbol.clone() if symbol else None
                        except Exception:
                            symbol = None
                        active = is_active(rule)
                        rule_meta[key] = {
                            "label": current_label,
                            "label_path": label_path,
                            "full_label": " / ".join([part for part in label_path if part]),
                            "expr_raw": expr_raw,
                            "expr_combined": combined_expr or "",
                            "is_else": is_else,
                            "symbol": symbol,
                            "has_symbol": symbol is not None,
                            "parent": parent_key,
                            "children": [],
                            "is_leaf": not bool(children),
                            "active": active,
                            "is_root": False,
                            "depth": depth,
                        }
                        rule_order.append(key)
                        if not children:
                            leaf_keys.append(key)
                        if depth > max_depth:
                            max_depth = depth
                        for child in children:
                            child_key = collect_rules(
                                child,
                                key,
                                label_path,
                                combined_expr or "",
                                depth + 1,
                            )
                            rule_meta[key]["children"].append(child_key)
                        return key

                    root_key = collect_rules(root_rule, None, [], "", 0)
                    if root_key in rule_meta:
                        rule_meta[root_key]["is_root"] = True

                    export_keys = [
                        key for key in rule_order if not rule_meta.get(key, {}).get("is_root")
                    ]
                    name_counts: Dict[str, int] = {}
                    for index, key in enumerate(export_keys, start=1):
                        meta = rule_meta.get(key, {})
                        base_label = meta.get("label") or meta.get("full_label") or f"rule_{index}"
                        safe_base = safe_label(base_label) or f"rule_{index}"
                        count = name_counts.get(safe_base, 0) + 1
                        name_counts[safe_base] = count
                        safe_name = safe_base if count == 1 else f"{safe_base}_{count:02d}"
                        meta["safe"] = safe_name
                        rule_meta[key] = meta

                    writers = {}
                    layer_dir = os.path.join(
                        relative_folder,
                        safe_fs_name(self._clean_layer_name(layer.name())),
                    )
                    os.makedirs(layer_dir, exist_ok=True)
                    for index, key in enumerate(export_keys, start=1):
                        meta = rule_meta.get(key, {})
                        safe_name = meta.get("safe") or f"rule_{index}"
                        rule_output_path = os.path.join(layer_dir, f"{safe_name}.geojson")
                        writers[key] = QgsVectorFileWriter(
                            rule_output_path,
                            "UTF-8",
                            fields,
                            layer.wkbType(),
                            target_crs,
                            "GeoJSON",
                        )

                    for key in rule_meta.keys():
                        ancestors: List[Any] = []
                        parent = rule_meta.get(key, {}).get("parent")
                        while parent is not None:
                            ancestors.append(parent)
                            parent = rule_meta.get(parent, {}).get("parent")
                        ancestors_by_key[key] = ancestors

                leaf_key_set = set(leaf_keys)

                def expression_passes(expression_string: str, context: QgsExpressionContext) -> bool:
                    if not expression_string:
                        return True
                    try:
                        return bool(QgsExpression(expression_string).evaluate(context))
                    except Exception:
                        return False

                def match_rule(key, context: QgsExpressionContext) -> List[Any]:
                    meta = rule_meta.get(key, {})
                    if not meta or not meta.get("active", True):
                        return []
                    if meta.get("is_root"):
                        return match_children(key, context)
                    if not meta.get("is_else") and not expression_passes(
                        meta.get("expr_combined", ""),
                        context,
                    ):
                        return []
                    if meta.get("is_else") and not expression_passes(
                        meta.get("expr_combined", ""),
                        context,
                    ):
                        return []
                    children = meta.get("children") or []
                    if children:
                        child_matches = match_children(key, context)
                        if child_matches:
                            return child_matches
                        return [key]
                    return [key]

                def match_children(parent_key, context: QgsExpressionContext) -> List[Any]:
                    matches: List[Any] = []
                    any_matched = False
                    for child_key in rule_meta.get(parent_key, {}).get("children", []):
                        child_meta = rule_meta.get(child_key, {})
                        if not child_meta.get("active", True):
                            continue
                        if child_meta.get("is_else"):
                            if not any_matched:
                                child_matches = match_rule(child_key, context)
                                if child_matches:
                                    matches.extend(child_matches)
                                    any_matched = True
                            continue
                        child_matches = match_rule(child_key, context)
                        if child_matches:
                            matches.extend(child_matches)
                            any_matched = True
                    return matches

                for feature in layer.getFeatures():
                    attrs = {
                        field_name: feature[field_name]
                        for field_name in fields_to_export
                        if field_name in feature.fields().names()
                    }

                    if label_expression:
                        try:
                            expression = QgsExpression(label_expression)
                            expression_context = QgsExpressionContext()
                            expression_context.appendScopes(
                                QgsExpressionContextUtils.globalProjectLayerScopes(layer)
                            )
                            expression_context.setFeature(feature)
                            attrs["label_text"] = expression.evaluate(expression_context)
                        except Exception:
                            attrs["label_text"] = None
                    else:
                        attrs["label_text"] = None

                    try:
                        render_context = QgsRenderContext()
                        expression_context = QgsExpressionContext()
                        expression_context.appendScopes(
                            QgsExpressionContextUtils.globalProjectLayerScopes(layer)
                        )
                        expression_context.setFeature(feature)
                        render_context.setExpressionContext(expression_context)
                        rule_context = render_context.expressionContext()
                    except Exception:
                        render_context = None
                        rule_context = None
                    if rule_context is None:
                        try:
                            rule_context = QgsExpressionContext()
                            rule_context.appendScopes(
                                QgsExpressionContextUtils.globalProjectLayerScopes(layer)
                            )
                            rule_context.setFeature(feature)
                        except Exception:
                            rule_context = None

                    target_keys: List[Any] = []
                    if render_context is not None:
                        try:
                            target_keys = renderer.legendKeysForFeature(feature, render_context) or []
                        except Exception:
                            target_keys = []
                        target_keys = [key for key in target_keys if key in writers]

                    if rule_context is not None and root_key is not None:
                        manual_keys = match_rule(root_key, rule_context)
                        manual_keys = [key for key in manual_keys if key in writers]
                        if manual_keys:
                            target_keys = (
                                list(set(target_keys) | set(manual_keys))
                                if target_keys
                                else manual_keys
                            )

                    if target_keys:
                        expanded = set(target_keys)
                        for key in list(target_keys):
                            for ancestor in ancestors_by_key.get(key, []):
                                expanded.add(ancestor)
                        target_keys = list(expanded)

                    geometry = feature.geometry()
                    if geometry and not geometry.isEmpty():
                        try:
                            geometry.transform(transform)
                        except Exception:
                            pass

                    for key in target_keys or []:
                        writer = writers.get(key)
                        if not writer:
                            continue
                        output_feature = QgsFeature(fields)
                        if geometry and not geometry.isEmpty():
                            output_feature.setGeometry(geometry)
                        symbol = None
                        if key in leaf_key_set and render_context is not None:
                            try:
                                symbol = renderer.symbolForFeature(feature, render_context)
                            except Exception:
                                symbol = None
                        if not symbol:
                            symbol = rule_meta.get(key, {}).get("symbol")
                        style = self._style_from_symbol(symbol, svg_folder, data_folder)
                        for field_name in style_field_names:
                            attrs[field_name] = style.get(field_name)
                        for attr_name, value in attrs.items():
                            if attr_name in [field.name() for field in fields]:
                                output_feature.setAttribute(
                                    attr_name,
                                    str(value) if value is not None else None,
                                )
                        try:
                            writer.addFeature(output_feature)
                        except Exception:
                            pass

                for writer in writers.values():
                    try:
                        del writer
                    except Exception:
                        pass
            else:
                writer = QgsVectorFileWriter(
                    output_path,
                    "UTF-8",
                    fields,
                    layer.wkbType(),
                    target_crs,
                    "GeoJSON",
                )

                for feature in layer.getFeatures():
                    attrs = {
                        field_name: feature[field_name]
                        for field_name in fields_to_export
                        if field_name in feature.fields().names()
                    }

                    if label_expression:
                        try:
                            expression = QgsExpression(label_expression)
                            context = QgsExpressionContext()
                            context.appendScopes(
                                QgsExpressionContextUtils.globalProjectLayerScopes(layer)
                            )
                            context.setFeature(feature)
                            attrs["label_text"] = expression.evaluate(context)
                        except Exception:
                            attrs["label_text"] = None
                    else:
                        attrs["label_text"] = None

                    try:
                        context = QgsRenderContext()
                        expression_context = QgsExpressionContext()
                        expression_context.appendScopes(
                            QgsExpressionContextUtils.globalProjectLayerScopes(layer)
                        )
                        expression_context.setFeature(feature)
                        context.setExpressionContext(expression_context)
                        symbol = layer.renderer().symbolForFeature(feature, context)
                    except Exception:
                        symbol = None

                    style = self._style_from_symbol(symbol, svg_folder, data_folder)
                    for key in style_field_names:
                        attrs[key] = style.get(key)

                    geometry = feature.geometry()
                    if geometry and not geometry.isEmpty():
                        try:
                            geometry.transform(transform)
                        except Exception:
                            pass

                    output_feature = QgsFeature(fields)
                    if geometry and not geometry.isEmpty():
                        output_feature.setGeometry(geometry)
                    for attr_name, value in attrs.items():
                        if attr_name in [field.name() for field in fields]:
                            output_feature.setAttribute(
                                attr_name,
                                str(value) if value is not None else None,
                            )
                    writer.addFeature(output_feature)

                del writer

        created_zips: Dict[str, str] = {}

        if "shp" in exports:
            for layer in layers:
                layer_name = self._clean_layer_name(layer.name()).replace(" ", "_")
                shp_output_path = os.path.join(shp_folder, f"{layer_name}.shp")
                try:
                    QgsVectorFileWriter.writeAsVectorFormat(
                        layer,
                        shp_output_path,
                        "CP1252",
                        layer.sourceCrs(),
                        "ESRI Shapefile",
                    )
                except Exception:
                    pass

            if do_zip:
                zip_path = os.path.join(export_folder, f"{project_name}_shapes.zip")
                self._zip_folder(shp_folder, zip_path)
                created_zips["shapes"] = zip_path
                if cleanup_after_zip:
                    self._safe_rmtree(shp_folder)

        if "gpkg" in exports and processing is not None:
            gpkg_path = os.path.join(gpkg_folder, f"{project_name}.gpkg")
            gpkg_params = {
                "LAYERS": layers,
                "OUTPUT": gpkg_path,
                "OVERWRITE": gpkg_opts.get("OVERWRITE", True),
                "SAVE_STYLE": gpkg_opts.get("SAVE_STYLE", True),
                "SAVE_METADATA": gpkg_opts.get("SAVE_METADATA", True),
            }
            try:
                processing.run("native:package", gpkg_params)
            except Exception:
                pass

            if do_zip:
                zip_path = os.path.join(export_folder, f"{project_name}_gpkg.zip")
                self._zip_folder(gpkg_folder, zip_path)
                created_zips["gpkg"] = zip_path
                if cleanup_after_zip:
                    self._safe_rmtree(gpkg_folder)
        elif "gpkg" in exports and processing is None:
            warnings.append("GPKG Export deaktiviert: Processing-Plugin fehlt.")

        if "dxf" in exports and processing is not None:
            try:
                dxf_algorithm = QgsApplication.processingRegistry().algorithmById(
                    "native:dxfexport"
                )
            except Exception:
                dxf_algorithm = None

            if dxf_algorithm is None:
                warnings.append(
                    "DXF Export nicht verfuegbar: Algorithmus 'native:dxfexport' fehlt."
                )
            else:
                dxf_errors: List[str] = []
                dxf_path = os.path.join(dxf_folder, f"{project_name}.dxf")
                project_crs = QgsProject.instance().crs()
                label_field = dxf_opts.get("LABEL_FIELD")

                def build_layer_defs(layer_value):
                    return [
                        {
                            "layer": layer_value(layer),
                            "attributeIndex": (
                                layer.fields().indexOf(label_field)
                                if label_field and layer.fields().indexOf(label_field) >= 0
                                else -1
                            ),
                            "overriddenLayerName": "",
                            "buildDataDefinedBlocks": True,
                            "dataDefinedBlocksMaximumNumberOfClasses": -1,
                        }
                        for layer in layers
                    ]

                dxf_params_base = {
                    "SYMBOLOGY_MODE": dxf_opts.get("SYMBOLOGY_MODE", 2),
                    "SYMBOLOGY_SCALE": dxf_opts.get("SYMBOLOGY_SCALE", 250),
                    "MAP_THEME": dxf_opts.get("MAP_THEME", None),
                    "ENCODING": dxf_opts.get("ENCODING", "cp1252"),
                    "CRS": dxf_opts.get("CRS", project_crs),
                    "EXTENT": dxf_opts.get("EXTENT", None),
                    "SELECTED_FEATURES_ONLY": dxf_opts.get("SELECTED_FEATURES_ONLY", False),
                    "USE_LAYER_TITLE": dxf_opts.get("USE_LAYER_TITLE", False),
                    "MTEXT": dxf_opts.get("MTEXT", True),
                    "EXPORT_LINES_WITH_ZERO_WIDTH": dxf_opts.get(
                        "EXPORT_LINES_WITH_ZERO_WIDTH",
                        False,
                    ),
                    "LABEL_FIELD": dxf_opts.get("LABEL_FIELD"),
                    "OUTPUT": dxf_path,
                }

                def try_dxf(layer_defs):
                    try:
                        if os.path.exists(dxf_path):
                            os.remove(dxf_path)
                    except Exception:
                        pass
                    try:
                        params = dict(dxf_params_base)
                        params["LAYERS"] = layer_defs
                        processing.run("native:dxfexport", params)
                    except Exception as exc:
                        dxf_errors.append(str(exc))
                        return False
                    return os.path.exists(dxf_path) and os.path.getsize(dxf_path) > 0

                ok = try_dxf(build_layer_defs(lambda layer: layer.source()))
                if not ok:
                    ok = try_dxf(build_layer_defs(lambda layer: layer))
                if not ok:
                    try:
                        params = dict(dxf_params_base)
                        params["LAYERS"] = layers
                        processing.run("native:dxfexport", params)
                        ok = os.path.exists(dxf_path) and os.path.getsize(dxf_path) > 0
                    except Exception as exc:
                        dxf_errors.append(str(exc))

                if not ok:
                    detail = f" ({dxf_errors[-1]})" if dxf_errors else ""
                    warnings.append(f"DXF Export fehlgeschlagen.{detail}")
                elif do_zip:
                    zip_path = os.path.join(export_folder, f"{project_name}_dxf.zip")
                    self._zip_folder(dxf_folder, zip_path)
                    created_zips["dxf"] = zip_path
                    if cleanup_after_zip:
                        self._safe_rmtree(dxf_folder)
        elif "dxf" in exports and processing is None:
            warnings.append("DXF Export deaktiviert: Processing-Plugin fehlt.")

        if not kml_opts.get("DISABLED", False):
            temp_dir = tempfile.mkdtemp(prefix="trassify_kml_")
            exported_kmls: List[str] = []

            for layer in layers:
                layer_name = self._clean_layer_name(layer.name()).replace(" ", "_")
                temp_kml_path = os.path.join(temp_dir, f"{layer_name}.kml")

                save_options = QgsVectorFileWriter.SaveVectorOptions()
                save_options.driverName = "KML"
                save_options.fileEncoding = "UTF-8"
                save_options.symbologyScale = kml_opts.get("SYMBOLOGY_SCALE", 250)
                save_options.symbologyExport = kml_opts.get(
                    "SYMBOLOGY_EXPORT",
                    QgsVectorFileWriter.SymbolLayerSymbology,
                )
                name_field = kml_opts.get("NAME_FIELD")
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
                        try:
                            tree = xml_et.parse(kml_path)
                            sub_root = tree.getroot()
                            for element in sub_root.iter():
                                if element.tag.endswith("Placemark") or element.tag.endswith("Style"):
                                    document.append(element)
                        except Exception:
                            continue
                    xml_et.ElementTree(root).write(
                        output_kml_path,
                        encoding="utf-8",
                        xml_declaration=True,
                    )
                except Exception:
                    try:
                        if exported_kmls:
                            shutil.copy(exported_kmls[0], output_kml_path)
                    except Exception:
                        pass

            if kml_opts.get("ZIP", True) and os.path.exists(output_kml_path):
                zip_path = os.path.join(export_folder, f"{project_name}_kml.zip")
                try:
                    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
                        zip_file.write(output_kml_path, os.path.basename(output_kml_path))
                    if cleanup_after_zip:
                        try:
                            os.remove(output_kml_path)
                        except Exception:
                            pass
                    created_zips["kml"] = zip_path
                except Exception:
                    pass

            self._safe_rmtree(temp_dir)

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

        output_kml_path = os.path.join(export_folder, f"{project_name}.kml")
        return {
            "data_folder": data_folder,
            "svg_folder": svg_folder,
            "export_folder": export_folder,
            "zips": created_zips,
            "kml": output_kml_path if os.path.exists(output_kml_path) else None,
            "status_json": status_json_path,
            "geojson_manifest": (
                geojson_manifest_path if os.path.exists(geojson_manifest_path) else None
            ),
            "export_manifest": (
                export_manifest_path if os.path.exists(export_manifest_path) else None
            ),
            "warnings": warnings,
        }

    def _get_layer_group_path(self, layer) -> List[str]:
        tree_layer = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
        if not tree_layer:
            return []
        group_path: List[str] = []
        parent = tree_layer.parent()
        while parent and parent.name():
            group_path.insert(0, self._clean_layer_name(parent.name()))
            parent = parent.parent()
        return group_path

    def _clean_layer_name(self, text: Optional[str]) -> str:
        try:
            value = text or ""
        except Exception:
            return ""
        if not isinstance(value, str):
            try:
                value = str(value)
            except Exception:
                return ""
        value = value.replace("\u00A0", " ").strip()
        if any(char in value for char in ("Ã", "Â", "Ð", "�")):
            try:
                repaired = value.encode("latin-1").decode("utf-8")
                if repaired:
                    value = repaired
            except Exception:
                pass
        return value

    def _style_from_symbol(self, symbol, svg_folder: str, data_folder: str) -> Dict[str, Any]:
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
                    relative_svg_path = os.path.relpath(
                        target_path,
                        start=data_folder,
                    ).replace("\\", "/")
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

    def _visible_fields(self, layer, blacklist: List[str]) -> List[str]:
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

    def _get_label_expression(self, layer) -> Optional[str]:
        try:
            if layer.labelsEnabled():
                settings = layer.labeling().settings()
                expression = settings.fieldName() or settings.format().expression()
                if not expression and settings.format().expressionString():
                    expression = settings.format().expressionString()
                return expression if expression else None
        except Exception:
            pass
        return None

    def _collect_manifest_entries(
        self,
        base_folder: str,
        allowed_exts: Optional[set[str]] = None,
    ) -> List[str]:
        normalized_exts = {ext.lower() for ext in allowed_exts} if allowed_exts else None
        entries: List[str] = []
        for root_dir, _dirs, files in os.walk(base_folder):
            for file_name in files:
                extension = os.path.splitext(file_name)[1].lower()
                if normalized_exts is not None and extension not in normalized_exts:
                    continue
                path = os.path.join(root_dir, file_name)
                try:
                    relative_path = os.path.relpath(path, start=base_folder)
                except Exception:
                    relative_path = file_name
                entries.append(relative_path.replace("\\", "/"))
        deduped = []
        seen = set()
        for entry in sorted(entries):
            if entry in seen:
                continue
            seen.add(entry)
            deduped.append(entry)
        return deduped

    def _write_manifest_file(self, path: str, entries: List[str]):
        try:
            with open(path, "w", encoding="utf-8") as file_obj:
                json.dump(entries, file_obj, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _zip_folder(self, folder_path: str, zip_path: str):
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for root_dir, _dirs, files in os.walk(folder_path):
                for file_name in files:
                    file_path = os.path.join(root_dir, file_name)
                    arcname = os.path.relpath(file_path, start=folder_path)
                    zip_file.write(file_path, arcname)

    def _safe_rmtree(self, folder_path: str):
        try:
            shutil.rmtree(folder_path)
        except Exception:
            pass
