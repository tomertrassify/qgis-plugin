from __future__ import annotations

import hashlib
from pathlib import Path

from qgis.PyQt.QtCore import QSettings, QTimer
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import (
    Qgis,
    QgsExpression,
    QgsFeatureRequest,
    QgsMapLayerType,
    QgsRuleBasedRenderer,
    QgsSymbol,
    QgsWkbTypes,
)


PLUGIN_DISPLAY_NAME = "Sparte Betreiber Regeln"
MENU_TITLE = "&Sparte Betreiber Regeln"
TOOLBAR_OBJECT_NAME = "SparteBetreiberRegelnToolbar"
SETTINGS_KEY_ENABLED = "SparteBetreiberRegeln/enabled"
FIELD_SPARTEN = ("sparte",)
FIELD_BETREIBER = ("betreiber",)
EMPTY_SPARTEN_LABEL = "(Ohne Sparte)"
EMPTY_BETREIBER_LABEL = "(Ohne Betreiber)"


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, int(value)))


def normalize_value(value):
    if value is None:
        return None
    if hasattr(value, "isNull") and value.isNull():
        return None

    text = str(value).strip()
    return text or None


def sort_key(value):
    if value is None:
        return (1, "")
    return (0, str(value).casefold(), str(value))


def display_value(value, empty_label):
    if value is None:
        return empty_label
    return str(value)


def stable_digest(text):
    token = str(text or "").encode("utf-8")
    return hashlib.sha1(token).digest()


