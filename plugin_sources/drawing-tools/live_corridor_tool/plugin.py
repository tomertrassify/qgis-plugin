# -*- coding: utf-8 -*-

import os
import sys

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject, QEvent, Qt, QSettings, QTimer
from qgis.PyQt.QtGui import QColor, QIcon, QImage, QPixmap
from qgis.PyQt.QtWidgets import (
    QAction,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QRadioButton,
    QToolBar,
    QVBoxLayout,
)
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsUnitTypes,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsRubberBand

try:
    from qgis.gui import QgsMapToolCapture
except Exception:
    QgsMapToolCapture = None


class LiveCorridorPlugin(QObject):
    """Toggle for native QGIS line digitizing with optional corridor capture.

    - User keeps using the normal QGIS "Add Line Feature" tool.
    - Toggle ON means: track the currently drawn sub-segment and show live preview.
    - Toggle OFF means: finalize corridor for that ON sub-segment only.
    - Right click / Enter while ON also finalizes the active ON sub-segment.
    """

    DEFAULT_HALF_WIDTH_METERS = 1.0
    MIN_HALF_WIDTH_METERS = 0.1
    MAX_HALF_WIDTH_METERS = 1000.0
    WHEEL_STEP_METERS = 0.1

    OUTPUT_ACTIVE_LAYER = "active_layer"
    OUTPUT_TEMP_LAYER = "temp_layer"
    TEMP_GEOM_LINE = "line"
    TEMP_GEOM_POLYGON = "polygon"

    SETTINGS_PREFIX = "live_corridor_tool"
    SETTINGS_HALF_WIDTH = "half_width_m"
    SETTINGS_BOX_ONLY_MODE = "box_only_mode"
    SETTINGS_OUTPUT_MODE = "output_mode"
    SETTINGS_TEMP_GEOM = "temp_geom"

    def __init__(self, iface):
        super().__init__()
        self.iface = iface
        self.canvas = None

        self.action = None
        self.settings_action = None
        self.toolbar = None
        self.owns_toolbar = False
        self.width_status_label = None
        self._internal_map_tool_switch = False
        self._toggle_icon_enabled = None
        self._toggle_icon_disabled = None

        # Toggle state (ON/OFF)
        self.enabled = False

        # Full line currently captured by native tool (tracked from clicks)
        self.capture_points = []

        # Sub-segment captured while toggle is ON
        self.segment_points = []
        self.segment_layer = None

        # Live preview graphics
        self.preview_line_rubber = None
        self.preview_corridor_rubber = None
        self.last_mouse_map_point = None

        # Dynamic width control (Option/Alt + MouseWheel)
        self.corridor_half_width_meters = float(self.DEFAULT_HALF_WIDTH_METERS)
        self._wheel_delta_buffer = 0

        # Output behavior
        self.box_only_mode = False
        self.output_mode = self.OUTPUT_ACTIVE_LAYER
        self.temp_geom_mode = self.TEMP_GEOM_LINE

        # Reused temporary output layers
        self.temp_box_line_layer_id = None
        self.temp_box_polygon_layer_id = None

        self._load_settings()

    def initGui(self):
        self.canvas = self.iface.mapCanvas()

        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        settings_icon_path = os.path.join(
            os.path.dirname(__file__),
            "IcBaselineSettings.svg",
        )
        self._toggle_icon_enabled = QIcon(icon_path)
        self._toggle_icon_disabled = self._build_disabled_icon(self._toggle_icon_enabled)
        self.action = QAction(
            self._toggle_icon_enabled,
            "Schutzrohr (Toggle)",
            self.iface.mainWindow(),
        )
        self.action.setObjectName("actionSchutzrohrToggle")
        self.action.setStatusTip("Schutzrohr-Toggle ein/aus")
        self.action.setWhatsThis(
            "Aktiviert/deaktiviert Schutzrohr-Abschnitte beim normalen Linienzeichnen."
        )
        self.action.setCheckable(True)
        self.action.triggered.connect(self._toggle_listener)
        try:
            self.iface.registerMainWindowAction(self.action, "")
        except Exception:
            pass

        settings_icon = QIcon(settings_icon_path)
        if settings_icon.isNull():
            settings_icon = QIcon(icon_path)

        self.settings_action = QAction(
            settings_icon,
            "Schutzrohr Einstellungen",
            self.iface.mainWindow(),
        )
        self.settings_action.setObjectName("actionSchutzrohrSettings")
        self.settings_action.setStatusTip("Schutzrohr-Einstellungen öffnen")
        self.settings_action.setWhatsThis(
            "Öffnet Einstellungen für Ausgabe, Geometrietyp und Breite."
        )
        self.settings_action.triggered.connect(self._open_settings_dialog)

        self.toolbar = self._resolve_preferred_toolbar()
        self.owns_toolbar = False
        if self.toolbar is None:
            self.toolbar = self.iface.addToolBar("Schutzrohr")
            self.toolbar.setObjectName("SchutzrohrToolbar")
            self.owns_toolbar = True

        self._insert_toggle_action(self.toolbar)
        self.toolbar.addAction(self.settings_action)
        self.iface.addPluginToMenu("&Schutzrohr", self.action)
        self.iface.addPluginToMenu("&Schutzrohr", self.settings_action)

        self._init_preview_rubbers()

        self.canvas.viewport().installEventFilter(self)
        self.canvas.installEventFilter(self)
        try:
            self.canvas.mapToolSet.connect(self._on_map_tool_set)
        except Exception:
            pass
        try:
            self.iface.currentLayerChanged.connect(self._on_current_layer_changed)
        except Exception:
            pass

        self._init_width_status_label()
        self._update_width_status_label()
        self._update_toggle_action_availability()

    def unload(self):
        toolbar = self._find_owned_toolbar() if self.owns_toolbar else self.toolbar
        action = self.action
        settings_action = self.settings_action
        width_status_label = self.width_status_label
        owns_toolbar = self.owns_toolbar

        self.toolbar = None
        self.owns_toolbar = False
        self.action = None
        self.settings_action = None
        self.width_status_label = None

        self._disable_listener(finalize_segment=False)

        if self.canvas:
            try:
                self.canvas.mapToolSet.disconnect(self._on_map_tool_set)
            except Exception:
                pass
            try:
                self.canvas.viewport().removeEventFilter(self)
                self.canvas.removeEventFilter(self)
            except Exception:
                pass

        try:
            self.iface.currentLayerChanged.disconnect(self._on_current_layer_changed)
        except Exception:
            pass

        self._reset_capture_state()

        if self._is_qt_object_alive(action):
            try:
                action.triggered.disconnect(self._toggle_listener)
            except Exception:
                pass
            try:
                self.iface.unregisterMainWindowAction(action)
            except Exception:
                pass
            self._safe_qt_call(self.iface.removePluginMenu, "&Schutzrohr", action)

        if self._is_qt_object_alive(settings_action):
            try:
                settings_action.triggered.disconnect(self._open_settings_dialog)
            except Exception:
                pass
            self._safe_qt_call(self.iface.removePluginMenu, "&Schutzrohr", settings_action)

        if self._is_qt_object_alive(toolbar):
            if self._is_qt_object_alive(action):
                try:
                    toolbar.removeAction(action)
                except Exception:
                    pass
            if self._is_qt_object_alive(settings_action):
                try:
                    toolbar.removeAction(settings_action)
                except Exception:
                    pass
            if owns_toolbar:
                self._safe_qt_call(self.iface.mainWindow().removeToolBar, toolbar)

        if self._is_qt_object_alive(width_status_label):
            try:
                self.iface.mainWindow().statusBar().removeWidget(width_status_label)
            except Exception:
                pass

        self.canvas = None

    def _resolve_preferred_toolbar(self):
        for attr_name in ("digitizeToolBar", "shapeDigitizeToolBar"):
            getter = getattr(self.iface, attr_name, None)
            if not callable(getter):
                continue
            try:
                toolbar = getter()
            except Exception:
                toolbar = None
            if toolbar:
                return toolbar
        return None

    def _find_owned_toolbar(self):
        try:
            return self.iface.mainWindow().findChild(QToolBar, "SchutzrohrToolbar")
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

    def _insert_toggle_action(self, toolbar):
        if not toolbar or not self.action:
            return

        anchor = self._vertex_anchor_action()
        if not anchor:
            toolbar.addAction(self.action)
            return

        actions = toolbar.actions()
        try:
            idx = actions.index(anchor)
        except ValueError:
            toolbar.addAction(self.action)
            return

        if idx + 1 < len(actions):
            toolbar.insertAction(actions[idx + 1], self.action)
        else:
            toolbar.addAction(self.action)

    def _vertex_anchor_action(self):
        for attr_name in ("actionVertexToolActiveLayer", "actionVertexTool"):
            getter = getattr(self.iface, attr_name, None)
            if not callable(getter):
                continue
            try:
                action = getter()
            except Exception:
                action = None
            if action:
                return action
        return None

    def eventFilter(self, obj, event):
        if not self.canvas:
            return False

        if obj == self.canvas.viewport():
            if event.type() == QEvent.MouseButtonPress:
                return self._handle_mouse_press(event)
            elif event.type() == QEvent.MouseMove:
                self._handle_mouse_move(event)
            elif event.type() == QEvent.Wheel:
                return self._handle_wheel(event)
            return False

        if (obj == self.canvas or obj == self.canvas.viewport()) and event.type() == QEvent.KeyPress:
            return self._handle_key_press(event)

        return False

    def _toggle_listener(self, enabled):
        if enabled:
            self._enable_listener()
        else:
            # Delay one event-loop tick so QGIS can finish QAction state updates
            # before we open an attribute form.
            QTimer.singleShot(0, lambda: self._disable_listener(finalize_segment=True))

    def _enable_listener(self):
        if self.enabled:
            return True

        source_layer = self._active_line_layer(require_editable=True)
        if not source_layer:
            self._reject_enable(
                "Tool kann nur mit aktivem Linienlayer im Bearbeitungsmodus verwendet werden."
            )
            return False

        if not self.box_only_mode and not self._is_add_line_map_tool_active():
            self._reject_enable(
                "Aktiviere zuerst das Werkzeug 'Linienobjekt hinzufügen'."
            )
            return False

        self.enabled = True
        self.segment_layer = source_layer

        if self.box_only_mode:
            self.capture_points = []
            self.segment_points = []
            self.last_mouse_map_point = None
            self._activate_box_only_map_tool()
        elif self.capture_points:
            # If user is already in the middle of a line capture, start corridor at last vertex.
            self.segment_points = [self.capture_points[-1]]

        mode_hint = "Nur-Box-Modus aktiv." if self.box_only_mode else "Linienmodus aktiv."
        self.iface.messageBar().pushInfo(
            "Schutzrohr",
            f"Aktiv: Korridor wird live verfolgt ({self._wheel_modifier_hint_text()} = Breite). {mode_hint}",
        )
        self._update_toggle_action_availability()
        return True

    def _disable_listener(self, finalize_segment=True):
        if not self.enabled and not self.segment_points:
            self._update_toggle_action_availability()
            return

        if finalize_segment:
            self._finalize_active_segment()

        self.enabled = False
        self.segment_points = []
        self.segment_layer = None
        self.last_mouse_map_point = None
        self._wheel_delta_buffer = 0
        self._clear_preview_graphics()
        self._update_toggle_action_availability()

    def _reject_enable(self, message):
        self.iface.messageBar().pushWarning("Schutzrohr", message)
        self._set_toggle_checked(False)
        self._update_toggle_action_availability()

    def _on_map_tool_set(self, *args):
        del args
        if self._internal_map_tool_switch:
            self._internal_map_tool_switch = False
        elif self.enabled and self.box_only_mode:
            self._disable_listener(finalize_segment=True)
            self._set_toggle_checked(False)
        self._reset_capture_state()
        self._update_toggle_action_availability()

    def _on_current_layer_changed(self, layer):
        del layer
        if self.enabled and not self._active_line_layer(require_editable=True):
            self._disable_listener(finalize_segment=False)
            self._set_toggle_checked(False)
        self._reset_capture_state()
        self._update_toggle_action_availability()

    def _handle_mouse_press(self, event):
        if not self._is_line_capture_context_active():
            return False

        if event.button() == Qt.LeftButton:
            map_point = self._canvas_pos_to_map(event.pos())
            if map_point is None:
                return False

            self._append_capture_point(map_point)
            if self.enabled:
                self._append_segment_point(map_point)
                self._refresh_preview()
                if self.box_only_mode:
                    try:
                        event.accept()
                    except Exception:
                        pass
                    return True
            return False

        if event.button() == Qt.RightButton:
            # Native tool closes current line. If toggle is ON, finalize corridor
            # for just the ON-segment and then reset capture tracking.
            QTimer.singleShot(0, self._finalize_segment_and_reset_capture)
            if self.enabled and self.box_only_mode:
                try:
                    event.accept()
                except Exception:
                    pass
                return True
        return False

    def _handle_mouse_move(self, event):
        if not self.enabled:
            return
        if not self.segment_points:
            return
        if not self._is_line_capture_context_active():
            self.last_mouse_map_point = None
            self._clear_preview_graphics()
            return

        moving_point = self._canvas_pos_to_map(event.pos())
        if moving_point is None:
            return
        self.last_mouse_map_point = moving_point
        self._refresh_preview(moving_point)

    def _handle_wheel(self, event):
        if not self.enabled:
            return False

        if not self._is_width_wheel_modifier_active(event):
            return False

        delta = 0
        try:
            delta = event.angleDelta().y()
        except Exception:
            delta = 0
        if delta == 0:
            try:
                delta = event.pixelDelta().y()
            except Exception:
                delta = 0

        if delta == 0:
            return True

        self._wheel_delta_buffer += delta
        steps = int(self._wheel_delta_buffer / 120)
        if steps == 0:
            try:
                event.accept()
            except Exception:
                pass
            return True

        self._wheel_delta_buffer -= steps * 120
        self._apply_width_steps(steps)
        try:
            event.accept()
        except Exception:
            pass
        return True

    def _activate_box_only_map_tool(self):
        pan_getter = getattr(self.iface, "actionPan", None)
        if not callable(pan_getter):
            return
        try:
            pan_action = pan_getter()
            if pan_action:
                self._internal_map_tool_switch = True
                pan_action.trigger()
        except Exception:
            pass

    def _set_toggle_checked(self, checked):
        if not self.action:
            return
        try:
            self.action.blockSignals(True)
            self.action.setChecked(bool(checked))
        except Exception:
            pass
        finally:
            try:
                self.action.blockSignals(False)
            except Exception:
                pass

    def _update_toggle_action_availability(self):
        if not self.action:
            return

        if self.enabled:
            self._set_toggle_action_enabled(True)
            self.action.setStatusTip("Schutzrohr-Toggle ein/aus")
            return

        layer_ok = self._active_line_layer(require_editable=True) is not None
        tool_ok = self.box_only_mode or self._is_add_line_map_tool_active()
        allowed = layer_ok and tool_ok
        self._set_toggle_action_enabled(allowed)

        if not layer_ok:
            self.action.setStatusTip("Aktiver Linienlayer im Bearbeitungsmodus erforderlich.")
        elif not tool_ok:
            self.action.setStatusTip("Nur im Werkzeug 'Linienobjekt hinzufügen' aktivierbar.")
        else:
            self.action.setStatusTip("Schutzrohr-Toggle ein/aus")

    def _set_toggle_action_enabled(self, enabled):
        if not self.action:
            return
        self.action.setEnabled(bool(enabled))
        if enabled or not self._toggle_icon_disabled:
            if self._toggle_icon_enabled:
                self.action.setIcon(self._toggle_icon_enabled)
            return
        self.action.setIcon(self._toggle_icon_disabled)

    def _build_disabled_icon(self, icon):
        if not icon:
            return None

        disabled_icon = QIcon()
        for size in (16, 24, 32):
            pixmap = icon.pixmap(size, size)
            if pixmap.isNull():
                continue
            image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
            for y in range(image.height()):
                for x in range(image.width()):
                    color = image.pixelColor(x, y)
                    if color.alpha() == 0:
                        continue
                    gray = int(
                        (color.red() * 0.299)
                        + (color.green() * 0.587)
                        + (color.blue() * 0.114)
                    )
                    color.setRed(gray)
                    color.setGreen(gray)
                    color.setBlue(gray)
                    color.setAlpha(int(color.alpha() * 0.65))
                    image.setPixelColor(x, y, color)
            gray_pixmap = QPixmap.fromImage(image)
            disabled_icon.addPixmap(gray_pixmap, QIcon.Normal, QIcon.Off)
            disabled_icon.addPixmap(gray_pixmap, QIcon.Disabled, QIcon.Off)

        return disabled_icon if not disabled_icon.isNull() else None

    def _is_width_wheel_modifier_active(self, event):
        modifiers = event.modifiers() if hasattr(event, "modifiers") else Qt.NoModifier
        try:
            modifiers |= QApplication.keyboardModifiers()
        except Exception:
            pass

        alt_pressed = bool(modifiers & Qt.AltModifier)
        ctrl_pressed = bool(modifiers & Qt.ControlModifier)

        # On Windows, Alt+Wheel is not reliably forwarded in all setups
        # (menu accelerator handling). Ctrl+Wheel is accepted as fallback.
        if sys.platform.startswith("win"):
            return alt_pressed or ctrl_pressed

        if sys.platform == "darwin":
            return alt_pressed

        # Linux/other: allow Alt and Ctrl for better cross-platform behavior.
        return alt_pressed or ctrl_pressed

    def _wheel_modifier_hint_text(self):
        if sys.platform == "darwin":
            return "Option/Alt + Mausrad"
        if sys.platform.startswith("win"):
            return "Alt oder Strg + Mausrad"
        return "Alt oder Strg + Mausrad"

    def _apply_width_steps(self, steps):
        if steps == 0:
            return

        new_half_width = self.corridor_half_width_meters + (
            steps * self.WHEEL_STEP_METERS
        )
        new_half_width = max(
            self.MIN_HALF_WIDTH_METERS,
            min(self.MAX_HALF_WIDTH_METERS, new_half_width),
        )
        new_half_width = round(new_half_width, 3)

        if abs(new_half_width - self.corridor_half_width_meters) < 1e-12:
            return

        self.corridor_half_width_meters = new_half_width
        self._save_settings()

        if self.segment_points:
            self._refresh_preview(self.last_mouse_map_point)

        self._show_width_feedback()

    def _show_width_feedback(self):
        msg = self._width_feedback_text()
        self._update_width_status_label()
        try:
            self.iface.mainWindow().statusBar().showMessage(msg, 1800)
        except Exception:
            pass

    def _width_feedback_text(self):
        half_width = self.corridor_half_width_meters
        total_width = half_width * 2.0
        return f"Korridor: {half_width:.2f} m je Seite (gesamt {total_width:.2f} m)"

    def _init_width_status_label(self):
        if self.width_status_label:
            return
        try:
            status_bar = self.iface.mainWindow().statusBar()
        except Exception:
            return
        if status_bar is None:
            return

        self.width_status_label = QLabel(status_bar)
        try:
            self.width_status_label.setStyleSheet("padding-left: 8px;")
        except Exception:
            pass
        status_bar.addPermanentWidget(self.width_status_label)

    def _update_width_status_label(self):
        if not self.width_status_label:
            return
        try:
            self.width_status_label.setText(self._width_feedback_text())
        except Exception:
            pass

    def _open_settings_dialog(self):
        dialog = QDialog(self.iface.mainWindow())
        dialog.setWindowTitle("Schutzrohr Einstellungen")

        root = QVBoxLayout(dialog)

        width_form = QFormLayout()
        width_spin = QDoubleSpinBox(dialog)
        width_spin.setDecimals(3)
        width_spin.setRange(self.MIN_HALF_WIDTH_METERS, self.MAX_HALF_WIDTH_METERS)
        width_spin.setSingleStep(self.WHEEL_STEP_METERS)
        width_spin.setSuffix(" m")
        width_spin.setValue(self.corridor_half_width_meters)
        width_form.addRow("Abstand je Seite:", width_spin)
        root.addLayout(width_form)

        box_only_checkbox = QCheckBox("Nur Box zeichnen (ohne Mittellinie)", dialog)
        box_only_checkbox.setChecked(self.box_only_mode)
        root.addWidget(box_only_checkbox)

        mode_group = QGroupBox("Speicherziel", dialog)
        mode_layout = QVBoxLayout(mode_group)
        active_layer_radio = QRadioButton("Im aktiven Linienlayer speichern", mode_group)
        temp_layer_radio = QRadioButton("In temporärem Layer erzeugen", mode_group)
        if self.output_mode == self.OUTPUT_TEMP_LAYER:
            temp_layer_radio.setChecked(True)
        else:
            active_layer_radio.setChecked(True)
        mode_layout.addWidget(active_layer_radio)
        mode_layout.addWidget(temp_layer_radio)

        temp_geom_form = QFormLayout()
        temp_geom_label = QLabel("Temp-Geometrietyp:")
        temp_geom_combo = QComboBox(mode_group)
        temp_geom_combo.addItem("Linienlayer (Box-Umriss)", self.TEMP_GEOM_LINE)
        temp_geom_combo.addItem("Polygonlayer (Box-Fläche)", self.TEMP_GEOM_POLYGON)
        temp_index = temp_geom_combo.findData(self.temp_geom_mode)
        if temp_index >= 0:
            temp_geom_combo.setCurrentIndex(temp_index)
        temp_geom_form.addRow(temp_geom_label, temp_geom_combo)
        mode_layout.addLayout(temp_geom_form)

        hint_label = QLabel(
            "Nur-Box-Modus blockiert während Toggle AN die native Linienerzeugung.",
            mode_group,
        )
        hint_label.setWordWrap(True)
        mode_layout.addWidget(hint_label)
        root.addWidget(mode_group)

        def _update_temp_options_enabled():
            enabled = temp_layer_radio.isChecked()
            temp_geom_label.setEnabled(enabled)
            temp_geom_combo.setEnabled(enabled)
            hint_label.setEnabled(enabled)

        temp_layer_radio.toggled.connect(_update_temp_options_enabled)
        _update_temp_options_enabled()

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal,
            dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        root.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return

        self.corridor_half_width_meters = self._clamp_half_width(width_spin.value())
        self.box_only_mode = bool(box_only_checkbox.isChecked())
        self.output_mode = (
            self.OUTPUT_TEMP_LAYER if temp_layer_radio.isChecked() else self.OUTPUT_ACTIVE_LAYER
        )
        temp_geom = temp_geom_combo.currentData()
        self.temp_geom_mode = temp_geom if temp_geom in (
            self.TEMP_GEOM_LINE,
            self.TEMP_GEOM_POLYGON,
        ) else self.TEMP_GEOM_LINE

        self._save_settings()
        self._show_width_feedback()
        self._update_toggle_action_availability()

        if self.segment_points:
            self._refresh_preview(self.last_mouse_map_point)

    def _handle_key_press(self, event):
        if not self._is_line_capture_context_active():
            return False

        key = event.key()

        if key in (Qt.Key_Return, Qt.Key_Enter):
            QTimer.singleShot(0, self._finalize_segment_and_reset_capture)
            return bool(self.enabled and self.box_only_mode)

        if key == Qt.Key_Escape:
            self._reset_capture_state()
            return bool(self.enabled and self.box_only_mode)

        if key in (Qt.Key_Backspace, Qt.Key_Delete):
            if self.capture_points:
                self.capture_points.pop()
            if self.enabled and self.segment_points:
                self.segment_points.pop()
                if self.segment_points:
                    self._refresh_preview()
                else:
                    self._clear_preview_graphics()
            return bool(self.enabled and self.box_only_mode)
        return False

    def _append_capture_point(self, point):
        if not self.capture_points:
            self.capture_points.append(point)
            return
        if not self._same_point(self.capture_points[-1], point):
            self.capture_points.append(point)

    def _append_segment_point(self, point):
        # First point while ON should anchor to previous vertex if available,
        # so the first full segment is included.
        if not self.segment_points:
            if len(self.capture_points) >= 2:
                self.segment_points = [self.capture_points[-2], self.capture_points[-1]]
            else:
                self.segment_points = [point]
            self.segment_layer = self._active_line_layer(
                require_editable=self._requires_editable_source_layer()
            )
            return

        if not self._same_point(self.segment_points[-1], point):
            self.segment_points.append(point)

    def _refresh_preview(self, moving_point=None):
        points = list(self.segment_points)
        if moving_point is not None:
            if not points or not self._same_point(points[-1], moving_point):
                points.append(moving_point)

        self.preview_line_rubber.reset(QgsWkbTypes.LineGeometry)
        if len(points) >= 2:
            line_geom = QgsGeometry.fromPolylineXY(points)
            self.preview_line_rubber.setToGeometry(line_geom, None)
            self.preview_line_rubber.show()

        self.preview_corridor_rubber.reset(QgsWkbTypes.PolygonGeometry)
        if len(points) < 2:
            return

        line_geom = QgsGeometry.fromPolylineXY(points)
        crs = self.canvas.mapSettings().destinationCrs()
        corridor_polygon = self._build_corridor_polygon(line_geom, crs)
        if corridor_polygon and not corridor_polygon.isEmpty():
            self.preview_corridor_rubber.setToGeometry(corridor_polygon, None)
            self.preview_corridor_rubber.show()

    def _finalize_segment_and_reset_capture(self):
        if self.enabled:
            self._finalize_active_segment()
        self._reset_capture_state()

    def _finalize_active_segment(self):
        if len(self.segment_points) < 2:
            self.segment_points = []
            self.segment_layer = None
            self._clear_preview_graphics()
            return

        source_line_layer = self.segment_layer
        if (
            not isinstance(source_line_layer, QgsVectorLayer)
            or not source_line_layer.isValid()
            or source_line_layer.id() not in QgsProject.instance().mapLayers()
        ):
            source_line_layer = self._active_line_layer(
                require_editable=self._requires_editable_source_layer()
            )

        if not source_line_layer:
            self.iface.messageBar().pushWarning(
                "Schutzrohr",
                "Kein aktiver Linienlayer verfügbar. Abschnitt verworfen.",
            )
            self.segment_points = []
            self.segment_layer = None
            self._clear_preview_graphics()
            return

        line_geom = QgsGeometry.fromPolylineXY(self.segment_points)
        corridor_polygon = self._build_corridor_polygon(line_geom, source_line_layer.crs())
        if not corridor_polygon or corridor_polygon.isEmpty():
            self.iface.messageBar().pushWarning(
                "Schutzrohr", "Korridor konnte für den aktiven Abschnitt nicht berechnet werden."
            )
            self.segment_points = []
            self.segment_layer = None
            self._clear_preview_graphics()
            return

        box_layer = self._resolve_box_layer(source_line_layer)
        if not box_layer:
            self.iface.messageBar().pushWarning(
                "Schutzrohr", "Ausgabelayer konnte nicht erstellt werden."
            )
            self.segment_points = []
            self.segment_layer = None
            self._clear_preview_graphics()
            return

        box_geometries = self._box_geometries_for_layer(corridor_polygon, box_layer)
        if not box_geometries:
            self.iface.messageBar().pushWarning(
                "Schutzrohr", "Box-Geometrie passt nicht zum gewählten Ausgabelayer."
            )
            self.segment_points = []
            self.segment_layer = None
            self._clear_preview_graphics()
            return

        any_saved = False
        box_features = self._build_features(box_layer, box_geometries)
        if box_features:
            if self._add_features_to_layer(box_layer, box_features):
                any_saved = True
            else:
                self.iface.messageBar().pushWarning(
                    "Schutzrohr",
                    "Box konnte nicht gespeichert werden. Prüfe den Ziellayer auf Pflichtfelder oder Constraints.",
                )
        else:
            self.iface.messageBar().pushWarning(
                "Schutzrohr", "Keine gültige Box-Geometrie zum Speichern vorhanden."
            )

        if not any_saved:
            self.iface.messageBar().pushWarning(
                "Schutzrohr", "Für diesen Abschnitt wurde nichts gespeichert."
            )

        self.segment_points = []
        self.segment_layer = None
        self._clear_preview_graphics()

    def _reset_capture_state(self):
        self.capture_points = []
        self.segment_points = []
        self.segment_layer = None
        self.last_mouse_map_point = None
        self._wheel_delta_buffer = 0
        self._clear_preview_graphics()

    def _active_line_layer(self, require_editable=False):
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer):
            return None
        if layer.geometryType() != QgsWkbTypes.LineGeometry:
            return None
        if require_editable and not layer.isEditable():
            return None
        return layer

    def _requires_editable_source_layer(self):
        return True

    def _is_line_capture_context_active(self):
        layer = self._active_line_layer(require_editable=self._requires_editable_source_layer())
        if not layer:
            return False

        if self.enabled and self.box_only_mode:
            return True

        return self._is_add_line_map_tool_active()

    def _is_add_line_map_tool_active(self):
        if not self.canvas:
            return False

        map_tool = self.canvas.mapTool()
        if map_tool is None:
            return False

        if QgsMapToolCapture and isinstance(map_tool, QgsMapToolCapture):
            try:
                return map_tool.captureMode() == QgsMapToolCapture.CaptureLine
            except Exception:
                return True

        action = map_tool.action() if hasattr(map_tool, "action") else None
        if action:
            text = action.text().lower()
            if "line" in text and ("add" in text or "hinzuf" in text):
                return True

        return False

    def _is_vertex_tool_active(self):
        if not self.canvas:
            return False

        map_tool = self.canvas.mapTool()
        if map_tool is None:
            return False

        action = map_tool.action() if hasattr(map_tool, "action") else None
        if action:
            for attr_name in ("actionVertexToolActiveLayer", "actionVertexTool"):
                getter = getattr(self.iface, attr_name, None)
                if not callable(getter):
                    continue
                try:
                    known_action = getter()
                except Exception:
                    known_action = None
                if known_action is not None and action == known_action:
                    return True

            text = action.text().lower()
            if "vertex" in text or "stütz" in text:
                return True

        return False

    def _canvas_pos_to_map(self, pos):
        try:
            match = self.canvas.snappingUtils().snapToMap(pos)
            if match.isValid():
                return match.point()
        except Exception:
            pass

        try:
            return self.canvas.getCoordinateTransform().toMapCoordinates(pos.x(), pos.y())
        except Exception:
            return None

    def _init_preview_rubbers(self):
        self.preview_line_rubber = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.preview_line_rubber.setColor(QColor(20, 105, 190, 220))
        self.preview_line_rubber.setWidth(2)

        self.preview_corridor_rubber = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
        fill = QColor(0, 0, 0, 0)
        stroke = QColor(0, 0, 0, 255)
        self.preview_corridor_rubber.setColor(fill)
        try:
            self.preview_corridor_rubber.setFillColor(fill)
        except Exception:
            pass
        try:
            self.preview_corridor_rubber.setStrokeColor(stroke)
        except Exception:
            self.preview_corridor_rubber.setColor(stroke)
        self.preview_corridor_rubber.setWidth(2)

        self._clear_preview_graphics()

    def _clear_preview_graphics(self):
        if self.preview_line_rubber:
            self.preview_line_rubber.reset(QgsWkbTypes.LineGeometry)
        if self.preview_corridor_rubber:
            self.preview_corridor_rubber.reset(QgsWkbTypes.PolygonGeometry)

    def _build_corridor_outline_lines(self, line_geom, layer_crs):
        corridor_polygon = self._build_corridor_polygon(line_geom, layer_crs)
        return self._polygon_to_outline_lines(corridor_polygon)

    def _build_corridor_polygon(self, line_geom, crs):
        if not crs or not crs.isValid():
            return None

        if crs.isGeographic():
            return self._build_geographic_corridor_polygon(line_geom, crs)

        distance = self._meters_to_layer_units(crs, self.corridor_half_width_meters)
        return self._buffer_square_ends(line_geom, distance)

    def _build_geographic_corridor_polygon(self, line_geom, source_crs):
        centroid = line_geom.centroid().asPoint()
        transform_context = QgsProject.instance().transformContext()

        to_wgs84 = QgsCoordinateTransform(
            source_crs,
            QgsCoordinateReferenceSystem("EPSG:4326"),
            transform_context,
        )

        try:
            center_ll = to_wgs84.transform(centroid)
        except Exception:
            return None

        proj4 = (
            f"+proj=aeqd +lat_0={center_ll.y()} +lon_0={center_ll.x()} "
            "+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
        )
        local_crs = QgsCoordinateReferenceSystem()
        local_crs.createFromProj4(proj4)
        if not local_crs.isValid():
            return None

        to_local = QgsCoordinateTransform(source_crs, local_crs, transform_context)
        from_local = QgsCoordinateTransform(local_crs, source_crs, transform_context)

        local_line = QgsGeometry(line_geom)
        try:
            local_line.transform(to_local)
        except Exception:
            return None

        local_polygon = self._buffer_square_ends(local_line, self.corridor_half_width_meters)
        if not local_polygon or local_polygon.isEmpty():
            return None

        try:
            local_polygon.transform(from_local)
        except Exception:
            return None

        return local_polygon

    def _polygon_to_outline_lines(self, polygon_geom):
        if not polygon_geom or polygon_geom.isEmpty():
            return []

        lines = []
        if polygon_geom.isMultipart():
            multi_polygon = polygon_geom.asMultiPolygon()
            for polygon in multi_polygon:
                if not polygon or not polygon[0]:
                    continue
                exterior_ring = polygon[0]
                if len(exterior_ring) >= 2:
                    lines.append(QgsGeometry.fromPolylineXY(exterior_ring))
            return lines

        polygon = polygon_geom.asPolygon()
        if not polygon or not polygon[0]:
            return []

        exterior_ring = polygon[0]
        if len(exterior_ring) >= 2:
            lines.append(QgsGeometry.fromPolylineXY(exterior_ring))
        return lines

    def _polygon_to_single_parts(self, polygon_geom):
        if not polygon_geom or polygon_geom.isEmpty():
            return []

        parts = []
        if polygon_geom.isMultipart():
            for polygon in polygon_geom.asMultiPolygon():
                if not polygon or not polygon[0]:
                    continue
                part_geom = QgsGeometry.fromPolygonXY(polygon)
                if part_geom and not part_geom.isEmpty():
                    parts.append(part_geom)
            return parts

        return [polygon_geom]

    def _buffer_square_ends(self, geometry, distance):
        try:
            return geometry.buffer(
                distance,
                8,
                Qgis.EndCapStyle.Flat,
                Qgis.JoinStyle.Miter,
                2.0,
            )
        except Exception:
            try:
                return geometry.buffer(distance, 8)
            except Exception:
                return None

    def _meters_to_layer_units(self, crs, meters):
        try:
            factor = QgsUnitTypes.fromUnitToUnitFactor(
                Qgis.DistanceUnit.Meters,
                crs.mapUnits(),
            )
        except Exception:
            factor = 1.0

        if factor <= 0:
            factor = 1.0
        return meters * factor

    def _default_attrs(self, layer):
        try:
            return [layer.defaultValue(i) for i in range(len(layer.fields()))]
        except Exception:
            return None

    def _resolve_box_layer(self, source_line_layer):
        if self.output_mode == self.OUTPUT_ACTIVE_LAYER:
            return source_line_layer
        return self._get_or_create_temp_box_layer(source_line_layer)

    def _box_geometries_for_layer(self, corridor_polygon, layer):
        if not layer:
            return []
        geom_type = layer.geometryType()
        if geom_type == QgsWkbTypes.LineGeometry:
            return self._polygon_to_outline_lines(corridor_polygon)
        if geom_type == QgsWkbTypes.PolygonGeometry:
            return self._polygon_to_single_parts(corridor_polygon)
        return []

    def _build_features(self, layer, geometries):
        if not layer or not geometries:
            return []

        features = []
        default_attrs = self._default_attrs(layer)
        fields = layer.fields()

        for geom in geometries:
            if not geom or geom.isEmpty():
                continue
            feature = QgsFeature(fields)
            feature.setGeometry(geom)
            if default_attrs is not None:
                feature.setAttributes(list(default_attrs))

            features.append(feature)

        return features

    def _add_features_to_layer(self, layer, features):
        if not layer or not features:
            return False

        if not layer.isEditable():
            try:
                layer.startEditing()
            except Exception:
                pass

        result = layer.addFeatures(features)
        success = result[0] if isinstance(result, tuple) else bool(result)

        if not success:
            try:
                provider = layer.dataProvider()
                provider_result = provider.addFeatures(features)
                success = (
                    provider_result[0]
                    if isinstance(provider_result, tuple)
                    else bool(provider_result)
                )
            except Exception:
                success = False

        if success:
            layer.updateExtents()
            layer.triggerRepaint()
        return success

    def _get_or_create_temp_box_layer(self, source_line_layer):
        if self.temp_geom_mode == self.TEMP_GEOM_POLYGON:
            expected_geom = QgsWkbTypes.PolygonGeometry
            layer_id = self.temp_box_polygon_layer_id
            layer_name = "Schutzrohr Box (temp Polygon)"
        else:
            expected_geom = QgsWkbTypes.LineGeometry
            layer_id = self.temp_box_line_layer_id
            layer_name = "Schutzrohr Box (temp Linie)"

        layer = self._project_layer_by_id(layer_id)
        if self._is_compatible_temp_layer(layer, expected_geom, source_line_layer):
            return layer

        created = self._create_temp_layer(source_line_layer, expected_geom, layer_name)
        if not created:
            return None

        if expected_geom == QgsWkbTypes.PolygonGeometry:
            self.temp_box_polygon_layer_id = created.id()
        else:
            self.temp_box_line_layer_id = created.id()
        return created

    @staticmethod
    def _project_layer_by_id(layer_id):
        if not layer_id:
            return None
        return QgsProject.instance().mapLayer(layer_id)

    def _is_compatible_temp_layer(self, layer, expected_geom, source_layer):
        if not isinstance(layer, QgsVectorLayer):
            return False
        if not layer.isValid():
            return False
        if layer.geometryType() != expected_geom:
            return False
        if not self._same_crs(layer, source_layer):
            return False
        if len(layer.fields()) != 0:
            return False
        self._ensure_layer_editable(layer)
        return True

    def _create_temp_layer(self, source_line_layer, geometry_type, layer_name):
        geometry_name = (
            "Polygon"
            if geometry_type == QgsWkbTypes.PolygonGeometry
            else "LineString"
        )
        crs_authid = source_line_layer.crs().authid() if source_line_layer.crs().isValid() else ""
        uri = f"{geometry_name}?crs={crs_authid}" if crs_authid else geometry_name
        layer = QgsVectorLayer(uri, layer_name, "memory")
        if not layer.isValid():
            return None

        QgsProject.instance().addMapLayer(layer)
        self._ensure_layer_editable(layer)

        self.iface.messageBar().pushInfo(
            "Schutzrohr",
            f"Temporärer Layer erstellt: {layer_name}",
        )
        return layer

    @staticmethod
    def _same_crs(a_layer, b_layer):
        try:
            a_crs = a_layer.crs()
            b_crs = b_layer.crs()
            if not a_crs.isValid() or not b_crs.isValid():
                return True
            return a_crs.authid() == b_crs.authid()
        except Exception:
            return True

    @staticmethod
    def _ensure_layer_editable(layer):
        if layer.isEditable():
            return
        try:
            layer.startEditing()
        except Exception:
            pass

    def _load_settings(self):
        settings = QSettings()
        self.corridor_half_width_meters = self._clamp_half_width(
            self._to_float(
                settings.value(
                    self._settings_key(self.SETTINGS_HALF_WIDTH),
                    self.DEFAULT_HALF_WIDTH_METERS,
                ),
                self.DEFAULT_HALF_WIDTH_METERS,
            )
        )

        legacy_centerline_value = settings.value(
            self._settings_key("include_centerline"),
            False,
        )
        self.box_only_mode = self._to_bool(
            settings.value(
                self._settings_key(self.SETTINGS_BOX_ONLY_MODE),
                legacy_centerline_value,
            ),
            default=False,
        )

        output_mode = settings.value(
            self._settings_key(self.SETTINGS_OUTPUT_MODE),
            self.OUTPUT_ACTIVE_LAYER,
        )
        self.output_mode = (
            output_mode
            if output_mode in (self.OUTPUT_ACTIVE_LAYER, self.OUTPUT_TEMP_LAYER)
            else self.OUTPUT_ACTIVE_LAYER
        )

        temp_geom = settings.value(
            self._settings_key(self.SETTINGS_TEMP_GEOM),
            self.TEMP_GEOM_LINE,
        )
        self.temp_geom_mode = (
            temp_geom
            if temp_geom in (self.TEMP_GEOM_LINE, self.TEMP_GEOM_POLYGON)
            else self.TEMP_GEOM_LINE
        )

    def _save_settings(self):
        settings = QSettings()
        settings.setValue(
            self._settings_key(self.SETTINGS_HALF_WIDTH),
            float(self.corridor_half_width_meters),
        )
        settings.setValue(
            self._settings_key(self.SETTINGS_BOX_ONLY_MODE),
            bool(self.box_only_mode),
        )
        settings.setValue(
            self._settings_key(self.SETTINGS_OUTPUT_MODE),
            self.output_mode,
        )
        settings.setValue(
            self._settings_key(self.SETTINGS_TEMP_GEOM),
            self.temp_geom_mode,
        )

    def _settings_key(self, key):
        return f"{self.SETTINGS_PREFIX}/{key}"

    def _clamp_half_width(self, value):
        try:
            numeric = float(value)
        except Exception:
            numeric = float(self.DEFAULT_HALF_WIDTH_METERS)
        numeric = max(self.MIN_HALF_WIDTH_METERS, numeric)
        numeric = min(self.MAX_HALF_WIDTH_METERS, numeric)
        return round(numeric, 3)

    @staticmethod
    def _to_float(value, default):
        try:
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _to_bool(value, default=False):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off"):
            return False
        return default

    @staticmethod
    def _same_point(a, b):
        return abs(a.x() - b.x()) < 1e-12 and abs(a.y() - b.y()) < 1e-12
