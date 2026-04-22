from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMenuBar,
    QPushButton,
    QSizePolicy,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from qgis.core import Qgis, QgsMapLayerType, QgsProject
from qgis.gui import QgsLayerTreeViewIndicator

from .attribution_plugin import (
    BOOTSTRAP_CODE_MARKERS,
    DEFAULT_CONFIG,
    INIT_FUNCTION_NAME,
    LayerConfigDialog,
    _apply_configuration_to_layer,
    _apply_configuration_to_layers,
    _can_sync_existing_layer_data,
    _effective_layer_config,
    _first_field_match,
    _sync_layer_operator_fields,
)
from .project_profile import current_profile_path_string
from .projectstarter_plugin import ProjectStarterPlugin
from .ui_helpers import ButlerMessageBox as QMessageBox, push_butler_message


class ProjectStarterButlerDialog(QDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent or plugin.iface.mainWindow())
        self.plugin = plugin
        self.layer_config_dialog = None
        self.current_layer = None
        self.placeholder_widget = None
        self._current_layer_signal_connected = False

        self.setWindowTitle("Projektstarter Butler")
        self.setWindowIcon(QIcon(str(plugin._icon_path(plugin._has_active_connection()))))
        self.resize(1320, 860)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        self.command_bar = QMenuBar(self)
        self.command_bar.setNativeMenuBar(False)

        self.project_menu = self.command_bar.addMenu("Projekt")
        self.choose_project_action = self.project_menu.addAction("Projektordner auswählen")
        self.choose_project_action.triggered.connect(self._choose_project)
        self.project_menu.addSeparator()
        self.disconnect_action = self.project_menu.addAction("Verbindung trennen")
        self.disconnect_action.triggered.connect(self._disconnect_project)

        self.add_menu = self.command_bar.addMenu("Hinzufügen")
        self.add_template_action = self.add_menu.addAction("Template hinzufügen")
        self.add_template_action.triggered.connect(self._add_template)
        self.create_object_action = self.add_menu.addAction("Objekt erstellen")
        self.create_object_action.triggered.connect(self._create_object)
        self.add_menu.addSeparator()
        self.add_operator_action = self.add_menu.addAction("Neuen Betreiber zur Betreiberliste hinzufügen")
        self.add_operator_action.triggered.connect(self._add_operator_to_list)

        self.update_menu = self.command_bar.addMenu("Aktualisieren")
        self.sync_plans_action = self.update_menu.addAction("Leitungsauskunft aktualisieren")
        self.sync_plans_action.triggered.connect(self._sync_plans)
        self.reload_local_folders_action = self.update_menu.addAction("Lokale Ordner neu laden")
        self.reload_local_folders_action.triggered.connect(self._reload_local_folders)
        self.reload_operator_list_action = self.update_menu.addAction("Betreiberliste neu laden")
        self.reload_operator_list_action.triggered.connect(self._reload_operator_list)
        self.refresh_attributes_action = self.update_menu.addAction("Attribute aktualisieren")
        self.refresh_attributes_action.triggered.connect(self._refresh_operator_attributes)

        self.settings_menu = self.command_bar.addMenu("Einstellungen")
        self.show_operator_list_action = self.settings_menu.addAction("Betreiberliste")
        self.show_operator_list_action.triggered.connect(self._show_operator_list)
        self.show_local_assignments_action = self.settings_menu.addAction("Lokale Ordner")
        self.show_local_assignments_action.triggered.connect(self._show_local_assignments)
        self.settings_menu.addSeparator()
        self.show_data_sources_action = self.settings_menu.addAction("Datenquellen")
        self.show_data_sources_action.triggered.connect(self._show_data_sources)
        self.show_configuration_action = self.settings_menu.addAction("Konfiguration")
        self.show_configuration_action.triggered.connect(self._show_configuration)

        root_layout.addWidget(self.command_bar)

        self.layer_host = QWidget(self)
        self.layer_host_layout = QVBoxLayout(self.layer_host)
        self.layer_host_layout.setContentsMargins(0, 0, 0, 0)
        self.layer_host_layout.setSpacing(0)
        root_layout.addWidget(self.layer_host, 1)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close, self)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        root_layout.addWidget(self.button_box)

        try:
            self.plugin.iface.currentLayerChanged.connect(self._on_current_layer_changed)
            self._current_layer_signal_connected = True
        except Exception:
            self._current_layer_signal_connected = False

        self.refresh_state(rebuild_layer=True)

    def _active_vector_layer(self):
        layer = self.plugin.iface.activeLayer()
        if layer is None or layer.type() != QgsMapLayerType.VectorLayer:
            return None
        return layer

    def _panel_layer(self):
        layer = self._active_vector_layer()
        default_layer = self.plugin._default_butler_layer()
        project_area_layer = self.plugin._project_area_layer()
        if layer is not None:
            if (
                default_layer is not None
                and project_area_layer is not None
                and layer.id() == project_area_layer.id()
            ):
                return default_layer
            return layer
        return default_layer

    def _clear_layer_host(self):
        if self.layer_config_dialog is not None:
            self.layer_host_layout.removeWidget(self.layer_config_dialog)
            self.layer_config_dialog.deleteLater()
            self.layer_config_dialog = None
        if self.placeholder_widget is not None:
            self.layer_host_layout.removeWidget(self.placeholder_widget)
            self.placeholder_widget.deleteLater()
            self.placeholder_widget = None

    def _build_placeholder_card(self, title, description, button_text=None, button_slot=None):
        host = QWidget(self.layer_host)
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.addStretch(1)

        card = QWidget(host)
        card.setObjectName("psbPlaceholderCard")
        card.setMaximumWidth(660)
        card.setStyleSheet(
            "QWidget#psbPlaceholderCard {"
            "background: #f7f3ea;"
            "border: 1px solid #d7cfbf;"
            "border-radius: 22px;"
            "}"
        )

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(40, 36, 40, 36)
        card_layout.setSpacing(14)

        title_label = QLabel(title, card)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 26px; font-weight: 700; color: #2f281f;")
        card_layout.addWidget(title_label)

        description_label = QLabel(description, card)
        description_label.setWordWrap(True)
        description_label.setAlignment(Qt.AlignCenter)
        description_label.setStyleSheet("font-size: 14px; color: #5b5345;")
        card_layout.addWidget(description_label)

        if button_text and button_slot is not None:
            action_button = QPushButton(button_text, card)
            action_button.clicked.connect(button_slot)
            action_button.setMinimumHeight(42)
            action_button.setMinimumWidth(240)
            action_button.setStyleSheet("padding: 8px 18px; font-weight: 600;")
            button_row = QHBoxLayout()
            button_row.setContentsMargins(0, 8, 0, 0)
            button_row.addStretch(1)
            button_row.addWidget(action_button)
            button_row.addStretch(1)
            card_layout.addLayout(button_row)

        card_row = QHBoxLayout()
        card_row.setContentsMargins(0, 0, 0, 0)
        card_row.addStretch(1)
        card_row.addWidget(card)
        card_row.addStretch(1)
        host_layout.addLayout(card_row)
        host_layout.addStretch(1)
        return host

    def closeEvent(self, event):
        if self._current_layer_signal_connected:
            try:
                self.plugin.iface.currentLayerChanged.disconnect(self._on_current_layer_changed)
            except Exception:
                pass
            self._current_layer_signal_connected = False
        super().closeEvent(event)

    def _on_current_layer_changed(self, layer):
        del layer
        self.refresh_state(rebuild_layer=True)

    def _rebuild_layer_panel(self, layer):
        self._clear_layer_host()
        self.current_layer = layer

        if self.plugin._current_project_dir is None:
            self.placeholder_widget = self._build_placeholder_card(
                "Step 1: Projekt auswählen",
                (
                    "Wähle zuerst den Projektordner aus. Danach verbindet der Projektstarter Butler "
                    "das Projekt und lädt die Betreiber- und Layer-Konfiguration direkt im Dialog."
                ),
                button_text="Projektordner auswählen",
                button_slot=self._choose_project,
            )
            self.layer_host_layout.addWidget(self.placeholder_widget, 1)
            return

        if layer is None:
            self.placeholder_widget = self._build_placeholder_card(
                "Aktiven Layer auswählen",
                (
                    "Aktiviere in QGIS einen Vektor-Layer. Falls die Projektlayer noch nicht geladen sind, "
                    "füge sie zuerst über 'Template hinzufügen' hinzu."
                ),
            )
            self.layer_host_layout.addWidget(self.placeholder_widget, 1)
            return

        dialog = LayerConfigDialog(layer, self)
        dialog.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        dialog.set_values(_effective_layer_config(layer))
        dialog.set_project_context_info(self._project_context_info(layer))
        dialog.set_embedded_navigation_visible(False)
        dialog.set_embedded_toolbar_actions_visible(False)
        if getattr(dialog, "button_box", None) is not None:
            dialog.button_box.hide()
        self.layer_config_dialog = dialog
        self.layer_host_layout.addWidget(dialog)

    def _project_context_info(self, panel_layer):
        project_dir = self.plugin._current_project_dir
        connected = self.plugin._has_active_connection()
        profile_path = current_profile_path_string().strip() or "Wird im QGIS-Projekt gespeichert."
        layer_name = panel_layer.name() if panel_layer is not None else "-"
        return {
            "status": "Verbunden" if connected else "Nicht verbunden",
            "project_dir": str(project_dir) if project_dir is not None else "-",
            "profile_path": profile_path,
            "layer_name": layer_name,
            "note": (
                "Das Projektprofil speichert Betreiberliste, Datenquellen und Feldzuordnung projektweit. "
                "Das Nextcloud-App-Passwort bleibt aus Sicherheitsgruenden lokal auf dem jeweiligen Rechner."
            ),
        }

    def refresh_state(self, rebuild_layer=False):
        project_dir = self.plugin._current_project_dir
        panel_layer = self._panel_layer()

        if rebuild_layer or panel_layer is not self.current_layer:
            self._rebuild_layer_panel(panel_layer)
        elif self.layer_config_dialog is not None:
            self.layer_config_dialog.set_project_context_info(self._project_context_info(panel_layer))

        has_project = project_dir is not None
        has_settings_panel = self.layer_config_dialog is not None

        self.choose_project_action.setText(
            "Projektordner wechseln" if has_project else "Projektordner auswählen"
        )
        self.sync_plans_action.setEnabled(has_project)
        self.disconnect_action.setEnabled(has_project)
        self.add_menu.menuAction().setEnabled(has_project)
        self.add_template_action.setEnabled(has_project)
        self.create_object_action.setEnabled(has_project)
        self.add_operator_action.setEnabled(has_settings_panel)
        self.update_menu.menuAction().setEnabled(has_project or has_settings_panel)
        self.settings_menu.menuAction().setEnabled(has_settings_panel)
        self.show_operator_list_action.setEnabled(has_settings_panel)
        self.show_local_assignments_action.setEnabled(has_settings_panel)
        self.show_data_sources_action.setEnabled(has_settings_panel)
        self.show_configuration_action.setEnabled(has_settings_panel)
        self.reload_local_folders_action.setEnabled(has_settings_panel)
        self.reload_operator_list_action.setEnabled(has_settings_panel)
        self.refresh_attributes_action.setEnabled(has_settings_panel)

        save_button = self.button_box.button(QDialogButtonBox.Save)
        if save_button is not None:
            save_button.setVisible(self.layer_config_dialog is not None)

    def _choose_project(self):
        self.plugin._select_and_connect_project()
        self.refresh_state(rebuild_layer=True)

    def _sync_plans(self):
        self.plugin._refresh_leitungsauskunft()
        self.refresh_state(rebuild_layer=False)

    def _add_template(self):
        self.plugin.add_template_layers(notify=True)
        self.refresh_state(rebuild_layer=True)

    def _create_object(self):
        self.plugin.create_manual_project_layer(notify=True)
        self.refresh_state(rebuild_layer=True)

    def _disconnect_project(self):
        self.plugin._disconnect_current_connection()
        self.refresh_state(rebuild_layer=True)

    def _reload_local_folders(self):
        if self.layer_config_dialog is None:
            return
        self.layer_config_dialog.reload_local_operators()

    def _reload_operator_list(self):
        if self.layer_config_dialog is None:
            return
        self.layer_config_dialog.reload_external_operators()

    def _refresh_operator_attributes(self):
        if self.layer_config_dialog is None:
            return

        self.layer_config_dialog._store_current_local_operator_overlays_from_table()
        if not self.layer_config_dialog._save_external_operator_changes(show_feedback=False):
            return

        config = self.layer_config_dialog.values()
        merged_operator_entries = self.layer_config_dialog.merged_operator_entries()
        layers = self.layer_config_dialog.selected_target_layers()
        if not layers:
            QMessageBox.warning(
                self,
                "Projektstarter Butler",
                "Bitte zuerst einen Vektor-Layer auswaehlen.",
            )
            return

        sync_layers = []
        skipped_layers = []
        seen_layer_ids = set()
        for layer in layers:
            if layer is None or layer.id() in seen_layer_ids:
                continue
            seen_layer_ids.add(layer.id())
            if _can_sync_existing_layer_data(layer, config):
                sync_layers.append(layer)
            else:
                skipped_layers.append(layer.name())

        if not sync_layers:
            QMessageBox.information(
                self,
                "Projektstarter Butler",
                "In den ausgewaehlten Layern ist keine gueltige Betreiber-Synchronisierung konfiguriert.",
            )
            return

        updated_rows = 0
        updated_values = 0
        pending_edits = False
        failures = []

        for layer in sync_layers:
            try:
                sync_result = _sync_layer_operator_fields(
                    layer,
                    config,
                    operator_entries=merged_operator_entries,
                )
            except Exception as exc:
                failures.append(f"{layer.name()}: {exc}")
                continue

            updated_rows += int(sync_result.get("updated_rows", 0) or 0)
            updated_values += int(sync_result.get("updated_values", 0) or 0)
            pending_edits = pending_edits or bool(sync_result.get("pending_edits", False))

        if updated_values > 0:
            suffix = " (Aenderungen sind noch nicht gespeichert.)" if pending_edits else ""
            push_butler_message(
                self.plugin.iface.messageBar(),
                "Projektstarter Butler",
                f"Attribute aktualisiert: {updated_rows} Datensaetze, {updated_values} Feldwerte{suffix}",
                level=Qgis.Success,
                duration=6,
                parent=self,
            )
        else:
            push_butler_message(
                self.plugin.iface.messageBar(),
                "Projektstarter Butler",
                "Keine Aenderungen noetig: Betreiberdaten sind bereits aktuell.",
                level=Qgis.Info,
                duration=5,
                parent=self,
            )

        details = []
        if skipped_layers:
            details.append(
                "Diese Layer wurden uebersprungen, weil keine passende Betreiber-Feldzuordnung aktiv ist:\n- "
                + "\n- ".join(skipped_layers)
            )
        if failures:
            details.append(
                "Die Aktualisierung ist fuer einzelne Layer fehlgeschlagen:\n- "
                + "\n- ".join(failures)
            )
        if details:
            QMessageBox.warning(
                self,
                "Projektstarter Butler",
                "\n\n".join(details),
            )

    def _add_operator_to_list(self):
        if self.layer_config_dialog is None:
            return
        self.layer_config_dialog.add_external_operator()

    def _show_operator_list(self):
        if self.layer_config_dialog is None:
            return
        self.layer_config_dialog.show_external_operators_tab()

    def _show_local_assignments(self):
        if self.layer_config_dialog is None:
            return
        self.layer_config_dialog.show_local_operators_tab()

    def _show_data_sources(self):
        if self.layer_config_dialog is None:
            return
        self.layer_config_dialog.show_data_sources_tab()

    def _show_configuration(self):
        if self.layer_config_dialog is None:
            return
        self.layer_config_dialog.show_configuration_tab()

    def accept(self):
        if self.layer_config_dialog is None or self.current_layer is None:
            super().accept()
            return

        self.layer_config_dialog._store_current_local_operator_overlays_from_table()
        if not self.layer_config_dialog._save_external_operator_changes(show_feedback=False):
            return

        if not _apply_configuration_to_layers(
            self.plugin.iface,
            self.layer_config_dialog.values(),
            primary_layer=self.current_layer,
            target_layers=self.layer_config_dialog.selected_target_layers(),
            merged_operator_entries=self.layer_config_dialog.merged_operator_entries(),
            parent=self,
        ):
            return

        if self.plugin._current_project_dir is not None:
            self.plugin._save_project_file(self.plugin._current_project_dir, notify=False)
        elif str(QgsProject.instance().fileName() or "").strip():
            QgsProject.instance().write()

        QMessageBox.information(
            self,
            "Projektstarter Butler",
            "Layer-Konfiguration und Butler-Profil wurden gespeichert.",
        )
        super().accept()


