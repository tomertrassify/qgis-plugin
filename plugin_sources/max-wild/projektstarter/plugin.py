import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from os.path import relpath
from pathlib import Path
from shutil import copy2, move
from urllib.error import URLError
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QFile, QIODevice, QSettings, QTimer
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMenu, QToolBar
from qgis.core import (
    Qgis,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsDxfExport,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsMapLayerUtils,
    QgsMapSettings,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsRendererCategory,
    QgsSymbol,
    QgsVectorFileWriter,
    QgsVectorLayer,
)


class ProjectStarterPlugin:
    REQUIRED_FOLDERS = (
        "001_Projektinfos",
        "002_Leitungsauskunft",
        "003_Ergebnis",
    )
    SETTINGS_KEY = "projektstarter/last_project_dir"
    LEGACY_SETTINGS_KEYS = ("max_wild_project_starter/last_project_dir",)
    PROJECT_AREA_LAYER_NAME = "Projektgebiet"
    GROUP_PROJECT = "001 Projekt"
    GROUP_GEOREF = "002 Georeferenzierte Pläne"
    GROUP_BASEMAPS = "003 Basemaps/ ALKIS"
    LEGACY_GROUP_PREFIX = "Projektstarter"
    OSM_LAYER_NAME = "OSM Standard"
    KML_STYLE_FIELD = "Sparte"
    SUBLAYER_SEPARATOR = "!!::!!"
    TEMPLATE_PREFERRED_FILENAMES = (
        "Vorgabe.gpkg",
        "Vorlage.gpkg",
    )
    STYLE_FILENAME = "projektgebiet-styling.qml"
    GEOBASIS_CONFIG_FILENAME = "geobasis_actions.conf.json"
    TOOLBAR_NAME = "Projektstarter"
    TOOLBAR_OBJECT_NAME = "ProjektstarterToolbar"
    DEFAULT_ICON_FILENAME = "projektstarter-favicon.svg"
    CONNECTED_ICON_FILENAME = "projektstarter-connected.svg"
    PROJECT_ENTRY_SCOPE = "projektstarter"
    LEGACY_PROJECT_ENTRY_SCOPES = ("max_wild_project_starter",)
    CONNECTION_ENABLED_KEY = "connection_enabled"
    CONNECTION_PROJECT_DIR_KEY = "project_dir"
    GEOREF_LAYER_KEY_PROPERTY = "projektstarter/georef_key"
    GEOREF_OPERATOR_PROPERTY = "projektstarter/georef_operator"
    LEGACY_GEOREF_LAYER_KEY_PROPERTIES = ("max_wild_project_starter/georef_key",)
    LEGACY_GEOREF_OPERATOR_PROPERTIES = ("max_wild_project_starter/georef_operator",)
    GEOREF_CANONICAL_FOLDER_NAME = "_Georeferenzierte Pläne"
    GEOREF_FOLDER_NAMES = (
        "_Georeferenzierte Plaene",
        "_Georeferenzierte Pläne",
        "Georeferenzierte Plaene",
        "Georeferenzierte Pläne",
        "Georefrenzierte Plaene",
        "Georefrenzierte Pläne",
    )
    GEOTIFF_EXTENSIONS = (".tif", ".tiff")
    GEOTIFF_SIDECAR_SUFFIXES = (
        ".tfw",
        ".tfwx",
        ".wld",
        ".prj",
        ".aux",
        ".xml",
        ".ovr",
        ".points",
    )
    EXPORT_SHP_DIRNAME = "Export_SHP"
    EXPORT_KML_DIRNAME = "Export_KML"
    EXPORT_GEOJSON_DIRNAME = "Export_GeoJSON"
    EXPORT_MANIFEST_FILENAME = ".projektstarter_export_manifest.json"
    LEGACY_EXPORT_MANIFEST_FILENAMES = (".max_wild_export_manifest.json",)
    SHAPEFILE_EXPORT_SUFFIXES = (
        ".shp",
        ".shx",
        ".dbf",
        ".prj",
        ".cpg",
        ".qpj",
        ".qix",
        ".sbn",
        ".sbx",
        ".fbn",
        ".fbx",
        ".ain",
        ".aih",
        ".atx",
        ".ixs",
        ".mxs",
        ".shp.xml",
    )
    EXPORT_ZOOM_DELAY_MS = 250
    EXPORT_SYNC_DELAY_MS = 250
    DEFAULT_PROJECT_CRS = "EPSG:25832"
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

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = Path(__file__).resolve().parent
        self.action = None
        self.toolbar = None
        self.wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        self._config_warning_shown = False
        self._current_project_dir = None
        self._managed_layers = []
        self._export_sync_pending = False
        self._pending_zoom_layer_id = None
        self._pending_zoom_extent = None
        self._resaving_after_georef_sync = False

    def initGui(self):
        self.action = QAction(QIcon(str(self._icon_path())), "Projektstarter", self.iface.mainWindow())
        self.action.triggered.connect(self.run)

        self.toolbar = self.iface.addToolBar(self.TOOLBAR_NAME)
        self.toolbar.setObjectName(self.TOOLBAR_OBJECT_NAME)
        self.toolbar.setToolTip(self.TOOLBAR_NAME)
        self.toolbar.setWindowIcon(QIcon(str(self._icon_path())))
        self.toolbar.addAction(self.action)

        self.iface.addPluginToMenu(self.TOOLBAR_NAME, self.action)

        project = QgsProject.instance()
        project.readProject.connect(self._on_project_read)
        project.projectSaved.connect(self._on_project_saved)
        project.cleared.connect(self._on_project_cleared)
        QTimer.singleShot(0, self._refresh_connection_state)

    def unload(self):
        action = self.action
        toolbar = self._find_toolbar()

        self.action = None
        self.toolbar = None

        project = QgsProject.instance()
        try:
            project.readProject.disconnect(self._on_project_read)
        except TypeError:
            pass
        try:
            project.projectSaved.disconnect(self._on_project_saved)
        except TypeError:
            pass
        try:
            project.cleared.disconnect(self._on_project_cleared)
        except TypeError:
            pass

        self._clear_managed_layer_connections()

        if self._is_qt_object_alive(action):
            self._safe_qt_call(self.iface.removePluginMenu, self.TOOLBAR_NAME, action)
            self._safe_qt_call(action.deleteLater)

        if self._is_qt_object_alive(toolbar):
            self._safe_qt_call(self.iface.mainWindow().removeToolBar, toolbar)
            self._safe_qt_call(toolbar.deleteLater)

        self._current_project_dir = None
        self._pending_zoom_layer_id = None
        self._pending_zoom_extent = None
        self._export_sync_pending = False
        self._resaving_after_georef_sync = False

    def _find_toolbar(self):
        try:
            return self.iface.mainWindow().findChild(QToolBar, self.TOOLBAR_OBJECT_NAME)
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

    def run(self):
        if self._has_active_connection():
            self._show_connection_menu()
            return

        self._select_and_connect_project()

    def _select_and_connect_project(self):
        project_dir = self._select_project_directory()
        if not project_dir:
            return

        self._connect_project(project_dir)

    def _connect_project(self, project_dir, notify=True):
        if project_dir is None:
            return

        validation_error = self._validate_project_directory(project_dir)
        if validation_error:
            self._show_message("Projektstarter", validation_error, Qgis.Warning)
            return

        kml_file = self._find_kml_file(project_dir / "001_Projektinfos")
        if not kml_file:
            self._show_message(
                "Projektstarter",
                "Im Ordner 001_Projektinfos wurde keine KML-Datei gefunden.",
                Qgis.Warning,
            )
            return

        kml_layer = self._create_kml_layer(kml_file)
        if not kml_layer:
            return

        project_gpkg = self._prepare_project_geopackage(project_dir)
        if not project_gpkg:
            return

        if not self._write_project_area_to_geopackage(kml_layer, project_gpkg):
            return

        preserve_manual_georef = self._should_preserve_manual_georef_layers(project_dir)
        project_group, georef_group, basemap_group = self._prepare_workspace_groups(
            project_dir,
            preserve_manual_georef=preserve_manual_georef,
        )
        project_area_layer = self._load_project_geopackage_layers(project_gpkg, project_group)
        if not project_area_layer:
            self._show_message(
                "Projektstarter",
                "Das GeoPackage wurde erstellt, aber das Projektgebiet konnte nicht geladen werden.",
                Qgis.Warning,
            )
            return

        self._current_project_dir = project_dir
        self._store_connection_state(True, project_dir)
        self._register_managed_project_layers(project_group)
        self._update_connection_icon(bool(self._managed_layers))
        self._sync_georeferenced_plans(georef_group=georef_group, notify=False)

        self._add_osm_basemap(basemap_group)
        self._load_alkis_for_project(project_area_layer, basemap_group)
        self._export_auxiliary_formats(notify=False)
        self._save_project_file(project_dir, notify=False, sync_georef=False)
        self._schedule_final_zoom(project_area_layer)
        if notify:
            self._show_message(
                "Projektstarter",
                f"Projektordner geladen: {project_dir.name}",
                Qgis.Success,
            )

    def _has_active_connection(self):
        return self._current_project_dir is not None and bool(self._managed_layers)

    def _show_connection_menu(self):
        menu = QMenu(self.iface.mainWindow())
        refresh_action = menu.addAction("Verbindung aktualisieren")
        leitungsauskunft_action = menu.addAction("Leitungsauskunft aktualisieren")
        export_action = menu.addAction("Exporte jetzt aktualisieren")
        zoom_action = menu.addAction("Zum Projektgebiet zoomen")
        save_action = menu.addAction("Projekt speichern")
        menu.addSeparator()
        switch_action = menu.addAction("Projektordner neu waehlen")
        disconnect_action = menu.addAction("Verbindung trennen")

        widget = self.toolbar.widgetForAction(self.action) if self.toolbar and self.action else None
        if widget is not None:
            global_pos = widget.mapToGlobal(widget.rect().bottomLeft())
        else:
            global_pos = self.iface.mainWindow().mapToGlobal(self.iface.mainWindow().rect().center())

        selected_action = menu.exec(global_pos)
        if selected_action is refresh_action:
            self._refresh_current_connection()
        elif selected_action is leitungsauskunft_action:
            self._refresh_leitungsauskunft()
        elif selected_action is export_action:
            self._export_auxiliary_formats(notify=True)
        elif selected_action is zoom_action:
            self._zoom_to_project_area_now()
        elif selected_action is save_action:
            if self._current_project_dir is not None:
                self._save_project_file(self._current_project_dir, notify=True)
        elif selected_action is switch_action:
            self._select_and_connect_project()
        elif selected_action is disconnect_action:
            self._disconnect_current_connection()

    def _refresh_current_connection(self):
        if self._current_project_dir is None:
            return
        self._connect_project(self._current_project_dir)

    def _refresh_leitungsauskunft(self):
        if self._current_project_dir is None:
            return

        changed = self._sync_georeferenced_plans(notify=False)
        if changed:
            self._save_project_file(self._current_project_dir, notify=False, sync_georef=False)
            self._show_message(
                "Projektstarter",
                "Leitungsauskunft wurde aktualisiert.",
                Qgis.Success,
            )
            return

        self._show_message(
            "Projektstarter",
            "Keine neuen oder geaenderten GeoTIFFs gefunden.",
            Qgis.Info,
        )

    def _zoom_to_project_area_now(self):
        layer = self._project_area_layer()
        if layer is None:
            self._show_message(
                "Projektstarter",
                "Projektgebiet konnte im verbundenen Projekt nicht gefunden werden.",
                Qgis.Warning,
            )
            return

        self._zoom_to_layer(layer)

    def _disconnect_current_connection(self):
        project_dir = self._current_project_dir
        self._store_connection_state(False)
        self._current_project_dir = None
        self._clear_managed_layer_connections()
        self._pending_zoom_layer_id = None
        self._pending_zoom_extent = None
        self._export_sync_pending = False
        self._update_connection_icon(False)

        if project_dir is not None:
            self._save_project_file(project_dir, notify=False)

        self._show_message(
            "Projektstarter",
            "Verbindung zum Projektordner wurde getrennt.",
            Qgis.Info,
        )

    def _select_project_directory(self):
        settings = QSettings()
        start_dir = self._read_setting_value(
            settings,
            self.SETTINGS_KEY,
            self.LEGACY_SETTINGS_KEYS,
            str(Path.home()),
        )
        selected_dir = QFileDialog.getExistingDirectory(
            self.iface.mainWindow(),
            "Projektordner waehlen",
            start_dir,
            QFileDialog.ShowDirsOnly,
        )

        if not selected_dir:
            return None

        settings.setValue(self.SETTINGS_KEY, selected_dir)
        return Path(selected_dir)

    def _validate_project_directory(self, project_dir):
        if not project_dir.exists() or not project_dir.is_dir():
            return "Der ausgewaehlte Pfad ist kein gueltiger Projektordner."

        missing_folders = [
            folder_name
            for folder_name in self.REQUIRED_FOLDERS
            if not (project_dir / folder_name).is_dir()
        ]
        if missing_folders:
            folder_list = ", ".join(missing_folders)
            return f"Folgende Pflichtordner fehlen: {folder_list}"

        return None

    def _find_kml_file(self, project_info_dir):
        kml_files = sorted(
            file_path
            for file_path in project_info_dir.iterdir()
            if file_path.is_file() and file_path.suffix.lower() == ".kml"
        )
        if not kml_files:
            return None

        if len(kml_files) > 1:
            self._show_message(
                "Projektstarter",
                f"Mehrere KML-Dateien gefunden. Es wird {kml_files[0].name} verwendet.",
                Qgis.Info,
            )

        return kml_files[0]

    def _create_kml_layer(self, kml_file):
        layer = QgsVectorLayer(str(kml_file), kml_file.stem, "ogr")
        if not layer.isValid():
            self._show_message(
                "Projektstarter",
                f"Die KML-Datei konnte nicht geladen werden: {kml_file.name}",
                Qgis.Critical,
            )
            return None

        return layer

    def _prepare_project_geopackage(self, project_dir):
        self._configure_project(project_dir)

        template_source = self._find_template_source()
        if not template_source:
            self._show_message(
                "Projektstarter",
                "Keine Vorgabe-GPKG gefunden. Der Projektstart laedt nur die KML.",
                Qgis.Warning,
            )
            return None

        target_gpkg = project_dir / "003_Ergebnis" / f"{project_dir.name}.gpkg"
        if not target_gpkg.exists():
            try:
                copy2(template_source, target_gpkg)
            except OSError as error:
                self._show_message(
                    "Projektstarter",
                    f"GeoPackage konnte nicht erstellt werden: {error}",
                    Qgis.Critical,
                )
                return None

        return target_gpkg

    def _configure_project(self, project_dir):
        project = QgsProject.instance()
        project_file = self._project_file_path(project_dir)
        project.setPresetHomePath(str(project_dir))
        project.setTitle(project_dir.name)
        project.setFileName(str(project_file))
        self._set_relative_project_paths(project)

        project_crs = self._read_project_crs(project_file)
        if project_crs is None:
            project_crs = QgsCoordinateReferenceSystem(self.DEFAULT_PROJECT_CRS)
        if project_crs.isValid():
            project.setCrs(project_crs)

    def _project_file_path(self, project_dir):
        return project_dir / "001_Projektinfos" / f"{project_dir.name}.qgz"

    def _project_geopackage_path(self, project_dir):
        return project_dir / "003_Ergebnis" / f"{project_dir.name}.gpkg"

    def _current_project_file_path(self):
        project_file = str(QgsProject.instance().fileName() or "").strip()
        if not project_file:
            return None
        return Path(project_file)

    def _portable_project_dir_value(self, project_dir):
        project_file = self._current_project_file_path()
        if project_file is not None:
            try:
                return relpath(str(project_dir), start=str(project_file.parent))
            except (OSError, ValueError):
                pass
        return str(project_dir)

    def _resolve_project_dir_value(self, stored_value):
        stored_value = str(stored_value or "").strip()
        if not stored_value:
            return None

        stored_path = Path(stored_value).expanduser()
        if stored_path.is_absolute():
            return stored_path

        project_file = self._current_project_file_path()
        if project_file is None:
            return None

        try:
            return (project_file.parent / stored_path).resolve()
        except OSError:
            return project_file.parent / stored_path

    def _set_relative_project_paths(self, project):
        if not hasattr(project, "setFilePathStorage"):
            return

        file_path_type = getattr(Qgis, "FilePathType", None)
        relative_path_type = getattr(file_path_type, "Relative", None)
        if relative_path_type is None:
            return

        try:
            project.setFilePathStorage(relative_path_type)
        except (AttributeError, TypeError):
            return

    def _read_setting_value(self, settings, primary_key, legacy_keys, default_value):
        value = settings.value(primary_key, None)
        if value not in (None, ""):
            return value

        for legacy_key in legacy_keys:
            value = settings.value(legacy_key, None)
            if value not in (None, ""):
                return value

        return default_value

    def _project_entry_scopes(self):
        return (self.PROJECT_ENTRY_SCOPE, *self.LEGACY_PROJECT_ENTRY_SCOPES)

    def _read_project_bool_entry(self, entry_key, default_value):
        project = QgsProject.instance()
        for scope in self._project_entry_scopes():
            value, ok = project.readBoolEntry(scope, entry_key, default_value)
            if ok:
                return bool(value)
        return bool(default_value)

    def _read_project_entry(self, entry_key, default_value=""):
        project = QgsProject.instance()
        for scope in self._project_entry_scopes():
            value, ok = project.readEntry(scope, entry_key, default_value)
            if ok:
                return value
        return default_value

    def _project_connection_enabled(self):
        return self._read_project_bool_entry(self.CONNECTION_ENABLED_KEY, True)

    def _store_connection_state(self, connected, project_dir=None):
        project = QgsProject.instance()
        project.writeEntryBool(
            self.PROJECT_ENTRY_SCOPE,
            self.CONNECTION_ENABLED_KEY,
            bool(connected),
        )
        if connected and project_dir is not None:
            project.writeEntry(
                self.PROJECT_ENTRY_SCOPE,
                self.CONNECTION_PROJECT_DIR_KEY,
                self._portable_project_dir_value(project_dir),
            )
        else:
            project.writeEntry(
                self.PROJECT_ENTRY_SCOPE,
                self.CONNECTION_PROJECT_DIR_KEY,
                "",
            )

    def _read_project_crs(self, project_file):
        if not project_file.is_file():
            return None

        try:
            with ZipFile(project_file, "r") as archive:
                qgs_name = next(
                    (name for name in archive.namelist() if name.lower().endswith(".qgs")),
                    None,
                )
                if not qgs_name:
                    return None
                project_xml = archive.read(qgs_name)
        except (OSError, KeyError, BadZipFile):
            return None

        try:
            root = ET.fromstring(project_xml)
        except ET.ParseError:
            return None

        auth_id = root.findtext(".//projectCrs/spatialrefsys/authid")
        if auth_id:
            crs = QgsCoordinateReferenceSystem(auth_id)
            if crs.isValid():
                return crs

        epsg_code = root.findtext(".//projectCrs/spatialrefsys/epsg")
        if epsg_code and str(epsg_code).isdigit():
            crs = QgsCoordinateReferenceSystem(f"EPSG:{epsg_code}")
            if crs.isValid():
                return crs

        return None

    def _save_project_file(self, project_dir, notify=False, sync_georef=True):
        project = QgsProject.instance()
        project_file = self._project_file_path(project_dir)
        project.setFileName(str(project_file))
        self._set_relative_project_paths(project)
        if sync_georef and self._current_project_dir is not None:
            self._sync_georeferenced_plans(notify=False)

        if project.write():
            if notify:
                self._show_message(
                    "Projektstarter",
                    f"Projekt gespeichert: {project_file.name}",
                    Qgis.Success,
                )
            return True

        self._show_message(
            "Projektstarter",
            f"QGIS-Projekt konnte nicht gespeichert werden: {project_file.name}",
            Qgis.Warning,
        )
        return False

    def _find_template_source(self):
        candidate_directories = (
            self.plugin_dir / "template",
            self.plugin_dir.parent / "template",
        )
        template_files = []
        for directory in candidate_directories:
            if directory.is_dir():
                template_files.extend(sorted(directory.glob("*.gpkg")))

        if not template_files:
            return None

        for preferred_name in self.TEMPLATE_PREFERRED_FILENAMES:
            for template_file in template_files:
                if template_file.name == preferred_name:
                    return template_file

        return template_files[0]

    def _write_project_area_to_geopackage(self, kml_layer, gpkg_file):
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.fileEncoding = "UTF-8"
        options.layerName = self.PROJECT_AREA_LAYER_NAME
        options.onlySelectedFeatures = False
        options.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer

        error, _new_file, _new_layer, error_message = QgsVectorFileWriter.writeAsVectorFormatV3(
            kml_layer,
            str(gpkg_file),
            QgsProject.instance().transformContext(),
            options,
        )
        if int(error) != 0:
            self._show_message(
                "Projektstarter",
                error_message or "Die KML konnte nicht in das GeoPackage geschrieben werden.",
                Qgis.Critical,
            )
            return False

        return True

    def _prepare_workspace_groups(self, project_dir, preserve_manual_georef=False):
        root = QgsProject.instance().layerTreeRoot()
        self._clear_managed_layer_connections()
        self._remove_legacy_group(root, project_dir)

        project_group = self._get_or_create_root_group(root, self.GROUP_PROJECT, 0)
        georef_group = self._get_or_create_root_group(root, self.GROUP_GEOREF, 1)
        basemap_group = self._get_or_create_root_group(root, self.GROUP_BASEMAPS, 2)

        self._reset_group(project_group)
        if preserve_manual_georef:
            self._reset_managed_georef_group(georef_group)
        else:
            self._reset_group(georef_group)
        self._reset_group(basemap_group)
        return project_group, georef_group, basemap_group

    def _should_preserve_manual_georef_layers(self, project_dir):
        if project_dir is None:
            return False
        if self._current_project_dir == project_dir:
            return True
        return self._detect_connected_project_dir() == project_dir

    def _remove_legacy_group(self, root, project_dir):
        legacy_group = self._find_root_group(root, f"{self.LEGACY_GROUP_PREFIX} - {project_dir.name}")
        if not legacy_group:
            return

        layer_ids = self._collect_layer_ids(legacy_group)
        if layer_ids:
            QgsProject.instance().removeMapLayers(layer_ids)
        root.removeChildNode(legacy_group)

    def _get_or_create_root_group(self, root, group_name, index):
        group = self._find_root_group(root, group_name)
        if group is not None:
            return group
        return root.insertGroup(index, group_name)

    def _get_or_create_child_group(self, parent_group, group_name):
        for child in parent_group.children():
            if isinstance(child, QgsLayerTreeGroup) and child.name() == group_name:
                return child
        return parent_group.addGroup(group_name)

    def _find_root_group(self, root, group_name):
        for node in root.children():
            if isinstance(node, QgsLayerTreeGroup) and node.name() == group_name:
                return node
        return None

    def _reset_group(self, group):
        layer_ids = self._collect_layer_ids(group)
        if layer_ids:
            QgsProject.instance().removeMapLayers(layer_ids)
        self._clear_group_children(group)

    def _collect_layer_ids(self, group):
        layer_ids = []
        for child in group.children():
            if isinstance(child, QgsLayerTreeLayer):
                layer_ids.append(child.layerId())
            elif isinstance(child, QgsLayerTreeGroup):
                layer_ids.extend(self._collect_layer_ids(child))
        return list(dict.fromkeys(layer_ids))

    def _clear_group_children(self, group):
        for child in list(group.children())[::-1]:
            group.removeChildNode(child)

    def _reset_managed_georef_group(self, group):
        layer_ids = self._collect_managed_georef_layer_ids(group)
        if layer_ids:
            QgsProject.instance().removeMapLayers(layer_ids)
        self._remove_empty_groups(group)

    def _collect_managed_georef_layer_ids(self, group):
        layer_ids = []
        for child in group.children():
            if isinstance(child, QgsLayerTreeLayer):
                layer = child.layer()
                if self._managed_georef_layer_key(layer):
                    layer_ids.append(child.layerId())
            elif isinstance(child, QgsLayerTreeGroup):
                layer_ids.extend(self._collect_managed_georef_layer_ids(child))
        return list(dict.fromkeys(layer_ids))

    def _leitungsauskunft_directory(self):
        if self._current_project_dir is None:
            return None
        return self._current_project_dir / "002_Leitungsauskunft"

    def _sync_georeferenced_plans(self, georef_group=None, notify=False):
        if self._current_project_dir is None:
            return False

        if georef_group is None:
            georef_group = self._find_root_group(QgsProject.instance().layerTreeRoot(), self.GROUP_GEOREF)
        if georef_group is None:
            return False

        plan_entries = self._discover_georeferenced_plan_files()
        existing_layers = self._existing_georeferenced_layers(georef_group)
        changes_made = False
        warnings = []

        for entry in plan_entries:
            operator_group = self._get_or_create_child_group(georef_group, entry["operator"])
            existing = existing_layers.pop(entry["key"], None)
            if existing is None:
                layer = QgsRasterLayer(str(entry["path"]), entry["name"])
                if not layer.isValid():
                    warnings.append(entry["path"].name)
                    continue

                self._mark_georeferenced_layer(layer, entry["key"], entry["operator"])
                QgsProject.instance().addMapLayer(layer, False)
                operator_group.addLayer(layer)
                changes_made = True
                continue

            layer = existing["layer"]
            node = existing["node"]
            if self._update_georeferenced_layer(layer, entry):
                changes_made = True
            if self._ensure_layer_node_group(node, operator_group):
                changes_made = True

        for existing in existing_layers.values():
            layer = existing["layer"]
            if layer is not None:
                QgsProject.instance().removeMapLayer(layer.id())
                changes_made = True

        if self._remove_empty_groups(georef_group):
            changes_made = True

        if warnings:
            self._show_message(
                "Projektstarter",
                f"Mindestens ein GeoTIFF konnte nicht geladen werden: {warnings[0]}",
                Qgis.Warning,
            )
        elif notify and changes_made:
            self._show_message(
                "Projektstarter",
                "Georeferenzierte Plaene wurden aktualisiert.",
                Qgis.Info,
            )

        return changes_made

    def _discover_georeferenced_plan_files(self):
        leitungsauskunft_dir = self._leitungsauskunft_directory()
        if leitungsauskunft_dir is None or not leitungsauskunft_dir.is_dir():
            return []

        entries = []
        for operator_dir in sorted(
            (path for path in leitungsauskunft_dir.iterdir() if path.is_dir()),
            key=lambda path: path.name.casefold(),
        ):
            plan_dir = self._collect_operator_geotiffs(operator_dir)
            if plan_dir is None:
                continue

            for tif_path in sorted(
                (
                    path
                    for path in plan_dir.rglob("*")
                    if path.is_file() and path.suffix.lower() in self.GEOTIFF_EXTENSIONS
                ),
                key=lambda path: str(path).casefold(),
            ):
                entries.append(
                    {
                        "key": self._georef_layer_key(operator_dir.name, tif_path.name),
                        "operator": operator_dir.name,
                        "path": tif_path,
                        "name": tif_path.stem,
                    }
                )

        return entries

    def _collect_operator_geotiffs(self, operator_dir):
        plan_dir = self._ensure_operator_georef_dir(operator_dir)
        self._cleanup_operator_georef_files(operator_dir, plan_dir)
        discovered_tifs = []

        for path in sorted(operator_dir.rglob("*"), key=lambda item: str(item).casefold()):
            if not path.is_file() or path.suffix.lower() not in self.GEOTIFF_EXTENSIONS:
                continue
            if self._path_is_within(path, plan_dir):
                continue

            target_path = self._move_geotiff_bundle_to_plan_dir(path, plan_dir)
            if target_path is not None:
                discovered_tifs.append(target_path)

        for tif_path in sorted(
            (
                path
                for path in plan_dir.rglob("*")
                if path.is_file() and path.suffix.lower() in self.GEOTIFF_EXTENSIONS
            ),
            key=lambda path: str(path).casefold(),
        ):
            if tif_path not in discovered_tifs:
                discovered_tifs.append(tif_path)

        if not discovered_tifs:
            return None
        return plan_dir

    def _find_operator_georef_dir(self, operator_dir):
        for folder_name in self.GEOREF_FOLDER_NAMES:
            candidate = operator_dir / folder_name
            if candidate.is_dir():
                return candidate
        return None

    def _ensure_operator_georef_dir(self, operator_dir):
        canonical_dir = operator_dir / self.GEOREF_CANONICAL_FOLDER_NAME
        if canonical_dir.is_dir():
            return canonical_dir

        plan_dir = self._find_operator_georef_dir(operator_dir)
        if plan_dir is not None:
            try:
                plan_dir.rename(canonical_dir)
                return canonical_dir
            except OSError:
                return plan_dir

        canonical_dir.mkdir(parents=True, exist_ok=True)
        return canonical_dir

    def _cleanup_operator_georef_files(self, operator_dir, plan_dir):
        for path in sorted(operator_dir.rglob("*"), key=lambda item: str(item).casefold()):
            if not path.is_file():
                continue

            if path.name.casefold().endswith(".aux.xml"):
                try:
                    path.unlink()
                except OSError:
                    pass
                continue

            if self._path_is_within(path, plan_dir):
                continue

            if path.suffix.lower() == ".points":
                target_path = self._available_support_destination(plan_dir, path.name)
                self._move_file_if_needed(path, target_path)

    def _path_is_within(self, path, directory):
        try:
            path.resolve().relative_to(directory.resolve())
            return True
        except (OSError, ValueError):
            return False

    def _move_geotiff_bundle_to_plan_dir(self, tif_path, plan_dir):
        destination = self._available_geotiff_destination(plan_dir, tif_path.name)
        self._move_file_if_needed(tif_path, destination)

        for sidecar_path in self._geotiff_sidecar_files(tif_path):
            if sidecar_path.name.casefold().endswith(".aux.xml"):
                try:
                    sidecar_path.unlink()
                except OSError:
                    pass
                continue
            sidecar_name = sidecar_path.name.replace(tif_path.name, destination.name, 1)
            sidecar_destination = destination.parent / sidecar_name
            self._move_file_if_needed(sidecar_path, sidecar_destination)

        return destination

    def _available_geotiff_destination(self, plan_dir, file_name):
        candidate = plan_dir / file_name
        if not candidate.exists():
            return candidate

        stem = Path(file_name).stem
        suffix = Path(file_name).suffix
        index = 2
        while True:
            candidate = plan_dir / f"{stem}_{index}{suffix}"
            if not candidate.exists():
                return candidate
            index += 1

    def _available_support_destination(self, plan_dir, file_name):
        candidate = plan_dir / file_name
        if not candidate.exists():
            return candidate

        stem = Path(file_name).stem
        suffix = "".join(Path(file_name).suffixes) or Path(file_name).suffix
        if not suffix:
            suffix = Path(file_name).suffix
        base_name = file_name[: -len(suffix)] if suffix and file_name.endswith(suffix) else stem
        index = 2
        while True:
            candidate = plan_dir / f"{base_name}_{index}{suffix}"
            if not candidate.exists():
                return candidate
            index += 1

    def _geotiff_sidecar_files(self, tif_path):
        sidecars = []
        for sibling in tif_path.parent.iterdir():
            if not sibling.is_file() or sibling == tif_path:
                continue

            name_lower = sibling.name.casefold()
            tif_name_lower = tif_path.name.casefold()
            tif_stem_lower = tif_path.stem.casefold()
            if name_lower.startswith(f"{tif_name_lower}."):
                sidecars.append(sibling)
                continue
            if not name_lower.startswith(f"{tif_stem_lower}."):
                continue
            if sibling.suffix.lower() in self.GEOTIFF_SIDECAR_SUFFIXES:
                sidecars.append(sibling)

        return sidecars

    def _move_file_if_needed(self, source_path, destination_path):
        if source_path == destination_path:
            return

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if destination_path.exists():
            return
        move(str(source_path), str(destination_path))

    def _georef_layer_key(self, operator_name, file_name):
        return f"{str(operator_name).casefold()}::{str(file_name).casefold()}"

    def _existing_georeferenced_layers(self, georef_group):
        layers_by_key = {}
        for operator_group in georef_group.children():
            if not isinstance(operator_group, QgsLayerTreeGroup):
                continue

            operator_name = operator_group.name()
            for child in operator_group.children():
                if not isinstance(child, QgsLayerTreeLayer):
                    continue
                layer = child.layer()
                if not isinstance(layer, QgsRasterLayer):
                    continue

                key = self._managed_georef_layer_key(layer, operator_name)
                if key and key not in layers_by_key:
                    layers_by_key[key] = {
                        "layer": layer,
                        "node": child,
                    }
        return layers_by_key

    def _managed_georef_layer_key(self, layer, operator_name=None):
        if not isinstance(layer, QgsRasterLayer):
            return ""

        key = self._layer_custom_property(
            layer,
            self.GEOREF_LAYER_KEY_PROPERTY,
            self.LEGACY_GEOREF_LAYER_KEY_PROPERTIES,
        )
        if key:
            return key

        source_path = Path(str(layer.source() or "").split("|", 1)[0])
        leitungsauskunft_dir = self._leitungsauskunft_directory()
        if (
            leitungsauskunft_dir is None
            or source_path.suffix.lower() not in self.GEOTIFF_EXTENSIONS
            or not self._path_is_within(source_path, leitungsauskunft_dir)
        ):
            return ""

        derived_operator = self._layer_custom_property(
            layer,
            self.GEOREF_OPERATOR_PROPERTY,
            self.LEGACY_GEOREF_OPERATOR_PROPERTIES,
        )
        if not derived_operator:
            derived_operator = str(operator_name or "").strip()
        if not derived_operator:
            return ""

        return self._georef_layer_key(derived_operator, source_path.name)

    def _layer_custom_property(self, layer, primary_key, legacy_keys=()):
        value = str(layer.customProperty(primary_key, "") or "").strip()
        if value:
            return value

        for legacy_key in legacy_keys:
            value = str(layer.customProperty(legacy_key, "") or "").strip()
            if value:
                return value

        return ""

    def _remove_legacy_layer_properties(self, layer, legacy_keys):
        remove_property = getattr(layer, "removeCustomProperty", None)
        if remove_property is None:
            return

        for legacy_key in legacy_keys:
            try:
                remove_property(legacy_key)
            except Exception:
                continue

    def _mark_georeferenced_layer(self, layer, key, operator_name):
        layer.setCustomProperty(self.GEOREF_LAYER_KEY_PROPERTY, key)
        layer.setCustomProperty(self.GEOREF_OPERATOR_PROPERTY, operator_name)
        self._remove_legacy_layer_properties(layer, self.LEGACY_GEOREF_LAYER_KEY_PROPERTIES)
        self._remove_legacy_layer_properties(layer, self.LEGACY_GEOREF_OPERATOR_PROPERTIES)

    def _update_georeferenced_layer(self, layer, entry):
        changed = False
        source_path = str(entry["path"])
        current_source = str(layer.source() or "").split("|", 1)[0]
        if current_source != source_path or layer.name() != entry["name"]:
            layer.setDataSource(source_path, entry["name"], "gdal")
            changed = True

        if (
            self._layer_custom_property(
                layer,
                self.GEOREF_LAYER_KEY_PROPERTY,
                self.LEGACY_GEOREF_LAYER_KEY_PROPERTIES,
            )
            != entry["key"]
        ):
            changed = True
        if (
            self._layer_custom_property(
                layer,
                self.GEOREF_OPERATOR_PROPERTY,
                self.LEGACY_GEOREF_OPERATOR_PROPERTIES,
            )
            != entry["operator"]
        ):
            changed = True

        self._mark_georeferenced_layer(layer, entry["key"], entry["operator"])
        if changed:
            layer.triggerRepaint()
        return changed

    def _ensure_layer_node_group(self, node, target_group):
        parent = node.parent()
        if parent is target_group:
            return False
        if parent is None:
            return False

        target_group.insertChildNode(0, node.clone())
        parent.removeChildNode(node)
        return True

    def _remove_empty_groups(self, parent_group):
        removed_any = False
        for child in list(parent_group.children())[::-1]:
            if not isinstance(child, QgsLayerTreeGroup):
                continue
            if child.children():
                continue
            parent_group.removeChildNode(child)
            removed_any = True
        return removed_any

    def _load_project_geopackage_layers(self, gpkg_file, target_group):
        sublayer_names = self._list_sublayer_names(gpkg_file)
        if not sublayer_names:
            self._show_message(
                "Projektstarter",
                f"Im GeoPackage wurden keine Vektorlayer gefunden: {gpkg_file.name}",
                Qgis.Warning,
            )
            return None

        project_area_layer = None
        for sublayer_name in self._ordered_sublayer_names(sublayer_names):
            layer_source = f"{gpkg_file}|layername={sublayer_name}"
            layer = QgsVectorLayer(layer_source, sublayer_name, "ogr")
            if not layer.isValid():
                continue

            QgsProject.instance().addMapLayer(layer, False)
            target_group.addLayer(layer)
            if sublayer_name == self.PROJECT_AREA_LAYER_NAME:
                project_area_layer = layer
                self._apply_project_area_style(layer)

        return project_area_layer

    def _list_sublayer_names(self, gpkg_file):
        container_layer = QgsVectorLayer(str(gpkg_file), gpkg_file.stem, "ogr")
        if not container_layer.isValid():
            self._show_message(
                "Projektstarter",
                f"GeoPackage konnte nicht gelesen werden: {gpkg_file.name}",
                Qgis.Critical,
            )
            return []

        sublayer_names = []
        for sublayer in container_layer.dataProvider().subLayers():
            parts = sublayer.split(self.SUBLAYER_SEPARATOR)
            if len(parts) > 1:
                sublayer_names.append(parts[1])
        return sublayer_names

    def _ordered_sublayer_names(self, sublayer_names):
        ordered_names = []
        if self.PROJECT_AREA_LAYER_NAME in sublayer_names:
            ordered_names.append(self.PROJECT_AREA_LAYER_NAME)

        ordered_names.extend(
            sublayer_name
            for sublayer_name in sublayer_names
            if sublayer_name != self.PROJECT_AREA_LAYER_NAME
        )
        return ordered_names

    def _find_project_area_style_file(self):
        candidate_paths = (
            self.plugin_dir / "template" / self.STYLE_FILENAME,
            self.plugin_dir / self.STYLE_FILENAME,
            self.plugin_dir.parent / "template" / self.STYLE_FILENAME,
        )
        for candidate in candidate_paths:
            if candidate.is_file():
                return candidate
        return None

    def _apply_project_area_style(self, layer):
        style_file = self._find_project_area_style_file()
        if not style_file:
            return

        _message, ok = layer.loadNamedStyle(str(style_file))
        if ok:
            layer.triggerRepaint()
            layer_tree_view = getattr(self.iface, "layerTreeView", lambda: None)()
            if layer_tree_view:
                layer_tree_view.refreshLayerSymbology(layer.id())
        else:
            self._show_message(
                "Projektstarter",
                f"Projektgebiet-Styling konnte nicht geladen werden: {style_file.name}",
                Qgis.Warning,
            )

    def _register_managed_project_layers(self, project_group):
        self._clear_managed_layer_connections()

        managed_layers = []
        for child in project_group.children():
            if not isinstance(child, QgsLayerTreeLayer):
                continue
            layer = child.layer()
            if not isinstance(layer, QgsVectorLayer):
                continue
            if self._current_project_dir is not None and not self._is_managed_layer_source(layer):
                continue
            try:
                layer.afterCommitChanges.connect(self._on_managed_layer_committed)
            except TypeError:
                pass
            managed_layers.append(layer)

        self._managed_layers = managed_layers
        self._update_connection_icon(bool(self._current_project_dir and self._managed_layers))

    def _clear_managed_layer_connections(self):
        for layer in self._managed_layers:
            try:
                layer.afterCommitChanges.disconnect(self._on_managed_layer_committed)
            except Exception:
                pass
        self._managed_layers = []
        if self._current_project_dir is None:
            self._update_connection_icon(False)

    def _is_managed_layer_source(self, layer):
        if self._current_project_dir is None or layer is None:
            return False

        expected_source = str(self._project_geopackage_path(self._current_project_dir).resolve())
        layer_source = str(layer.source() or "").split("|", 1)[0]
        if not layer_source:
            return False

        try:
            return str(Path(layer_source).resolve()) == expected_source
        except OSError:
            return False

    def _icon_path(self, connected=False):
        icon_name = self.CONNECTED_ICON_FILENAME if connected else self.DEFAULT_ICON_FILENAME
        return self.plugin_dir / "assets" / icon_name

    def _update_connection_icon(self, connected):
        if self.action is None:
            return

        icon = QIcon(str(self._icon_path(connected)))
        self.action.setIcon(icon)
        if self.toolbar is not None:
            self.toolbar.setWindowIcon(icon)

    def _refresh_connection_state(self):
        if not self._project_connection_enabled():
            self._current_project_dir = None
            self._clear_managed_layer_connections()
            self._update_connection_icon(False)
            return

        project_dir = self._detect_connected_project_dir()
        if project_dir is None:
            self._current_project_dir = None
            self._clear_managed_layer_connections()
            self._update_connection_icon(False)
            return

        project_group = self._find_root_group(QgsProject.instance().layerTreeRoot(), self.GROUP_PROJECT)
        self._current_project_dir = project_dir
        self._store_connection_state(True, project_dir)
        if project_group is None:
            self._connect_project(project_dir, notify=False)
            return

        self._register_managed_project_layers(project_group)
        if not self._managed_layers or self._project_area_layer() is None:
            self._connect_project(project_dir, notify=False)
            return

        self._sync_georeferenced_plans(notify=False)

    def _detect_connected_project_dir(self):
        project = QgsProject.instance()
        project_file = self._current_project_file_path()
        if project_file is not None:
            project_info_dir = project_file.parent
            if project_info_dir.name == "001_Projektinfos":
                project_dir = project_info_dir.parent
                if self._is_connected_project_dir(project_dir, project_file):
                    return project_dir

        preset_home = str(project.presetHomePath() or "").strip()
        if preset_home:
            project_dir = Path(preset_home)
            if self._is_connected_project_dir(project_dir):
                return project_dir

        stored_dir = self._read_project_entry(self.CONNECTION_PROJECT_DIR_KEY, "")
        project_dir = self._resolve_project_dir_value(stored_dir)
        if project_dir is not None and self._is_connected_project_dir(project_dir, project_file):
            return project_dir

        return None

    def _is_connected_project_dir(self, project_dir, project_file=None):
        try:
            project_dir = Path(project_dir)
        except TypeError:
            return False

        if self._validate_project_directory(project_dir):
            return False

        if not self._project_geopackage_path(project_dir).is_file():
            return False

        if project_file is not None:
            expected_project_file = self._project_file_path(project_dir)
            try:
                if project_file.resolve() != expected_project_file.resolve():
                    return False
            except OSError:
                return False

        return True

    def _project_area_layer(self):
        for layer in self._managed_layers:
            if layer is not None and layer.name() == self.PROJECT_AREA_LAYER_NAME:
                return layer

        project_group = self._find_root_group(QgsProject.instance().layerTreeRoot(), self.GROUP_PROJECT)
        if project_group is None:
            return None

        for child in project_group.children():
            if not isinstance(child, QgsLayerTreeLayer):
                continue
            layer = child.layer()
            if isinstance(layer, QgsVectorLayer) and layer.name() == self.PROJECT_AREA_LAYER_NAME:
                return layer

        return None

    def _add_osm_basemap(self, target_group):
        uri = (
            "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            "&zmin=0&zmax=19"
        )
        layer = QgsRasterLayer(uri, self.OSM_LAYER_NAME, "wms")
        if not layer.isValid():
            self._show_message(
                "Projektstarter",
                "OSM Standard konnte nicht geladen werden.",
                Qgis.Warning,
            )
            return None

        QgsProject.instance().addMapLayer(layer, False)
        target_group.addLayer(layer)
        return layer

    def _load_alkis_for_project(self, project_area_layer, target_group):
        center = self._layer_center_wgs84(project_area_layer)
        if center is None:
            self._show_message(
                "Projektstarter",
                "Mittelpunkt des Projektgebiets konnte nicht nach WGS84 berechnet werden.",
                Qgis.Warning,
            )
            return

        geocode_data = self._reverse_geocode(center.y(), center.x(), timeout=3.5)
        bundesland = self._extract_state(geocode_data)
        if bundesland == "nicht verfuegbar":
            self._show_message(
                "Projektstarter",
                "Bundesland fuer ALKIS konnte nicht ermittelt werden.",
                Qgis.Warning,
            )
            return

        geobasis_plugin = self._find_geobasis_plugin()
        if geobasis_plugin is None:
            self._show_message(
                "Projektstarter",
                "GeoBasis_Loader ist nicht aktiv. OSM wurde trotzdem geladen.",
                Qgis.Warning,
            )
            return

        services = getattr(geobasis_plugin, "services", None)
        if not services:
            self._show_message(
                "Projektstarter",
                "GeoBasis_Loader ist noch nicht geladen. OSM wurde trotzdem geladen.",
                Qgis.Warning,
            )
            return

        state_match = self._match_geobasis_state(services, bundesland)
        if state_match is None:
            self._show_message(
                "Projektstarter",
                f"Bundesland '{bundesland}' wurde im GeoBasis-Katalog nicht gefunden.",
                Qgis.Warning,
            )
            return

        _state_key, state_data, state_name = state_match
        catalog_title = self._current_geobasis_catalog_title(geobasis_plugin)
        if not catalog_title:
            self._show_message(
                "Projektstarter",
                "Aktueller GeoBasis-Katalog konnte nicht ermittelt werden.",
                Qgis.Warning,
            )
            return

        configured_topics = self._find_configured_topics_for_state(
            state_data=state_data,
            state_name=state_name,
            raw_state_name=bundesland,
            topic_kind="parcel_building",
            catalog_title=catalog_title,
        )

        if not configured_topics:
            topic_path, topic_name = self._find_best_topic_for_state(state_data, "parcel_building")
            if topic_path:
                configured_topics = [(topic_path, topic_name or topic_path)]

        if not configured_topics:
            self._show_message(
                "Projektstarter",
                f"Kein passendes ALKIS-Thema in {state_name} gefunden.",
                Qgis.Warning,
            )
            return

        original_get_crs = self._patch_geobasis_project_crs(geobasis_plugin)
        try:
            if len(configured_topics) > 1:
                loaded_names = self._load_geobasis_topics_into_group(
                    geobasis_plugin=geobasis_plugin,
                    catalog_title=catalog_title,
                    topics=configured_topics,
                    target_group=target_group,
                )
            else:
                loaded_names = []
                first_path, first_name = configured_topics[0]
                before_count = len(QgsProject.instance().layerTreeRoot().children())
                if self._invoke_geobasis_add_topic(geobasis_plugin, catalog_title, first_path):
                    self._move_new_root_nodes_to_group(
                        QgsProject.instance().layerTreeRoot(),
                        target_group,
                        before_count,
                    )
                    loaded_names.append(first_name or first_path)
        finally:
            self._restore_geobasis_get_crs(geobasis_plugin, original_get_crs)

        if loaded_names:
            self._show_message(
                "Projektstarter",
                f"ALKIS geladen fuer {state_name}.",
                Qgis.Info,
            )

    def _layer_center_wgs84(self, layer):
        extent = layer.extent()
        if extent.isEmpty():
            return None

        center = extent.center()
        source_crs = layer.crs()
        if not source_crs.isValid() or source_crs.authid() == self.wgs84.authid():
            return center

        try:
            transform = QgsCoordinateTransform(source_crs, self.wgs84, QgsProject.instance())
            return transform.transform(center)
        except QgsCsException:
            return None

    def _reverse_geocode(self, lat, lon, timeout=8):
        url = (
            "https://nominatim.openstreetmap.org/reverse"
            f"?format=jsonv2&lat={lat:.8f}&lon={lon:.8f}&accept-language=de"
        )
        request = Request(
            url,
            headers={
                "User-Agent": "QGIS-Projektstarter/1.5.0 (https://qgis.org)",
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8")
        except (URLError, TimeoutError):
            return None

        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None

    def _extract_state(self, geocode_data):
        if not geocode_data:
            return "nicht verfuegbar"

        address = geocode_data.get("address") or {}
        return address.get("state") or "nicht verfuegbar"

    def _find_geobasis_plugin(self):
        try:
            import qgis.utils as qgis_utils
        except Exception:
            return None

        plugins = getattr(qgis_utils, "plugins", {}) or {}
        for plugin in plugins.values():
            if plugin is None:
                continue
            if plugin.__class__.__name__ == "GeoBasis_Loader" and hasattr(plugin, "add_topic"):
                return plugin

        for plugin in plugins.values():
            if plugin is None:
                continue
            if (
                hasattr(plugin, "add_topic")
                and hasattr(plugin, "services")
                and hasattr(plugin, "qgs_settings")
            ):
                return plugin

        return None

    def _current_geobasis_catalog_title(self, geobasis_plugin):
        qgs_settings = getattr(geobasis_plugin, "qgs_settings", None)
        if qgs_settings is None or not hasattr(qgs_settings, "value"):
            return None

        current_catalog = qgs_settings.value("geobasis_loader/current_catalog")
        if hasattr(current_catalog, "get"):
            return current_catalog.get("titel")
        return None

    def _match_geobasis_state(self, services, bundesland):
        state_name = self._canonical_state_name(bundesland)
        if not state_name:
            return None

        best_match = None
        best_score = 0.0
        for service in services:
            if not isinstance(service, (list, tuple)) or len(service) < 2:
                continue

            state_key, state_data = service[0], service[1]
            if not isinstance(state_data, dict):
                continue

            candidate_name = state_data.get("menu") or state_data.get("bundeslandname") or state_key
            candidate = self._canonical_state_name(candidate_name)
            if not candidate:
                continue

            if candidate == state_name:
                score = 1.0
            elif state_name in candidate or candidate in state_name:
                score = 0.9
            else:
                score = SequenceMatcher(None, state_name, candidate).ratio()

            if score > best_score:
                best_score = score
                best_match = (state_key, state_data, candidate_name)

        if best_score < 0.6:
            return None
        return best_match

    def _find_configured_topics_for_state(
        self, state_data, state_name, raw_state_name, topic_kind, catalog_title
    ):
        config = self._load_geobasis_actions_config()
        if not isinstance(config, dict):
            return []

        catalogs = config.get("catalogs")
        if not isinstance(catalogs, dict):
            return []

        catalog_cfg = catalogs.get(catalog_title) or catalogs.get("_default")
        if not isinstance(catalog_cfg, dict):
            return []

        states_cfg = catalog_cfg.get("states")
        if not isinstance(states_cfg, dict):
            return []

        state_cfg = self._match_state_config_entry(states_cfg, [state_name, raw_state_name])
        if not isinstance(state_cfg, dict):
            return []

        action_cfg = state_cfg.get(topic_kind)
        if action_cfg is None:
            return []

        topic_by_path = self._topics_by_path(state_data)
        if topic_kind == "parcel_building":
            selected_paths = self._select_parcel_building_paths(action_cfg, topic_by_path, topic_kind)
            if selected_paths:
                topics = []
                for path in selected_paths:
                    topic = topic_by_path.get(path)
                    topic_name = topic.get("name") if isinstance(topic, dict) else path
                    topics.append((path, topic_name or path))
                return topics

        selected = self._select_configured_path(action_cfg, topic_by_path, topic_kind)
        if not selected:
            return []

        path, topic = selected
        topic_name = topic.get("name") if isinstance(topic, dict) else None
        return [(path, (topic_name or path))]

    def _find_best_topic_for_state(self, state_data, topic_kind):
        topics = state_data.get("themen")
        if not isinstance(topics, dict):
            return None, None

        candidates = self._collect_topic_candidates(topics)
        best_path = None
        best_name = None
        best_score = -1
        for candidate in candidates:
            if not candidate.get("__loading__", True):
                continue

            score = self._score_topic(candidate, topic_kind)
            if score > best_score:
                best_score = score
                best_path = candidate.get("__path__")
                best_name = candidate.get("name")

        if best_score <= 0 or not best_path:
            return None, None

        return best_path, (best_name or best_path)

    def _load_geobasis_actions_config(self):
        config_path = self._find_geobasis_actions_config()
        if config_path is None:
            return None

        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            if not self._config_warning_shown:
                self._show_message(
                    "Projektstarter",
                    "GeoBasis-Config konnte nicht gelesen werden. Fallback wird verwendet.",
                    Qgis.Warning,
                )
                self._config_warning_shown = True
            return None

    def _find_geobasis_actions_config(self):
        candidate_paths = (
            self.plugin_dir / self.GEOBASIS_CONFIG_FILENAME,
            self.plugin_dir.parent / "coordinatify" / self.GEOBASIS_CONFIG_FILENAME,
        )
        for candidate in candidate_paths:
            if candidate.is_file():
                return candidate
        return None

    def _match_state_config_entry(self, states_cfg, state_names):
        wanted = set()
        for name in state_names:
            canonical = self._canonical_state_name(name)
            if canonical:
                wanted.add(canonical)
        if not wanted:
            return None

        for cfg_name, cfg_value in states_cfg.items():
            names = [cfg_name]
            if isinstance(cfg_value, dict):
                aliases = cfg_value.get("aliases")
                if isinstance(aliases, list):
                    names.extend(alias for alias in aliases if isinstance(alias, str))

            canonical_names = {
                self._canonical_state_name(candidate) for candidate in names if candidate
            }
            canonical_names.discard("")
            if canonical_names & wanted:
                return cfg_value

        return None

    def _topics_by_path(self, state_data):
        topics = state_data.get("themen")
        if not isinstance(topics, dict):
            return {}

        topic_by_path = {}
        for topic in self._collect_topic_candidates(topics):
            path = topic.get("__path__")
            if isinstance(path, str) and path:
                topic_by_path[path] = topic
        return topic_by_path

    def _collect_topic_candidates(self, topic_dict):
        candidates = []
        for topic in topic_dict.values():
            if not isinstance(topic, dict):
                continue

            if topic.get("__path__") and topic.get("name"):
                candidates.append(topic)

            layers = topic.get("layers")
            if isinstance(layers, dict):
                candidates.extend(self._collect_topic_candidates(layers))

        return candidates

    def _select_parcel_building_paths(self, action_cfg, topic_by_path, topic_kind):
        candidates = self._extract_configured_paths(action_cfg)
        prefer_types = self._extract_prefer_types(action_cfg, topic_kind)
        ordered_candidates = self._ordered_candidates_by_type(candidates, topic_by_path, prefer_types)
        if not ordered_candidates:
            return []

        flurst_path = None
        gebaeude_path = None
        for path, topic in ordered_candidates:
            has_flurst, has_gebaeude = self._topic_has_parcel_or_building(topic)
            if flurst_path is None and has_flurst and not has_gebaeude:
                flurst_path = path
            if gebaeude_path is None and has_gebaeude and not has_flurst:
                gebaeude_path = path

        for path, topic in ordered_candidates:
            has_flurst, has_gebaeude = self._topic_has_parcel_or_building(topic)
            if flurst_path is None and has_flurst:
                flurst_path = path
            if gebaeude_path is None and has_gebaeude and path != flurst_path:
                gebaeude_path = path

        selected = []
        if flurst_path:
            selected.append(flurst_path)
        if gebaeude_path and gebaeude_path != flurst_path:
            selected.append(gebaeude_path)
        return selected

    def _select_configured_path(self, action_cfg, topic_by_path, topic_kind):
        candidates = self._extract_configured_paths(action_cfg)
        prefer_types = self._extract_prefer_types(action_cfg, topic_kind)

        if prefer_types:
            selected_by_type = self._select_path_by_type(candidates, topic_by_path, prefer_types)
            if selected_by_type:
                return selected_by_type

        seen = set()
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            topic = topic_by_path.get(path)
            if topic and topic.get("__loading__", True):
                return path, topic
        return None

    def _extract_configured_paths(self, action_cfg):
        paths = []

        def _append(value):
            if isinstance(value, str) and value:
                paths.append(value)

        if isinstance(action_cfg, str):
            _append(action_cfg)
            return paths

        if isinstance(action_cfg, list):
            for entry in action_cfg:
                if isinstance(entry, str):
                    _append(entry)
                elif isinstance(entry, dict):
                    _append(entry.get("path"))
            return paths

        if isinstance(action_cfg, dict):
            options = action_cfg.get("options")
            if isinstance(options, list):
                for entry in options:
                    if isinstance(entry, str):
                        _append(entry)
                    elif isinstance(entry, dict):
                        _append(entry.get("path"))
            _append(action_cfg.get("preferred_path"))
        return paths

    def _extract_prefer_types(self, action_cfg, topic_kind):
        if isinstance(action_cfg, dict):
            prefer_types = action_cfg.get("prefer_types")
            if isinstance(prefer_types, list):
                return prefer_types

        if topic_kind == "parcel_building":
            return ["ogc_wfs", "ogc_api_features", "ogc_wms"]
        return []

    def _ordered_candidates_by_type(self, candidates, topic_by_path, prefer_types):
        prefer_rank = {}
        if isinstance(prefer_types, list):
            normalized = [str(t).lower() for t in prefer_types if isinstance(t, str) and t]
            prefer_rank = {layer_type: index for index, layer_type in enumerate(normalized)}

        ordered_paths = []
        seen_paths = set()
        for index, path in enumerate(candidates):
            if path in seen_paths:
                continue
            seen_paths.add(path)
            topic = topic_by_path.get(path)
            if not topic or not topic.get("__loading__", True):
                continue

            topic_type = str(topic.get("type", "ogc_wms")).lower()
            rank = prefer_rank.get(topic_type, len(prefer_rank))
            ordered_paths.append((rank, index, path, topic))

        ordered_paths.sort(key=lambda item: (item[0], item[1]))
        return [(path, topic) for _rank, _index, path, topic in ordered_paths]

    def _select_path_by_type(self, candidates, topic_by_path, prefer_types):
        ordered_candidates = self._ordered_candidates_by_type(candidates, topic_by_path, prefer_types)
        if not ordered_candidates:
            return None
        return ordered_candidates[0]

    def _topic_has_parcel_or_building(self, topic):
        tokens = self._topic_tokens(topic)
        has_flurst = any(
            token.startswith(prefix)
            for token in tokens
            for prefix in ("flurst", "parzell", "grundstueck", "liegenschaft")
        )
        has_gebaeude = any(
            token.startswith(prefix) for token in tokens for prefix in ("gebaeude", "building")
        )
        return has_flurst, has_gebaeude

    def _topic_tokens(self, topic):
        tokens = set(self._tokenize(topic.get("name", "")))
        path = topic.get("__path__")
        if isinstance(path, str):
            tokens.update(self._tokenize(path))

        keywords = topic.get("keywords")
        if isinstance(keywords, list):
            for keyword in keywords:
                tokens.update(self._tokenize(keyword))
        return tokens

    def _score_topic(self, topic, topic_kind):
        topic_type = str(topic.get("type", "")).lower()
        if topic_kind == "parcel_building":
            return self._score_parcel_building_topic(topic, topic_type)
        return -1

    def _score_parcel_building_topic(self, topic, topic_type):
        tokens = self._topic_tokens(topic)
        has_flurst = any(
            token.startswith(prefix)
            for token in tokens
            for prefix in ("flurst", "parzell", "grundstueck", "liegenschaft")
        )
        has_gebaeude = any(
            token.startswith(prefix) for token in tokens for prefix in ("gebaeude", "building")
        )

        if not has_flurst and not has_gebaeude:
            return -1

        score = 0
        if has_flurst and has_gebaeude:
            score += 130
        elif has_flurst:
            score += 85
        else:
            score += 40

        if isinstance(topic.get("layers"), (dict, list)):
            score += 25
        if "alkis" in tokens:
            score += 15
        if "nutzung" in tokens:
            score += 8
        if topic_type == "ogc_wfs":
            score -= 20
        if topic_type == "ogc_api_features":
            score -= 15

        return score

    def _invoke_geobasis_add_topic(self, geobasis_plugin, catalog_title, topic_path):
        try:
            try:
                geobasis_plugin.add_topic(catalog_title=catalog_title, path=topic_path)
            except TypeError:
                geobasis_plugin.add_topic(catalog_title, topic_path)
        except Exception:
            return False
        return True

    def _preferred_geobasis_crs(self, supported_auth_ids):
        if supported_auth_ids is None:
            return None

        supported = []
        for auth_id in supported_auth_ids:
            if isinstance(auth_id, str) and auth_id:
                supported.append(auth_id)

        if not supported:
            return None

        project_crs = QgsProject.instance().crs()
        project_authid = project_crs.authid() if project_crs.isValid() else ""
        if project_authid and project_authid in supported:
            return project_authid

        return supported[0]

    def _patch_geobasis_project_crs(self, geobasis_plugin):
        original_get_crs = getattr(geobasis_plugin, "get_crs", None)
        if not callable(original_get_crs):
            return None

        def use_project_crs(supported_auth_ids, layer_name):
            preferred_authid = self._preferred_geobasis_crs(supported_auth_ids)
            if preferred_authid:
                return preferred_authid
            return original_get_crs(supported_auth_ids, layer_name)

        geobasis_plugin.get_crs = use_project_crs
        return original_get_crs

    def _restore_geobasis_get_crs(self, geobasis_plugin, original_get_crs):
        if callable(original_get_crs):
            geobasis_plugin.get_crs = original_get_crs

    def _load_geobasis_topics_into_group(self, geobasis_plugin, catalog_title, topics, target_group):
        root = QgsProject.instance().layerTreeRoot()
        loaded_names = []

        for topic_path, topic_name in topics:
            before_count = len(root.children())
            if not self._invoke_geobasis_add_topic(geobasis_plugin, catalog_title, topic_path):
                continue

            self._move_new_root_nodes_to_group(root, target_group, before_count)
            loaded_names.append(topic_name or topic_path)

        return loaded_names

    def _move_new_root_nodes_to_group(self, root, target_group, before_count):
        after_nodes = list(root.children())
        delta = len(after_nodes) - int(before_count)
        if delta <= 0:
            return

        new_nodes = after_nodes[:delta]
        for node in reversed(new_nodes):
            parent = node.parent()
            if parent is None:
                continue
            target_group.insertChildNode(0, node.clone())
            parent.removeChildNode(node)

    def _canonical_state_name(self, value):
        tokens = self._tokenize(value)
        if not tokens:
            return ""

        tokens = [
            token
            for token in tokens
            if token not in {"land", "freistaat", "freie", "freier", "hansestadt", "und"}
        ] or tokens

        normalized = "".join(tokens)
        aliases = {
            "badenwurttemberg": "badenwuerttemberg",
            "thueringen": "thueringen",
            "rheinlandpfalz": "rheinlandpfalz",
            "sachsenanhalt": "sachsenanhalt",
            "schleswigholstein": "schleswigholstein",
            "nordrheinwestfalen": "nordrheinwestfalen",
            "mecklenburgvorpommern": "mecklenburgvorpommern",
        }
        return aliases.get(normalized, normalized)

    def _tokenize(self, value):
        if not isinstance(value, str):
            return []

        value = value.strip().lower()
        if not value:
            return []

        value = (
            value.replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
        )
        value = unicodedata.normalize("NFKD", value)

        words = []
        current = []
        for char in value:
            if unicodedata.category(char) == "Mn":
                continue

            if char.isalnum():
                current.append(char)
                continue

            if current:
                words.append("".join(current))
                current = []

        if current:
            words.append("".join(current))

        return words

    def _vector_export_layers(self):
        vector_layers = []
        for layer in self._managed_layers:
            if layer is None:
                continue
            if layer.type() != Qgis.LayerType.Vector:
                continue
            if not layer.isSpatial():
                continue
            vector_layers.append(layer)
        return vector_layers

    def _result_directory(self):
        if self._current_project_dir is None:
            return None
        return self._current_project_dir / "003_Ergebnis"

    def _schedule_export_sync(self):
        if self._export_sync_pending:
            return
        self._export_sync_pending = True
        QTimer.singleShot(self.EXPORT_SYNC_DELAY_MS, self._run_scheduled_export_sync)

    def _run_scheduled_export_sync(self):
        self._export_sync_pending = False
        self._export_auxiliary_formats(notify=False)

    def _export_auxiliary_formats(self, notify=False):
        result_dir = self._result_directory()
        vector_layers = self._vector_export_layers()
        if result_dir is None or not vector_layers:
            return False

        try:
            result_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self._show_message(
                "Projektstarter",
                f"Exportordner konnte nicht erstellt werden: {error}",
                Qgis.Critical,
            )
            return False

        errors = []
        try:
            self._export_dxf(vector_layers, result_dir / f"{self._current_project_dir.name}.dxf")
        except Exception as error:
            errors.append(f"DXF: {error}")

        try:
            self._export_shapefiles(vector_layers, result_dir / self.EXPORT_SHP_DIRNAME)
        except Exception as error:
            errors.append(f"SHP: {error}")

        try:
            self._export_kml(vector_layers, result_dir / self.EXPORT_KML_DIRNAME)
        except Exception as error:
            errors.append(f"KML: {error}")

        try:
            self._export_geojson(vector_layers, result_dir / self.EXPORT_GEOJSON_DIRNAME)
        except Exception as error:
            errors.append(f"GeoJSON: {error}")

        if errors:
            self._show_message(
                "Projektstarter",
                f"Export-Sync teilweise fehlgeschlagen: {errors[0]}",
                Qgis.Warning,
            )
            return False

        if notify:
            self._show_message(
                "Projektstarter",
                "Zusatzausgaben wurden aktualisiert.",
                Qgis.Info,
            )
        return True

    def _export_manifest_path(self, directory):
        return directory / self.EXPORT_MANIFEST_FILENAME

    def _export_manifest_candidates(self, directory):
        manifest_paths = [self._export_manifest_path(directory)]
        manifest_paths.extend(directory / name for name in self.LEGACY_EXPORT_MANIFEST_FILENAMES)
        return manifest_paths

    def _load_export_manifest(self, directory):
        for manifest_path in self._export_manifest_candidates(directory):
            if not manifest_path.is_file():
                continue

            try:
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue

            file_entries = manifest_data.get("files", []) if isinstance(manifest_data, dict) else []
            if not isinstance(file_entries, list):
                continue

            managed_paths = []
            for relative_path in file_entries:
                if not isinstance(relative_path, str) or not relative_path.strip():
                    continue
                candidate = directory / relative_path
                if self._path_is_within(candidate, directory):
                    managed_paths.append(candidate)
            return managed_paths

        return []

    def _delete_export_paths(self, paths):
        for path in sorted({Path(path) for path in paths}, key=lambda item: str(item).casefold(), reverse=True):
            try:
                if path.is_file():
                    path.unlink()
            except OSError:
                continue

    def _clear_managed_export_files(self, directory):
        managed_paths = self._load_export_manifest(directory)
        self._delete_export_paths(managed_paths)
        for manifest_path in self._export_manifest_candidates(directory):
            try:
                manifest_path.unlink()
            except OSError:
                pass
        directory.mkdir(parents=True, exist_ok=True)

    def _write_export_manifest(self, directory, created_paths):
        manifest_path = self._export_manifest_path(directory)
        unique_entries = []
        seen_entries = set()
        for path in created_paths:
            try:
                relative_path = Path(path).relative_to(directory)
            except ValueError:
                continue

            entry = str(relative_path)
            entry_key = entry.casefold()
            if entry_key in seen_entries:
                continue
            seen_entries.add(entry_key)
            unique_entries.append(entry)

        if not unique_entries:
            try:
                manifest_path.unlink()
            except OSError:
                pass
            return

        manifest_path.write_text(
            json.dumps({"files": sorted(unique_entries, key=str.casefold)}, indent=2),
            encoding="utf-8",
        )

    def _collect_export_bundle_paths(self, output_path):
        output_path = Path(output_path)
        if not output_path.parent.exists():
            return []

        suffix_lower = output_path.suffix.lower()
        candidate_paths = [output_path]
        if suffix_lower == ".shp":
            candidate_paths = [
                output_path.parent / f"{output_path.stem}{suffix}"
                for suffix in self.SHAPEFILE_EXPORT_SUFFIXES
            ]
        elif suffix_lower == ".geojson":
            candidate_paths.append(output_path.parent / f"{output_path.name}.qml")

        return [path for path in candidate_paths if path.is_file()]

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
        coordinate_transform=None,
        symbology_export=None,
        symbology_scale=None,
        action_on_existing=None,
        save_metadata=False,
    ):
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = driver_name
        options.fileEncoding = "UTF-8"
        options.layerName = layer_name or layer.name()
        options.onlySelectedFeatures = False
        options.saveMetadata = save_metadata

        if coordinate_transform is not None:
            options.ct = coordinate_transform
        if symbology_export is not None:
            options.symbologyExport = symbology_export
        if symbology_scale is not None:
            options.symbologyScale = float(symbology_scale)
        if action_on_existing is not None:
            options.actionOnExistingFile = action_on_existing

        error, _new_file, _new_layer, error_message = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            str(output_path),
            QgsProject.instance().transformContext(),
            options,
        )
        if int(error) != 0:
            raise RuntimeError(error_message or "Unbekannter Exportfehler.")

    def _coordinate_transform(self, layer, destination_crs):
        if not destination_crs or not destination_crs.isValid():
            return None
        if layer.crs() == destination_crs:
            return None
        return QgsCoordinateTransform(layer.crs(), destination_crs, QgsProject.instance())

    def _safe_name(self, name):
        safe_name = QgsMapLayerUtils.launderLayerName(name or "layer")
        safe_name = safe_name.replace(" ", "_")
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", safe_name)
        safe_name = safe_name.strip("._")
        return safe_name or "layer"

    def _unique_name(self, base_name, used_names):
        candidate = self._safe_name(base_name)
        derived = candidate
        suffix = 2
        while derived.lower() in used_names:
            derived = f"{candidate}_{suffix}"
            suffix += 1
        used_names.add(derived.lower())
        return derived

    def _save_qml_sidecar(self, layer, output_path):
        style_path = f"{output_path}.qml"
        layer.saveNamedStyle(style_path)

    def _export_dxf(self, layers, output_path):
        self._clear_managed_export_files(output_path.parent)
        project = QgsProject.instance()
        project_crs = project.crs()
        if not project_crs.isValid():
            project_crs = layers[0].crs()

        map_settings = QgsMapSettings()
        map_settings.setTransformContext(project.transformContext())
        map_settings.setLayers(layers)
        map_settings.setDestinationCrs(project_crs)
        map_settings.setExtent(
            QgsMapLayerUtils.combinedExtent(layers, project_crs, project.transformContext())
        )

        exporter = QgsDxfExport()
        exporter.setMapSettings(map_settings)
        exporter.setDestinationCrs(project_crs)
        exporter.setSymbologyExport(Qgis.FeatureSymbologyExport.PerSymbolLayer)
        exporter.setSymbologyScale(self._current_symbology_scale())
        exporter.addLayers([QgsDxfExport.DxfLayer(layer) for layer in layers])

        qfile = QFile(str(output_path))
        if not qfile.open(QIODevice.WriteOnly | QIODevice.Truncate):
            raise RuntimeError(f"DXF-Datei konnte nicht geschrieben werden: {qfile.errorString()}")

        dxf_encoding = QgsDxfExport.dxfEncoding("CP1252") or "CP1252"
        result = exporter.writeToFile(qfile, dxf_encoding)
        qfile.close()
        if int(result) != 0:
            raise RuntimeError(exporter.feedbackMessage() or "Unbekannter DXF-Fehler.")
        self._write_export_manifest(output_path.parent, self._collect_export_bundle_paths(output_path))

    def _export_shapefiles(self, layers, directory):
        self._clear_managed_export_files(directory)
        used_names = set()
        created_paths = []
        for layer in layers:
            output_path = directory / f"{self._unique_name(layer.name(), used_names)}.shp"
            self._write_vector_layer(
                layer,
                output_path,
                "ESRI Shapefile",
                layer_name=self._safe_name(layer.name()),
                action_on_existing=QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile,
            )
            created_paths.extend(self._collect_export_bundle_paths(output_path))
        self._write_export_manifest(directory, created_paths)

    def _export_kml(self, layers, directory):
        self._clear_managed_export_files(directory)
        used_names = set()
        destination_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        created_paths = []
        for layer in layers:
            export_layer = self._prepare_kml_layer(layer)
            output_path = directory / f"{self._unique_name(layer.name(), used_names)}.kml"
            self._write_vector_layer(
                export_layer,
                output_path,
                "KML",
                layer_name=self._safe_name(layer.name()),
                coordinate_transform=self._coordinate_transform(export_layer, destination_crs),
                symbology_export=Qgis.FeatureSymbologyExport.PerSymbolLayer,
                symbology_scale=self._current_symbology_scale(),
                action_on_existing=QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile,
            )
            created_paths.extend(self._collect_export_bundle_paths(output_path))
        self._write_export_manifest(directory, created_paths)

    def _export_geojson(self, layers, directory):
        self._clear_managed_export_files(directory)
        used_names = set()
        destination_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        created_paths = []
        for layer in layers:
            output_path = directory / f"{self._unique_name(layer.name(), used_names)}.geojson"
            self._write_vector_layer(
                layer,
                output_path,
                "GeoJSON",
                layer_name=self._safe_name(layer.name()),
                coordinate_transform=self._coordinate_transform(layer, destination_crs),
                symbology_export=Qgis.FeatureSymbologyExport.PerSymbolLayer,
                symbology_scale=self._current_symbology_scale(),
                action_on_existing=QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile,
            )
            self._save_qml_sidecar(layer, output_path)
            created_paths.extend(self._collect_export_bundle_paths(output_path))
        self._write_export_manifest(directory, created_paths)

    def _prepare_kml_layer(self, layer):
        if layer.fields().indexOf(self.KML_STYLE_FIELD) < 0:
            return layer

        export_layer = layer.clone()
        if export_layer is None:
            return layer

        renderer = self._build_categorized_renderer(export_layer, self.KML_STYLE_FIELD)
        if renderer is None:
            return layer

        export_layer.setRenderer(renderer)
        return export_layer

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
            symbol.setColor(QColor(self.CATEGORY_COLORS[index % len(self.CATEGORY_COLORS)]))
            categories.append(QgsRendererCategory(value, symbol, str(value)))

        renderer = QgsCategorizedSymbolRenderer(field_name, categories)
        renderer.sortByLabel()
        return renderer

    def _schedule_final_zoom(self, layer):
        if layer is None:
            return
        self._pending_zoom_layer_id = layer.id()
        self._pending_zoom_extent = self._layer_extent_in_project_crs(layer)
        QTimer.singleShot(self.EXPORT_ZOOM_DELAY_MS, self._apply_scheduled_zoom)

    def _apply_scheduled_zoom(self):
        if not self._pending_zoom_layer_id:
            return
        layer = QgsProject.instance().mapLayer(self._pending_zoom_layer_id)
        self._pending_zoom_layer_id = None
        zoom_done = False
        if layer is not None:
            zoom_done = self._zoom_to_layer(layer)
        if not zoom_done and self._pending_zoom_extent is not None:
            self._zoom_to_extent(self._pending_zoom_extent)
        self._pending_zoom_extent = None
        if self._current_project_dir is not None:
            self._save_project_file(self._current_project_dir, notify=False)

    def _zoom_to_layer(self, layer):
        extent = self._layer_extent_in_project_crs(layer)
        if extent is None:
            self._show_message(
                "Projektstarter",
                "Das Projektgebiet wurde geladen, hat aber keine gueltige Ausdehnung zum Zoomen.",
                Qgis.Warning,
            )
            return False

        self._zoom_to_extent(extent)
        self.iface.setActiveLayer(layer)
        return True

    def _layer_extent_in_project_crs(self, layer):
        try:
            layer.updateExtents()
        except AttributeError:
            pass

        extent = layer.extent()
        if extent.isEmpty():
            return None

        source_crs = layer.crs()
        project_crs = QgsProject.instance().crs()
        if not source_crs.isValid() or not project_crs.isValid() or source_crs == project_crs:
            return QgsRectangle(extent)

        try:
            transform = QgsCoordinateTransform(source_crs, project_crs, QgsProject.instance())
            return transform.transformBoundingBox(extent)
        except QgsCsException:
            return QgsRectangle(extent)

    def _zoom_to_extent(self, extent):
        canvas = self.iface.mapCanvas()
        canvas.setExtent(extent)
        canvas.refresh()

    def _on_managed_layer_committed(self):
        self._schedule_export_sync()

    def _on_project_read(self, *args):
        QTimer.singleShot(0, self._refresh_connection_state)

    def _on_project_saved(self):
        if self._resaving_after_georef_sync:
            self._resaving_after_georef_sync = False
            self._schedule_export_sync()
            QTimer.singleShot(0, self._refresh_connection_state)
            return

        georef_changed = self._sync_georeferenced_plans(notify=False)
        if georef_changed and self._current_project_dir is not None:
            self._resaving_after_georef_sync = True
            QTimer.singleShot(0, self._resave_after_georef_sync)
        self._schedule_export_sync()
        QTimer.singleShot(0, self._refresh_connection_state)

    def _resave_after_georef_sync(self):
        if not self._resaving_after_georef_sync:
            return
        if self._current_project_dir is None:
            self._resaving_after_georef_sync = False
            return
        if not self._save_project_file(self._current_project_dir, notify=False):
            self._resaving_after_georef_sync = False

    def _on_project_cleared(self):
        self._current_project_dir = None
        self._clear_managed_layer_connections()
        self._pending_zoom_layer_id = None
        self._pending_zoom_extent = None
        self._export_sync_pending = False
        self._resaving_after_georef_sync = False

    def _show_message(self, title, message, level):
        self.iface.messageBar().pushMessage(title, message, level=level, duration=5)