class SparteBetreiberRegelnPlugin:
    SIGNAL_NAMES = (
        "attributeValueChanged",
        "featureAdded",
        "featureDeleted",
        "featuresDeleted",
        "editCommandEnded",
        "editingStopped",
        "committedAttributeValuesChanges",
        "committedFeaturesAdded",
        "committedFeaturesRemoved",
    )

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = Path(__file__).resolve().parent
        self.action = None
        self.toolbar = None
        self.enabled = False
        self.active_layer = None
        self.connected_layer_signals = []
        self.pending_layer_ids = set()

    def initGui(self):
        self.action = QAction(QIcon(str(self._icon_path())), PLUGIN_DISPLAY_NAME, self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.setStatusTip("Automatische Sparte/Betreiber-Regeln ein- oder ausschalten.")
        self.action.setToolTip("Automatische Sparte/Betreiber-Regeln")
        self.action.toggled.connect(self._on_action_toggled)

        self.toolbar = self.iface.addToolBar(PLUGIN_DISPLAY_NAME)
        self.toolbar.setObjectName(TOOLBAR_OBJECT_NAME)
        self.toolbar.addAction(self.action)
        self.iface.addPluginToMenu(MENU_TITLE, self.action)

        try:
            self.iface.currentLayerChanged.connect(self._on_current_layer_changed)
        except Exception:
            pass

        restore_enabled = self._load_enabled_state()
        self.action.blockSignals(True)
        self.action.setChecked(restore_enabled)
        self.action.blockSignals(False)
        self._set_enabled(restore_enabled, announce=False)
        self._update_action_tooltip(self.iface.activeLayer())

    def unload(self):
        self._set_enabled(False, announce=False, persist=False)

        try:
            self.iface.currentLayerChanged.disconnect(self._on_current_layer_changed)
        except Exception:
            pass

        if self.action is not None:
            try:
                self.action.toggled.disconnect(self._on_action_toggled)
            except Exception:
                pass
            try:
                self.iface.removePluginMenu(MENU_TITLE, self.action)
            except Exception:
                pass

        if self.toolbar is not None and self.action is not None:
            try:
                self.toolbar.removeAction(self.action)
            except Exception:
                pass

        if self.toolbar is not None:
            try:
                self.iface.mainWindow().removeToolBar(self.toolbar)
            except Exception:
                pass
            try:
                self.toolbar.deleteLater()
            except Exception:
                pass

        if self.action is not None:
            try:
                self.action.deleteLater()
            except Exception:
                pass

        self.toolbar = None
        self.action = None

    def _on_action_toggled(self, checked):
        self._set_enabled(bool(checked), announce=True)

    def _set_enabled(self, enabled, announce=False, persist=True):
        self.enabled = bool(enabled)
        if persist:
            self._save_enabled_state(self.enabled)

        if self.enabled:
            self._switch_active_layer(self.iface.activeLayer())
            if announce:
                if self.active_layer is None:
                    self._push_message(
                        "Toggle aktiv. Waehle einen Vektor-Layer mit den Feldern Sparte und Betreiber.",
                        level=Qgis.Info,
                    )
                else:
                    self._push_message(
                        f"Toggle aktiv fuer Layer '{self.active_layer.name()}'.",
                        level=Qgis.Success,
                    )
        else:
            self._detach_active_layer()
            if announce:
                self._push_message("Toggle deaktiviert.", level=Qgis.Info)

        self._update_action_tooltip(self.iface.activeLayer())

    def _on_current_layer_changed(self, layer):
        self._update_action_tooltip(layer)
        if not self.enabled:
            return
        self._switch_active_layer(layer)

    def _switch_active_layer(self, layer):
        if layer is self.active_layer:
            if self._is_supported_layer(layer):
                self._schedule_renderer_update(layer)
            return

        self._detach_active_layer()
        if not self._is_supported_layer(layer):
            return

        self.active_layer = layer
        self._connect_active_layer_signals(layer)
        self._schedule_renderer_update(layer)

    def _detach_active_layer(self):
        layer = self.active_layer
        if layer is not None:
            for signal_name in list(self.connected_layer_signals):
                signal = getattr(layer, signal_name, None)
                if signal is None:
                    continue
                try:
                    signal.disconnect(self._on_active_layer_data_changed)
                except Exception:
                    pass

        self.active_layer = None
        self.connected_layer_signals = []

    def _connect_active_layer_signals(self, layer):
        self.connected_layer_signals = []
        for signal_name in self.SIGNAL_NAMES:
            signal = getattr(layer, signal_name, None)
            if signal is None:
                continue
            try:
                signal.connect(self._on_active_layer_data_changed)
                self.connected_layer_signals.append(signal_name)
            except Exception:
                continue

    def _on_active_layer_data_changed(self, *args):
        if not self.enabled or self.active_layer is None:
            return
        self._schedule_renderer_update(self.active_layer)

    def _schedule_renderer_update(self, layer):
        if layer is None:
            return

        layer_id = layer.id()
        if layer_id in self.pending_layer_ids:
            return

        self.pending_layer_ids.add(layer_id)
        QTimer.singleShot(0, lambda layer_id=layer_id: self._flush_renderer_update(layer_id))

    def _flush_renderer_update(self, layer_id):
        self.pending_layer_ids.discard(layer_id)
        layer = self.active_layer
        if not self.enabled or layer is None or layer.id() != layer_id:
            return
        if not self._is_supported_layer(layer):
            self._detach_active_layer()
            self._update_action_tooltip(self.iface.activeLayer())
            return
        self._apply_renderer(layer)

    def _apply_renderer(self, layer):
        sparte_field = self._find_field_name(layer, FIELD_SPARTEN)
        betreiber_field = self._find_field_name(layer, FIELD_BETREIBER)
        if not sparte_field or not betreiber_field:
            return False

        base_symbol = QgsSymbol.defaultSymbol(layer.geometryType())
        if base_symbol is None:
            self._push_message(
                f"Layer-Typ von '{layer.name()}' wird fuer die automatische Symbolisierung nicht unterstuetzt.",
                level=Qgis.Warning,
            )
            return False

        grouped_values = self._collect_grouped_values(layer, sparte_field, betreiber_field)
        renderer = QgsRuleBasedRenderer(base_symbol)
        root_rule = renderer.rootRule()
        while root_rule.children():
            root_rule.removeChildAt(0)

        for sparte_value in sorted(grouped_values.keys(), key=sort_key):
            base_color = self._color_for_sparte(sparte_value)
            parent_symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            parent_symbol.setColor(base_color)
            parent_symbol.setOpacity(0.0)

            parent_rule = QgsRuleBasedRenderer.Rule(parent_symbol)
            parent_rule.setLabel(display_value(sparte_value, EMPTY_SPARTEN_LABEL))
            parent_rule.setFilterExpression(self._build_value_expression(sparte_field, sparte_value))

            betreiber_values = sorted(grouped_values[sparte_value], key=sort_key)
            for index, betreiber_value in enumerate(betreiber_values):
                child_symbol = QgsSymbol.defaultSymbol(layer.geometryType())
                child_symbol.setColor(
                    self._color_for_betreiber(base_color, betreiber_value, index, len(betreiber_values))
                )

                child_rule = QgsRuleBasedRenderer.Rule(child_symbol)
                child_rule.setLabel(display_value(betreiber_value, EMPTY_BETREIBER_LABEL))
                child_rule.setFilterExpression(
                    self._build_pair_expression(
                        sparte_field,
                        sparte_value,
                        betreiber_field,
                        betreiber_value,
                    )
                )
                parent_rule.appendChild(child_rule)

            root_rule.appendChild(parent_rule)

        layer.setRenderer(renderer)
        layer.triggerRepaint()
        if layer.geometryType() != QgsWkbTypes.NullGeometry:
            try:
                self.iface.layerTreeView().refreshLayerSymbology(layer.id())
            except Exception:
                pass
        return True

    def _collect_grouped_values(self, layer, sparte_field, betreiber_field):
        field_names = [field.name() for field in layer.fields()]
        indices = []
        for name in (sparte_field, betreiber_field):
            try:
                indices.append(field_names.index(name))
            except ValueError:
                continue

        request = QgsFeatureRequest()
        if indices:
            request.setSubsetOfAttributes(indices)
        try:
            request.setFlags(QgsFeatureRequest.NoGeometry)
        except Exception:
            pass

        grouped = {}
        for feature in layer.getFeatures(request):
            sparte_value = normalize_value(feature[sparte_field])
            betreiber_value = normalize_value(feature[betreiber_field])
            grouped.setdefault(sparte_value, set()).add(betreiber_value)

        return grouped

    def _build_value_expression(self, field_name, value):
        quoted_field = QgsExpression.quotedColumnRef(field_name)
        if value is None:
            return f"{quoted_field} IS NULL OR trim({quoted_field}) = ''"
        return f"{quoted_field} = {QgsExpression.quotedValue(value)}"

    def _build_pair_expression(self, sparte_field, sparte_value, betreiber_field, betreiber_value):
        return (
            f"({self._build_value_expression(sparte_field, sparte_value)}) AND "
            f"({self._build_value_expression(betreiber_field, betreiber_value)})"
        )

    def _color_for_sparte(self, sparte_value):
        token = display_value(sparte_value, EMPTY_SPARTEN_LABEL)
        digest = stable_digest(token)
        hue = int.from_bytes(digest[:2], "big") % 360
        saturation = 150 + (digest[2] % 70)
        value = 190 + (digest[3] % 45)
        return QColor.fromHsv(hue, clamp(saturation, 120, 235), clamp(value, 170, 240))

    def _color_for_betreiber(self, base_color, betreiber_value, index, total):
        if total <= 1:
            return QColor(base_color)

        token = display_value(betreiber_value, EMPTY_BETREIBER_LABEL)
        digest = stable_digest(token)
        hue = base_color.hsvHue() if base_color.hsvHue() >= 0 else 0
        saturation = clamp(base_color.hsvSaturation() - 20 + (digest[0] % 45), 110, 255)
        value = clamp(base_color.value() - 25 + (digest[1] % 60), 125, 245)

        if index % 2:
            value = clamp(value - 18, 110, 245)

        return QColor.fromHsv(hue, saturation, value)

    def _is_supported_layer(self, layer):
        if layer is None:
            return False
        if layer.type() != QgsMapLayerType.VectorLayer:
            return False
        return bool(self._find_field_name(layer, FIELD_SPARTEN) and self._find_field_name(layer, FIELD_BETREIBER))

    def _find_field_name(self, layer, aliases):
        lookup = {field.name().casefold(): field.name() for field in layer.fields()}
        for alias in aliases:
            match = lookup.get(str(alias).casefold())
            if match:
                return match
        return ""

    def _update_action_tooltip(self, layer):
        if self.action is None:
            return

        if self.enabled and self._is_supported_layer(layer):
            message = f"Aktiv fuer Layer '{layer.name()}'."
        elif self.enabled:
            message = "Aktiv. Waehle einen Layer mit Sparte und Betreiber."
        else:
            message = "Deaktiviert."

        self.action.setToolTip(f"{PLUGIN_DISPLAY_NAME}\n{message}")
        self.action.setWhatsThis(message)

    def _load_enabled_state(self):
        settings = QSettings()
        return str(settings.value(SETTINGS_KEY_ENABLED, "false")).strip().lower() in {"1", "true", "yes"}

    def _save_enabled_state(self, enabled):
        settings = QSettings()
        settings.setValue(SETTINGS_KEY_ENABLED, "true" if enabled else "false")

    def _push_message(self, text, level=Qgis.Info, duration=4):
        try:
            self.iface.messageBar().pushMessage(
                PLUGIN_DISPLAY_NAME,
                text,
                level=level,
                duration=duration,
            )
        except Exception:
            pass

    def _icon_path(self):
        return self.plugin_dir / "icon.svg"