class ProjectStarterAttributionButlerPlugin(ProjectStarterPlugin):
    TOOLBAR_NAME = "Projektstarter Butler"
    TOOLBAR_OBJECT_NAME = "ProjektstarterButlerToolbar"
    DEFAULT_ICON_FILENAME = "projektstarter-butler.svg"
    CONNECTED_ICON_FILENAME = "projektstarter-butler-connected.svg"
    DEFAULT_BUTLER_LAYER_NAME = "Fremdleitungen"
    LAYER_TREE_TOOLTIP = "Mit Projektstarter Butler verbunden"

    def __init__(self, iface):
        super().__init__(iface)
        self.action_unbind_hidden = None
        self._layer_tree_indicators = {}
        self._original_layer_mark_width = None

    def initGui(self):
        self.action = QAction(QIcon(str(self._icon_path())), "Projektstarter Butler", self.iface.mainWindow())
        self.action.setToolTip("Projektstarter Butler")
        self.action.triggered.connect(self.run)

        self.toolbar = self.iface.addToolBar(self.TOOLBAR_NAME)
        self.toolbar.setObjectName(self.TOOLBAR_OBJECT_NAME)
        self.toolbar.setToolTip(self.TOOLBAR_NAME)
        self.toolbar.setWindowIcon(QIcon(str(self._icon_path())))
        self.toolbar.addAction(self.action)

        self.iface.addPluginToMenu(self.TOOLBAR_NAME, self.action)

        self.action_unbind_hidden = QAction(self.iface.mainWindow())
        self.action_unbind_hidden.setShortcut("Ctrl+Alt+Shift+U")
        self.action_unbind_hidden.setShortcutContext(Qt.ApplicationShortcut)
        self.action_unbind_hidden.triggered.connect(self.unbind_active_layer)
        self.action_unbind_hidden.setVisible(False)
        self.iface.mainWindow().addAction(self.action_unbind_hidden)

        self._connect_project_signals()
        QTimer.singleShot(0, self._refresh_connection_state)

    def unload(self):
        self._clear_bound_layer_indicators()
        self._restore_bound_layer_indicator_space()

        action_unbind_hidden = self.action_unbind_hidden
        self.action_unbind_hidden = None

        if self._is_qt_object_alive(action_unbind_hidden):
            self._safe_qt_call(self.iface.mainWindow().removeAction, action_unbind_hidden)
            self._safe_qt_call(action_unbind_hidden.deleteLater)

        super().unload()

    def _find_toolbar(self):
        try:
            return self.iface.mainWindow().findChild(QToolBar, self.TOOLBAR_OBJECT_NAME)
        except Exception:
            return self.toolbar

    def _connect_project_signals(self):
        super()._connect_project_signals()
        project = QgsProject.instance()
        project.layersAdded.connect(self._on_project_layers_changed)
        project.layersRemoved.connect(self._on_project_layers_changed)

    def _disconnect_project_signals(self):
        project = QgsProject.instance()
        try:
            project.layersAdded.disconnect(self._on_project_layers_changed)
        except TypeError:
            pass
        try:
            project.layersRemoved.disconnect(self._on_project_layers_changed)
        except TypeError:
            pass
        super()._disconnect_project_signals()

    def _active_vector_layer(self):
        layer = self.iface.activeLayer()
        if layer is None or layer.type() != QgsMapLayerType.VectorLayer:
            return None
        return layer

    def _layer_tree_view(self):
        return getattr(self.iface, "layerTreeView", lambda: None)()

    def _ensure_bound_layer_indicator_space(self):
        layer_tree_view = self._layer_tree_view()
        if layer_tree_view is None:
            return

        try:
            current_width = int(layer_tree_view.layerMarkWidth())
        except Exception:
            current_width = 0

        if self._original_layer_mark_width is None:
            self._original_layer_mark_width = current_width

        try:
            layer_tree_view.setLayerMarkWidth(max(current_width, 24))
        except Exception:
            pass

    def _restore_bound_layer_indicator_space(self):
        if self._original_layer_mark_width is None:
            return

        layer_tree_view = self._layer_tree_view()
        if layer_tree_view is not None:
            try:
                layer_tree_view.setLayerMarkWidth(int(self._original_layer_mark_width))
            except Exception:
                pass
        self._original_layer_mark_width = None

    def _clear_bound_layer_indicators(self):
        layer_tree_view = self._layer_tree_view()
        layer_tree_root = QgsProject.instance().layerTreeRoot()
        for layer_id, indicator in list(self._layer_tree_indicators.items()):
            if layer_tree_view is not None:
                node = layer_tree_root.findLayer(layer_id) if layer_tree_root is not None else None
                try:
                    layer_tree_view.removeIndicator(node, indicator)
                except Exception:
                    pass
            if self._is_qt_object_alive(indicator):
                self._safe_qt_call(indicator.deleteLater)
        self._layer_tree_indicators.clear()

    def _refresh_bound_layer_indicators(self):
        self._clear_bound_layer_indicators()

        layer_tree_view = self._layer_tree_view()
        layer_tree_root = QgsProject.instance().layerTreeRoot()
        if layer_tree_view is None or layer_tree_root is None:
            return

        icon = QIcon(str(self._icon_path(connected=True)))
        added_any = False
        for layer in QgsProject.instance().mapLayers().values():
            if layer is None or layer.type() != QgsMapLayerType.VectorLayer:
                continue
            if not self._layer_has_butler_binding(layer):
                continue

            node = layer_tree_root.findLayer(layer.id())
            if node is None:
                continue

            if not added_any:
                self._ensure_bound_layer_indicator_space()
                added_any = True

            indicator = QgsLayerTreeViewIndicator(layer_tree_view)
            indicator.setIcon(icon)
            indicator.setToolTip(self.LAYER_TREE_TOOLTIP)
            self._layer_tree_indicators[layer.id()] = indicator
            layer_tree_view.addIndicator(node, indicator)

        if not added_any:
            self._restore_bound_layer_indicator_space()

    def _on_project_layers_changed(self, *args):
        del args
        QTimer.singleShot(0, self._refresh_bound_layer_indicators)

    def _on_project_cleared(self):
        super()._on_project_cleared()
        self._refresh_bound_layer_indicators()

    def _layer_has_butler_binding(self, layer) -> bool:
        if layer is None:
            return False

        try:
            config = layer.editFormConfig()
        except Exception:
            return False

        current_func = ""
        current_code = ""
        if hasattr(config, "initFunction"):
            current_func = str(config.initFunction() or "")
        if hasattr(config, "initCode"):
            current_code = str(config.initCode() or "")

        return current_func == INIT_FUNCTION_NAME and any(
            marker in current_code for marker in BOOTSTRAP_CODE_MARKERS
        )

    def _default_butler_layer(self):
        project_root = self._project_layer_root(QgsProject.instance().layerTreeRoot())
        layer = self._find_project_vector_layer_by_name(project_root, self.DEFAULT_BUTLER_LAYER_NAME)
        if layer is not None:
            return layer

        layer = self._find_vector_layer_by_name(QgsProject.instance().layerTreeRoot(), self.DEFAULT_BUTLER_LAYER_NAME)
        if layer is not None:
            return layer

        for layer in self._managed_layers:
            if layer is not None and layer.name() == self.DEFAULT_BUTLER_LAYER_NAME:
                return layer
        return None

    def _default_butler_config(self, layer) -> dict:
        layer_fields = [field.name() for field in layer.fields()]
        config = dict(_effective_layer_config(layer))
        config.update(
            {
                "path_field_name": _first_field_match(layer_fields, ["quelle_pfad", "Quelle_Pfad"]),
                "file_link_field_name": _first_field_match(layer_fields, ["quelle_1", "Quelle_1"]),
                "folder_link_field_name": _first_field_match(layer_fields, ["quelle_2", "Quelle_2"]),
                "name_field_name": "",
                "stand_field_name": _first_field_match(layer_fields, ["Stand"]),
                "operator_name_field_name": _first_field_match(layer_fields, ["Betreiber"]),
                "operator_contact_field_name": _first_field_match(layer_fields, ["betr_anspr"]),
                "operator_phone_field_name": _first_field_match(layer_fields, ["betr_tel"]),
                "operator_email_field_name": _first_field_match(layer_fields, ["betr_email"]),
                "operator_fault_field_name": _first_field_match(
                    layer_fields,
                    ["Stör-Nr.", "Stör-Nr", "Stoer-Nr.", "Stoer-Nr", "stoer-nr", "stör-nr"],
                ),
                "operator_validity_field_name": _first_field_match(
                    layer_fields,
                    ["Gültigk.", "Gültigk", "Gueltigk.", "Gueltigk", "gueltigk", "gültigk"],
                ),
                "operator_stand_field_name": _first_field_match(layer_fields, ["Stand"]),
                "fill_on_form_open": True,
                "overwrite_existing_values": True,
            }
        )
        return config

    def _ensure_default_butler_binding(self):
        layer = self._default_butler_layer()
        if layer is None or self._layer_has_butler_binding(layer):
            return

        config = self._default_butler_config(layer)
        if not config.get("nextcloud_base_url") or not config.get("nextcloud_user") or not config.get("nextcloud_app_password"):
            return
        if not config.get("path_field_name") or not config.get("operator_name_field_name"):
            return

        if not _apply_configuration_to_layer(
            self.iface,
            layer,
            config,
            merged_operator_entries=None,
            parent=self.iface.mainWindow(),
            prompt_sync_existing=False,
            show_success_message=False,
        ):
            return

        self._refresh_bound_layer_indicators()

        if self._current_project_dir is not None:
            self._save_project_file(self._current_project_dir, notify=False)

        push_butler_message(
            self.iface.messageBar(),
            "Projektstarter Butler",
            "Der Standardlayer 'Fremdleitungen' wurde automatisch mit der Betreiberliste verbunden.",
            level=Qgis.Success,
            duration=5,
            parent=self.iface.mainWindow(),
        )

    def _connect_project(self, project_dir, notify=True):
        super()._connect_project(project_dir, notify=notify)
        if self._current_project_dir is None:
            return
        self._ensure_default_butler_binding()

    def add_template_layers(self, notify=True):
        added = super().add_template_layers(notify=notify)
        if self._current_project_dir is not None:
            self._ensure_default_butler_binding()
        return added

    def run(self):
        self._refresh_connection_state()
        dialog = ProjectStarterButlerDialog(self, self.iface.mainWindow())
        dialog.exec_()
        self._refresh_bound_layer_indicators()

    def _refresh_connection_state(self):
        super()._refresh_connection_state()
        self._refresh_bound_layer_indicators()

    def unbind_active_layer(self):
        layer = self._active_vector_layer()
        if layer is None:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Projektstarter Butler",
                "Bitte zuerst einen Vektor-Layer aktivieren.",
            )
            return

        from .attribution_plugin import _clear_layer_config, _remove_form_init_code_if_managed

        _clear_layer_config(layer)
        _remove_form_init_code_if_managed(layer)
        self._refresh_bound_layer_indicators()
        push_butler_message(
            self.iface.messageBar(),
            "Projektstarter Butler",
            f"Layer '{layer.name()}' wurde vom Butler getrennt.",
            level=Qgis.Info,
            duration=5,
            parent=self.iface.mainWindow(),
        )
