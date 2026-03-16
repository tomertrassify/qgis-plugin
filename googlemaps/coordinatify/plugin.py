import json
import os
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
        self._connected = False
        self._web_dialogs = []

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
