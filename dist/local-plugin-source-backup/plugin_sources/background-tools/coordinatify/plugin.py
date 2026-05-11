import json
import os
import unicodedata
from difflib import SequenceMatcher
from urllib.error import URLError
from urllib.request import Request, urlopen

from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import QAction, QApplication, QDialog, QVBoxLayout
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsLayerTreeGroup,
    QgsProject,
)

try:
    from qgis.PyQt.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebEngineView = None


class CoordinatifyPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        self.assets_dir = os.path.join(os.path.dirname(__file__), "assets")
        self.geobasis_actions_config = os.path.join(
            os.path.dirname(__file__), "geobasis_actions.conf.json"
        )
        self._connected = False
        self._web_dialogs = []
        self._config_warning_shown = False

    def initGui(self):
        if self._connected:
            return

        self.canvas.contextMenuAboutToShow.connect(self._on_context_menu_about_to_show)
        self._connected = True

    def unload(self):
        if not self._connected:
            return

        try:
            self.canvas.contextMenuAboutToShow.disconnect(self._on_context_menu_about_to_show)
        except TypeError:
            pass

        for dialog in list(self._web_dialogs):
            dialog.close()
        self._web_dialogs.clear()

        self._connected = False

    def _on_context_menu_about_to_show(self, menu, event):
        try:
            point_wgs84 = self._to_wgs84(event.mapPoint())
        except QgsCsException:
            self.iface.messageBar().pushMessage(
                "Coordinatify",
                "Koordinate konnte nicht nach WGS84 transformiert werden.",
                level=Qgis.Warning,
                duration=4,
            )
            return

        lat = point_wgs84.y()
        lon = point_wgs84.x()
        geocode_data = self._reverse_geocode(lat, lon, timeout=2.5)
        bundesland = self._extract_state(geocode_data)

        menu.addSeparator()

        action_state = QAction(f"Bundesland: {bundesland}", menu)
        action_state.setEnabled(False)
        menu.addAction(action_state)

        action_parcels = QAction("Flurstücke und Gebäude", menu)
        action_parcels.triggered.connect(
            lambda _checked=False, bundesland=bundesland: self._load_geobasis_by_state(
                bundesland, "parcel_building"
            )
        )
        menu.addAction(action_parcels)

        action_satellite = QAction("Satellitenbild", menu)
        action_satellite.triggered.connect(
            lambda _checked=False, bundesland=bundesland: self._load_geobasis_by_state(
                bundesland, "satellite"
            )
        )
        menu.addAction(action_satellite)

        action_maps = QAction("In Google Maps öffnen", menu)
        action_maps.setIcon(self._icon("icons8-google-maps-neu.svg"))
        action_maps.triggered.connect(
            lambda _checked=False, lat=lat, lon=lon: self._open_google_maps(lat, lon)
        )
        menu.addAction(action_maps)

        action_streetview = QAction("In Street View öffnen", menu)
        action_streetview.setIcon(self._icon("icons8-google-street-view.svg"))
        action_streetview.triggered.connect(
            lambda _checked=False, lat=lat, lon=lon: self._open_street_view(lat, lon)
        )
        menu.addAction(action_streetview)

        action_copy_address = QAction("Adresse kopieren", menu)
        action_copy_address.setIcon(self._icon("TablerMapPin.svg"))
        action_copy_address.triggered.connect(
            lambda _checked=False, lat=lat, lon=lon, geocode_data=geocode_data: self._copy_address(
                lat, lon, geocode_data
            )
        )
        menu.addAction(action_copy_address)

    def _icon(self, filename):
        return QIcon(os.path.join(self.assets_dir, filename))

    def _to_wgs84(self, point):
        source_crs = self.canvas.mapSettings().destinationCrs()
        if source_crs.authid() == "EPSG:4326":
            return point

        transform = QgsCoordinateTransform(source_crs, self.wgs84, QgsProject.instance())
        return transform.transform(point)

    def _open_google_maps(self, lat, lon):
        url = f"https://www.google.com/maps/search/?api=1&query={lat:.8f},{lon:.8f}"
        self._open_url(url, "Google Maps")

    def _open_street_view(self, lat, lon):
        url = (
            "https://www.google.com/maps/@?api=1"
            f"&map_action=pano&viewpoint={lat:.8f},{lon:.8f}"
        )
        self._open_url(url, "Street View")

    def _open_url(self, url, title="Web"):
        if QWebEngineView is not None:
            self._open_url_embedded(url, title)
            return

        ok = QDesktopServices.openUrl(QUrl(url))
        if not ok:
            self.iface.messageBar().pushMessage(
                "Coordinatify",
                "Link konnte nicht geöffnet werden.",
                level=Qgis.Warning,
                duration=4,
            )
            return

        self.iface.messageBar().pushMessage(
            "Coordinatify",
            "QtWebEngine nicht verfügbar. Link wurde extern im Browser geöffnet.",
            level=Qgis.Info,
            duration=4,
        )

    def _open_url_embedded(self, url, title):
        dialog = QDialog(self.iface.mainWindow())
        dialog.setWindowTitle(f"Coordinatify: {title}")
        dialog.resize(1100, 760)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)

        web_view = QWebEngineView(dialog)
        web_view.setUrl(QUrl(url))
        layout.addWidget(web_view)

        self._web_dialogs.append(dialog)
        dialog.destroyed.connect(lambda _=None, d=dialog: self._forget_web_dialog(d))

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _forget_web_dialog(self, dialog):
        try:
            self._web_dialogs.remove(dialog)
        except ValueError:
            pass

    def _copy_address(self, lat, lon, geocode_data=None):
        if geocode_data is None:
            geocode_data = self._reverse_geocode(lat, lon, timeout=8)

        address = self._format_address(geocode_data)
        if not address:
            address = f"{lat:.8f}, {lon:.8f}"
            self.iface.messageBar().pushMessage(
                "Coordinatify",
                "Adresse nicht gefunden. Koordinaten wurden kopiert.",
                level=Qgis.Warning,
                duration=4,
            )
        else:
            self.iface.messageBar().pushMessage(
                "Coordinatify",
                "Adresse wurde in die Zwischenablage kopiert.",
                level=Qgis.Success,
                duration=3,
            )

        QApplication.clipboard().setText(address)

    def _reverse_geocode(self, lat, lon, timeout=8):
        url = (
            "https://nominatim.openstreetmap.org/reverse"
            f"?format=jsonv2&lat={lat:.8f}&lon={lon:.8f}&accept-language=de"
        )
        request = Request(
            url,
            headers={
                "User-Agent": "QGIS-Coordinatify/1.3.0 (https://qgis.org)",
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8")
        except (URLError, TimeoutError):
            return None

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return None

        return data

    def _extract_state(self, geocode_data):
        if not geocode_data:
            return "nicht verfügbar"

        address = geocode_data.get("address") or {}
        state = address.get("state")
        if state:
            return state

        return "nicht verfügbar"

    def _format_address(self, geocode_data):
        if not geocode_data:
            return None

        address = geocode_data.get("address") or {}
        street = self._first_non_empty(
            address,
            ["road", "pedestrian", "footway", "residential", "path", "street"],
        )
        house_number = address.get("house_number")
        postcode = address.get("postcode")
        city = self._first_non_empty(
            address,
            ["city", "town", "village", "municipality", "hamlet"],
        )

        left = " ".join(part for part in [street, house_number] if part)
        right = " ".join(part for part in [postcode, city] if part)

        if left and right:
            return f"{left}, {right}"
        if left:
            return left
        if right:
            return right

        return geocode_data.get("display_name")

    def _first_non_empty(self, mapping, keys):
        for key in keys:
            value = mapping.get(key)
            if value:
                return value
        return None

    def _load_geobasis_by_state(self, bundesland, topic_kind):
        topic_label = self._topic_kind_label(topic_kind)
        geobasis_plugin = self._find_geobasis_plugin()
        if geobasis_plugin is None:
            self.iface.messageBar().pushMessage(
                "Coordinatify",
                "GeoBasis_Loader ist nicht aktiv.",
                level=Qgis.Warning,
                duration=4,
            )
            return

        services = getattr(geobasis_plugin, "services", None)
        if not services:
            self.iface.messageBar().pushMessage(
                "Coordinatify",
                "GeoBasis_Loader ist noch nicht geladen.",
                level=Qgis.Warning,
                duration=4,
            )
            return

        state_match = self._match_geobasis_state(services, bundesland)
        if state_match is None:
            self.iface.messageBar().pushMessage(
                "Coordinatify",
                f"Bundesland '{bundesland}' wurde im GeoBasis-Katalog nicht gefunden.",
                level=Qgis.Warning,
                duration=5,
            )
            return

        _state_key, state_data, state_name = state_match

        catalog_title = self._current_geobasis_catalog_title(geobasis_plugin)
        if not catalog_title:
            self.iface.messageBar().pushMessage(
                "Coordinatify",
                "Aktueller GeoBasis-Katalog konnte nicht ermittelt werden.",
                level=Qgis.Warning,
                duration=4,
            )
            return

        configured_topics = self._find_configured_topics_for_state(
            state_data=state_data,
            state_name=state_name,
            raw_state_name=bundesland,
            topic_kind=topic_kind,
            catalog_title=catalog_title,
        )

        if not configured_topics:
            topic_path, topic_name = self._find_best_topic_for_state(state_data, topic_kind)
            if topic_path:
                configured_topics = [(topic_path, topic_name or topic_path)]

        if not configured_topics:
            self.iface.messageBar().pushMessage(
                "Coordinatify",
                f"Kein passendes Thema '{topic_label}' in {state_name} gefunden.",
                level=Qgis.Warning,
                duration=5,
            )
            return

        if topic_kind == "parcel_building" and len(configured_topics) > 1:
            loaded_names = self._load_geobasis_topics_grouped(
                geobasis_plugin=geobasis_plugin,
                catalog_title=catalog_title,
                topics=configured_topics,
                group_name="ALKIS (Gebäude & Flurstücke)",
            )
        else:
            loaded_names = []
            first_path, first_name = configured_topics[0]
            if self._invoke_geobasis_add_topic(geobasis_plugin, catalog_title, first_path):
                loaded_names.append(first_name or first_path)

        if not loaded_names:
            self.iface.messageBar().pushMessage(
                "Coordinatify",
                f"GeoBasis konnte '{topic_label}' nicht laden.",
                level=Qgis.Warning,
                duration=5,
            )
            return

        if topic_kind == "parcel_building" and len(loaded_names) > 1:
            loaded_label = "ALKIS (Gebäude & Flurstücke)"
        else:
            loaded_label = loaded_names[0]

        self.iface.messageBar().pushMessage(
            "Coordinatify",
            f"GeoBasis lädt: {loaded_label}",
            level=Qgis.Info,
            duration=3,
        )

    def _topic_kind_label(self, topic_kind):
        if topic_kind == "parcel_building":
            return "Flurstücke und Gebäude"
        return "Satellitenbild"

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

    def _topic_has_parcel_or_building(self, topic):
        tokens = self._topic_tokens(topic)
        has_flurst = any(
            token.startswith(prefix)
            for token in tokens
            for prefix in ("flurst", "parzell", "grundstueck", "liegenschaft")
        )
        has_gebaeude = any(token.startswith(prefix) for token in tokens for prefix in ("gebaeude", "building"))
        return has_flurst, has_gebaeude

    def _load_geobasis_actions_config(self):
        if not os.path.exists(self.geobasis_actions_config):
            return None

        try:
            with open(self.geobasis_actions_config, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            if not self._config_warning_shown:
                self.iface.messageBar().pushMessage(
                    "Coordinatify",
                    "GeoBasis-Config konnte nicht gelesen werden. Fallback wird verwendet.",
                    level=Qgis.Warning,
                    duration=5,
                )
                self._config_warning_shown = True
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

    def _extract_prefer_types(self, action_cfg, topic_kind):
        if isinstance(action_cfg, dict):
            prefer_types = action_cfg.get("prefer_types")
            if isinstance(prefer_types, list):
                return prefer_types

        if topic_kind == "parcel_building":
            return ["ogc_wfs", "ogc_api_features", "ogc_wms"]

        return []

    def _invoke_geobasis_add_topic(self, geobasis_plugin, catalog_title, topic_path):
        try:
            try:
                geobasis_plugin.add_topic(catalog_title=catalog_title, path=topic_path)
            except TypeError:
                geobasis_plugin.add_topic(catalog_title, topic_path)
        except Exception:
            return False
        return True

    def _load_geobasis_topics_grouped(self, geobasis_plugin, catalog_title, topics, group_name):
        root = QgsProject.instance().layerTreeRoot()
        group = self._get_or_create_top_group(root, group_name)
        loaded_names = []

        original_get_crs = getattr(geobasis_plugin, "get_crs", None)
        shared_crs = {"asked": False, "value": None}

        if callable(original_get_crs):
            def get_crs_once(supported_auth_ids, layer_name):
                if shared_crs["asked"]:
                    return shared_crs["value"]
                crs = original_get_crs(supported_auth_ids, layer_name)
                shared_crs["asked"] = True
                shared_crs["value"] = crs
                return crs

            geobasis_plugin.get_crs = get_crs_once

        try:
            for topic_path, topic_name in topics:
                before_count = len(root.children())
                if not self._invoke_geobasis_add_topic(geobasis_plugin, catalog_title, topic_path):
                    continue

                self._move_new_root_nodes_to_group(root, group, before_count)
                loaded_names.append(topic_name or topic_path)
        finally:
            if callable(original_get_crs):
                geobasis_plugin.get_crs = original_get_crs

        return loaded_names

    def _get_or_create_top_group(self, root, group_name):
        for node in root.children():
            if isinstance(node, QgsLayerTreeGroup) and node.name() == group_name:
                return node
        return root.insertGroup(0, group_name)

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

    def _score_topic(self, topic, topic_kind):
        topic_type = str(topic.get("type", "")).lower()
        if topic_kind == "parcel_building":
            return self._score_parcel_building_topic(topic, topic_type)
        return self._score_satellite_topic(topic, topic_type)

    def _score_parcel_building_topic(self, topic, topic_type):
        tokens = self._topic_tokens(topic)

        has_flurst = any(
            token.startswith(prefix)
            for token in tokens
            for prefix in ("flurst", "parzell", "grundstueck", "liegenschaft")
        )
        has_gebaeude = any(token.startswith(prefix) for token in tokens for prefix in ("gebaeude", "building"))

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

    def _score_satellite_topic(self, topic, topic_type):
        if topic_type in {"ogc_wfs", "ogc_api_features"}:
            return -1

        tokens = self._topic_tokens(topic)
        if any(token in tokens for token in ("dom", "dgm", "oberflaechenmodell", "hoehenmodell")):
            return -1

        score = 0
        if any(token.startswith("satellit") or token == "satellite" for token in tokens):
            score += 140
        if any(token.startswith("orthophoto") or token.startswith("orthofoto") for token in tokens):
            score += 115
        if any(token.startswith("dop") for token in tokens):
            score += 105
        if "luftbild" in tokens or "truedop" in tokens or "trueortho" in tokens:
            score += 95
        if "rgb" in tokens or "farbe" in tokens or "farbig" in tokens:
            score += 8
        if "grau" in tokens or "graustufen" in tokens:
            score -= 4
        if "cir" in tokens or "infrarot" in tokens:
            score -= 3

        if score <= 0:
            return -1

        return score

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
