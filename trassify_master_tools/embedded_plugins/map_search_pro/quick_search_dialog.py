import json

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
)
from qgis.PyQt.QtCore import QEvent, QLocale, QPoint, QRect, Qt, QTimer, QUrl, QUrlQuery
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


class QuickSearchDialog(QDialog):
    MAX_RESULTS = 10

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._reply = None
        self._pending_text = ""
        self._drag_active = False
        self._drag_offset = QPoint()
        self._user_moved = False
        self._base_height = 84
        self._expanded_height = 332

        self._network_manager = QNetworkAccessManager(self)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(230)
        self._search_timer.timeout.connect(self._perform_search)

        self._build_ui()
        if parent is not None:
            parent.installEventFilter(self)

    def _build_ui(self):
        self.setObjectName("MapSearchProQuickSearch")
        self.setModal(False)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumWidth(540)
        self.resize(760, self._base_height)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self.panel = QFrame(self)
        self.panel.setObjectName("quickSearchPanel")
        shadow = QGraphicsDropShadowEffect(self.panel)
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 95))
        shadow.setOffset(0, 7)
        self.panel.setGraphicsEffect(shadow)

        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(10, 10, 10, 10)
        panel_layout.setSpacing(6)

        self.search_shell = QFrame(self.panel)
        self.search_shell.setObjectName("quickSearchShell")
        self.search_shell.setFixedHeight(56)
        self.search_shell.setCursor(Qt.OpenHandCursor)
        self.search_shell.installEventFilter(self)

        shell_layout = QHBoxLayout(self.search_shell)
        shell_layout.setContentsMargins(20, 7, 20, 7)
        shell_layout.setSpacing(0)

        self.search_input = QLineEdit(self.search_shell)
        self.search_input.setObjectName("quickSearchInput")
        self.search_input.setPlaceholderText("Search places and POIs")
        self.search_input.textChanged.connect(self._schedule_search)
        self.search_input.returnPressed.connect(self._activate_current_result)
        self.search_input.installEventFilter(self)

        shell_layout.addWidget(self.search_input, 1)

        self.result_list = QListWidget(self.panel)
        self.result_list.setObjectName("quickSearchResults")
        self.result_list.setMinimumHeight(230)
        self.result_list.itemActivated.connect(self._activate_item)
        self.result_list.itemClicked.connect(self._activate_item)

        panel_layout.addWidget(self.search_shell)
        panel_layout.addWidget(self.result_list)
        root_layout.addWidget(self.panel)

        self.setStyleSheet(
            """
            QFrame#quickSearchPanel {
                background: rgba(234, 241, 248, 188);
                border: 1px solid rgba(255, 255, 255, 132);
                border-radius: 20px;
            }
            QFrame#quickSearchShell {
                background: rgba(246, 251, 255, 238);
                border: 1px solid rgba(167, 184, 202, 160);
                border-radius: 28px;
            }
            QLineEdit#quickSearchInput {
                background: transparent;
                border: none;
                color: #26313f;
                font-size: 25px;
                padding: 0px;
            }
            QLineEdit#quickSearchInput:focus {
                border: none;
            }
            QListWidget#quickSearchResults {
                background: rgba(242, 248, 255, 216);
                border: 1px solid rgba(177, 194, 213, 145);
                border-radius: 14px;
                padding: 6px;
                font-size: 13px;
            }
            QListWidget#quickSearchResults::item {
                border-radius: 8px;
                padding: 8px;
                color: #26313f;
            }
            QListWidget#quickSearchResults::item:selected {
                background: rgba(171, 216, 255, 170);
                color: #102033;
            }
            """
        )
        self._set_results_visible(False)

    def show_overlay(self):
        self._position_on_main_window(force=not self._user_moved)
        self._clamp_to_main_window()
        self.show()
        self.raise_()
        self.activateWindow()
        self.search_input.setFocus(Qt.ShortcutFocusReason)
        self.search_input.selectAll()
        if len(self.search_input.text().strip()) < 2:
            self._set_results_visible(False)

    def _position_on_main_window(self, force=False):
        if self._user_moved and not force:
            return

        main_window = self.parentWidget() or self.iface.mainWindow()
        if main_window is None:
            return

        width = max(540, min(860, main_window.width() - 120))
        height = self.height()
        origin = main_window.mapToGlobal(QPoint(0, 0))
        x_pos = origin.x() + (main_window.width() - width) // 2
        y_pos = origin.y() + 56
        self.setGeometry(x_pos, y_pos, width, height)

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() in (QEvent.Resize, QEvent.Move):
            if self.isVisible():
                if self._user_moved:
                    self._clamp_to_main_window()
                else:
                    self._position_on_main_window(force=True)
            return False

        if watched is self.search_shell:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._drag_active = True
                self._drag_offset = (
                    self._mouse_event_global_pos(event) - self.frameGeometry().topLeft()
                )
                self.search_shell.setCursor(Qt.ClosedHandCursor)
                return True
            if event.type() == QEvent.MouseMove and self._drag_active:
                new_top_left = self._mouse_event_global_pos(event) - self._drag_offset
                self.move(new_top_left)
                self._user_moved = True
                return True
            if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                self._drag_active = False
                self.search_shell.setCursor(Qt.OpenHandCursor)
                self._clamp_to_main_window()
                return True

        if watched is self.search_input and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Down and self.result_list.isVisible():
                self._move_selection(1)
                return True
            if key == Qt.Key_Up and self.result_list.isVisible():
                self._move_selection(-1)
                return True
            if key == Qt.Key_Escape:
                self.hide()
                return True

        return super().eventFilter(watched, event)

    def hideEvent(self, event):
        self._abort_pending_request()
        return super().hideEvent(event)

    def _schedule_search(self, text):
        self._pending_text = text.strip()
        if len(self._pending_text) < 2:
            self._search_timer.stop()
            self._abort_pending_request()
            self._set_results_visible(False)
            self.result_list.clear()
            return

        self._set_results_visible(True)
        self._search_timer.start()

    def _perform_search(self):
        query_text = self._pending_text
        if len(query_text) < 2:
            return

        self._abort_pending_request()
        self._set_loading_state(query_text)

        request = QNetworkRequest(self._build_search_url(query_text))
        request.setHeader(
            QNetworkRequest.UserAgentHeader, "MapSearchPro/1.0 (QGIS quick search plugin)"
        )
        request.setRawHeader(
            b"Accept-Language", self._current_language().encode("utf-8", errors="ignore")
        )

        self._reply = self._network_manager.get(request)
        self._reply.finished.connect(self._on_search_finished)

    def _build_search_url(self, query_text):
        url = QUrl("https://nominatim.openstreetmap.org/search")
        query = QUrlQuery()
        query.addQueryItem("format", "jsonv2")
        query.addQueryItem("q", query_text)
        query.addQueryItem("limit", str(self.MAX_RESULTS))
        query.addQueryItem("addressdetails", "1")
        query.addQueryItem("extratags", "1")
        query.addQueryItem("namedetails", "1")
        query.addQueryItem("polygon_geojson", "0")
        query.addQueryItem("dedupe", "1")

        viewbox = self._map_viewbox_wgs84()
        if viewbox is not None:
            west, south, east, north = viewbox
            # Nominatim expects left,top,right,bottom.
            query.addQueryItem("viewbox", f"{west},{north},{east},{south}")

        url.setQuery(query)
        return url

    def _map_viewbox_wgs84(self):
        canvas = self.iface.mapCanvas()
        canvas_extent = canvas.extent()
        map_crs = canvas.mapSettings().destinationCrs()

        try:
            transform = QgsCoordinateTransform(
                map_crs, QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance()
            )
            lower_left = transform.transform(
                QgsPointXY(canvas_extent.xMinimum(), canvas_extent.yMinimum())
            )
            upper_right = transform.transform(
                QgsPointXY(canvas_extent.xMaximum(), canvas_extent.yMaximum())
            )
        except Exception:
            return None

        west = min(lower_left.x(), upper_right.x())
        east = max(lower_left.x(), upper_right.x())
        south = min(lower_left.y(), upper_right.y())
        north = max(lower_left.y(), upper_right.y())
        return west, south, east, north

    def _on_search_finished(self):
        if self._reply is None:
            return

        reply = self._reply
        self._reply = None

        if reply.error() != QNetworkReply.NoError:
            self._show_message_item("No results found (network error).")
            reply.deleteLater()
            return

        payload = bytes(reply.readAll())
        reply.deleteLater()

        try:
            results = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._show_message_item("No results found (invalid response).")
            return

        if not isinstance(results, list) or len(results) == 0:
            self._show_message_item("No suggestions.")
            return

        self.result_list.clear()
        for entry in results:
            item = self._to_result_item(entry)
            if item is not None:
                self.result_list.addItem(item)

        if self.result_list.count() == 0:
            self._show_message_item("No suggestions.")
            return
        self.result_list.setCurrentRow(0)

    def _to_result_item(self, entry):
        lat = entry.get("lat")
        lon = entry.get("lon")
        if lat is None or lon is None:
            return None

        display_name = entry.get("display_name", "")
        title = entry.get("name")
        if not title and display_name:
            title = display_name.split(",")[0].strip()
        if not title:
            title = "Unnamed result"

        place_class = entry.get("class", "")
        place_type = entry.get("type", "")
        short_desc = self._shorten_text(display_name, 92)
        top_line = title
        bottom_line = f"{place_class}:{place_type}   {short_desc}"
        item = QListWidgetItem(f"{top_line}\n{bottom_line}")
        item.setToolTip(display_name)
        item.setData(Qt.UserRole, entry)
        return item

    def _shorten_text(self, text, max_len):
        compact = " ".join(text.split())
        if len(compact) <= max_len:
            return compact
        return compact[: max_len - 3] + "..."

    def _activate_current_result(self):
        item = self.result_list.currentItem()
        if item is None and self.result_list.count() > 0:
            item = self.result_list.item(0)
        if item is not None:
            self._activate_item(item)

    def _activate_item(self, item):
        result = item.data(Qt.UserRole)
        if not isinstance(result, dict):
            return
        self._zoom_to_result(result)
        self.hide()

    def _zoom_to_result(self, result):
        try:
            lat = float(result["lat"])
            lon = float(result["lon"])
        except (KeyError, TypeError, ValueError):
            return

        canvas = self.iface.mapCanvas()
        map_crs = canvas.mapSettings().destinationCrs()
        transform = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:4326"), map_crs, QgsProject.instance()
        )

        target_point = transform.transform(QgsPointXY(lon, lat))
        bbox = self._parse_bounding_box(result.get("boundingbox"))

        if bbox is not None:
            south, north, west, east = bbox
            try:
                sw = transform.transform(QgsPointXY(west, south))
                ne = transform.transform(QgsPointXY(east, north))
                rect = QgsRectangle(
                    min(sw.x(), ne.x()),
                    min(sw.y(), ne.y()),
                    max(sw.x(), ne.x()),
                    max(sw.y(), ne.y()),
                )
                if rect.width() > 0 and rect.height() > 0:
                    rect.scale(1.35)
                    canvas.setExtent(rect)
                    canvas.refresh()
                    return
            except Exception:
                pass

        current_extent = canvas.extent()
        span = max(current_extent.width(), current_extent.height()) * 0.12
        if span <= 0:
            span = 500
        rect = QgsRectangle(
            target_point.x() - span,
            target_point.y() - span,
            target_point.x() + span,
            target_point.y() + span,
        )
        canvas.setExtent(rect)
        canvas.refresh()

    def _parse_bounding_box(self, values):
        if not isinstance(values, list) or len(values) < 4:
            return None
        try:
            south = float(values[0])
            north = float(values[1])
            west = float(values[2])
            east = float(values[3])
        except (TypeError, ValueError):
            return None

        if south > north:
            south, north = north, south
        if west > east:
            west, east = east, west
        return south, north, west, east

    def _move_selection(self, step):
        count = self.result_list.count()
        if count <= 0:
            return

        row = self.result_list.currentRow()
        if row < 0:
            row = 0
        else:
            row = (row + step) % count

        self.result_list.setCurrentRow(row)
        item = self.result_list.currentItem()
        if item is not None:
            self.result_list.scrollToItem(item)

    def _abort_pending_request(self):
        if self._reply is not None:
            self._reply.abort()
            self._reply.deleteLater()
            self._reply = None

    def _set_loading_state(self, query_text):
        self.result_list.clear()
        loading_item = QListWidgetItem(f"Searching for '{query_text}'...")
        loading_item.setFlags(Qt.NoItemFlags)
        self.result_list.addItem(loading_item)

    def _show_message_item(self, message):
        self.result_list.clear()
        message_item = QListWidgetItem(message)
        message_item.setFlags(Qt.NoItemFlags)
        self.result_list.addItem(message_item)

    def _current_language(self):
        language = QLocale.system().name().replace("_", "-")
        if not language:
            return "en"
        return language

    def _mouse_event_global_pos(self, event):
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint()
        return event.globalPos()

    def _clamp_to_main_window(self):
        main_window = self.parentWidget() or self.iface.mainWindow()
        if main_window is None:
            return

        origin = main_window.mapToGlobal(QPoint(0, 0))
        bounds = QRect(origin, main_window.size())
        current = self.geometry()

        min_x = bounds.left() + 8
        max_x = bounds.right() - current.width() - 8
        min_y = bounds.top() + 8
        max_y = bounds.bottom() - current.height() - 8

        if max_x < min_x:
            max_x = min_x
        if max_y < min_y:
            max_y = min_y

        clamped_x = min(max(current.x(), min_x), max_x)
        clamped_y = min(max(current.y(), min_y), max_y)
        if clamped_x != current.x() or clamped_y != current.y():
            self.move(clamped_x, clamped_y)

    def _set_results_visible(self, visible):
        self.result_list.setVisible(visible)
        target_height = self._expanded_height if visible else self._base_height
        if self.height() != target_height:
            self.resize(self.width(), target_height)
            if not self._user_moved:
                self._position_on_main_window(force=True)
            self._clamp_to_main_window()
