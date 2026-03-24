from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from qgis.core import Qgis, QgsMapLayerType, QgsProject

from .attribution_plugin import (
    LayerConfigDialog,
    _apply_configuration_to_layer,
    _effective_layer_config,
)
from .project_profile import current_profile_path_string
from .projectstarter_plugin import ProjectStarterPlugin


class ProjectStarterButlerDialog(QDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent or plugin.iface.mainWindow())
        self.plugin = plugin
        self.layer_config_dialog = None
        self.current_layer = None
        self.placeholder_label = None

        self.setWindowTitle("Projektstarter Butler")
        self.setWindowIcon(QIcon(str(plugin._icon_path(plugin._has_active_connection()))))
        self.resize(1320, 860)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        intro_label = QLabel(
            "Projektordner, Projektstatus und Betreiber-/Layer-Konfiguration liegen hier in einem Overlay. "
            "Die Betreiberliste und Datenquellen kommen direkt aus der eingebetteten Butler-Konfiguration."
        )
        intro_label.setWordWrap(True)
        root_layout.addWidget(intro_label)

        project_group = QGroupBox("Projekt")
        project_layout = QGridLayout(project_group)
        project_layout.setColumnStretch(1, 1)

        self.connection_value = QLabel("-")
        self.connection_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.project_dir_value = QLabel("-")
        self.project_dir_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.profile_path_value = QLabel("-")
        self.profile_path_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.active_layer_value = QLabel("-")
        self.active_layer_value.setTextInteractionFlags(Qt.TextSelectableByMouse)

        project_layout.addWidget(QLabel("Projektstatus"), 0, 0)
        project_layout.addWidget(self.connection_value, 0, 1)
        project_layout.addWidget(QLabel("Projektordner"), 1, 0)
        project_layout.addWidget(self.project_dir_value, 1, 1)
        project_layout.addWidget(QLabel("Projektprofil"), 2, 0)
        project_layout.addWidget(self.profile_path_value, 2, 1)
        project_layout.addWidget(QLabel("Aktiver Layer"), 3, 0)
        project_layout.addWidget(self.active_layer_value, 3, 1)

        note_label = QLabel(
            "Hinweis: Das Projektprofil speichert Betreiberliste, Datenquellen und Feldzuordnung projektweit. "
            "Das Nextcloud-App-Passwort bleibt aus Sicherheitsgruenden lokal auf dem jeweiligen Rechner."
        )
        note_label.setWordWrap(True)
        project_layout.addWidget(note_label, 4, 0, 1, 2)

        button_row = QHBoxLayout()
        self.choose_project_button = QPushButton("Projektordner waehlen...")
        self.choose_project_button.clicked.connect(self._choose_project)
        self.refresh_project_button = QPushButton("Projekt aktualisieren")
        self.refresh_project_button.clicked.connect(self._refresh_project)
        self.sync_plans_button = QPushButton("Leitungsauskunft")
        self.sync_plans_button.clicked.connect(self._sync_plans)
        self.zoom_button = QPushButton("Zum Projektgebiet")
        self.zoom_button.clicked.connect(self._zoom_to_project)
        self.save_project_button = QPushButton("Projekt speichern")
        self.save_project_button.clicked.connect(self._save_project)
        self.disconnect_button = QPushButton("Verbindung trennen")
        self.disconnect_button.clicked.connect(self._disconnect_project)
        self.refresh_layer_button = QPushButton("Aktiven Layer uebernehmen")
        self.refresh_layer_button.clicked.connect(self._reload_active_layer)

        for button in (
            self.choose_project_button,
            self.refresh_project_button,
            self.sync_plans_button,
            self.zoom_button,
            self.save_project_button,
            self.disconnect_button,
            self.refresh_layer_button,
        ):
            button_row.addWidget(button)
        button_row.addStretch(1)
        project_layout.addLayout(button_row, 5, 0, 1, 2)

        root_layout.addWidget(project_group)

        self.layer_host = QWidget(self)
        self.layer_host_layout = QVBoxLayout(self.layer_host)
        self.layer_host_layout.setContentsMargins(0, 0, 0, 0)
        self.layer_host_layout.setSpacing(0)
        root_layout.addWidget(self.layer_host, 1)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close, self)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        root_layout.addWidget(self.button_box)

        self.refresh_state(rebuild_layer=True)

    def _active_vector_layer(self):
        layer = self.plugin.iface.activeLayer()
        if layer is None or layer.type() != QgsMapLayerType.VectorLayer:
            return None
        return layer

    def _clear_layer_host(self):
        if self.layer_config_dialog is not None:
            self.layer_host_layout.removeWidget(self.layer_config_dialog)
            self.layer_config_dialog.deleteLater()
            self.layer_config_dialog = None
        if self.placeholder_label is not None:
            self.layer_host_layout.removeWidget(self.placeholder_label)
            self.placeholder_label.deleteLater()
            self.placeholder_label = None

    def _rebuild_layer_panel(self, layer):
        self._clear_layer_host()
        self.current_layer = layer

        if layer is None:
            self.placeholder_label = QLabel(
                "Aktiviere in QGIS einen Vektor-Layer und klicke dann auf "
                "'Aktiven Layer uebernehmen', damit hier die komplette Butler-Konfiguration erscheint."
            )
            self.placeholder_label.setWordWrap(True)
            self.placeholder_label.setAlignment(Qt.AlignCenter)
            self.placeholder_label.setMinimumHeight(220)
            self.layer_host_layout.addWidget(self.placeholder_label)
            return

        dialog = LayerConfigDialog(layer, self)
        dialog.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        dialog.set_values(_effective_layer_config(layer))
        if getattr(dialog, "button_box", None) is not None:
            dialog.button_box.hide()
        self.layer_config_dialog = dialog
        self.layer_host_layout.addWidget(dialog)

    def refresh_state(self, rebuild_layer=False):
        project_dir = self.plugin._current_project_dir
        connected = self.plugin._has_active_connection()

        self.connection_value.setText("Verbunden" if connected else "Nicht verbunden")
        self.project_dir_value.setText(str(project_dir) if project_dir is not None else "-")

        profile_path = current_profile_path_string().strip()
        self.profile_path_value.setText(profile_path or "Wird nach dem ersten Projektspeichern angelegt.")

        active_layer = self._active_vector_layer()
        self.active_layer_value.setText(active_layer.name() if active_layer is not None else "-")

        self.refresh_project_button.setEnabled(project_dir is not None)
        self.sync_plans_button.setEnabled(project_dir is not None)
        self.zoom_button.setEnabled(project_dir is not None)
        self.save_project_button.setEnabled(project_dir is not None or bool(QgsProject.instance().fileName()))
        self.disconnect_button.setEnabled(project_dir is not None)

        if rebuild_layer or active_layer is not self.current_layer:
            self._rebuild_layer_panel(active_layer)

    def _choose_project(self):
        self.plugin._select_and_connect_project()
        self.refresh_state(rebuild_layer=True)

    def _refresh_project(self):
        self.plugin._refresh_current_connection()
        self.refresh_state(rebuild_layer=True)

    def _sync_plans(self):
        self.plugin._refresh_leitungsauskunft()
        self.refresh_state(rebuild_layer=False)

    def _zoom_to_project(self):
        self.plugin._zoom_to_project_area_now()
        self.refresh_state(rebuild_layer=False)

    def _disconnect_project(self):
        self.plugin._disconnect_current_connection()
        self.refresh_state(rebuild_layer=True)

    def _reload_active_layer(self):
        self.refresh_state(rebuild_layer=True)

    def _save_project(self):
        if self.plugin._current_project_dir is not None:
            self.plugin._save_project_file(self.plugin._current_project_dir, notify=True)
        elif str(QgsProject.instance().fileName() or "").strip():
            if not QgsProject.instance().write():
                QMessageBox.warning(
                    self,
                    "Projektstarter Butler",
                    "Das QGIS-Projekt konnte nicht gespeichert werden.",
                )
                return
        else:
            QMessageBox.information(
                self,
                "Projektstarter Butler",
                "Es ist noch kein Projektordner verbunden und kein QGIS-Projekt gespeichert.",
            )
            return
        self.refresh_state(rebuild_layer=False)

    def accept(self):
        if self.layer_config_dialog is None or self.current_layer is None:
            super().accept()
            return

        self.layer_config_dialog._store_current_local_operator_overlays_from_table()
        if not self.layer_config_dialog._save_external_operator_changes(show_feedback=False):
            return

        if not _apply_configuration_to_layer(
            self.plugin.iface,
            self.current_layer,
            self.layer_config_dialog.values(),
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
            "Layer-Konfiguration und Projektprofil wurden gespeichert.",
        )
        super().accept()


class ProjectStarterAttributionButlerPlugin(ProjectStarterPlugin):
    TOOLBAR_NAME = "Projektstarter Butler"
    TOOLBAR_OBJECT_NAME = "ProjektstarterButlerToolbar"
    DEFAULT_ICON_FILENAME = "projektstarter-butler.svg"
    CONNECTED_ICON_FILENAME = "projektstarter-butler-connected.svg"

    def __init__(self, iface):
        super().__init__(iface)
        self.action_unbind_hidden = None

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

        project = QgsProject.instance()
        project.readProject.connect(self._on_project_read)
        project.projectSaved.connect(self._on_project_saved)
        project.cleared.connect(self._on_project_cleared)
        QTimer.singleShot(0, self._refresh_connection_state)

    def unload(self):
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

    def _active_vector_layer(self):
        layer = self.iface.activeLayer()
        if layer is None or layer.type() != QgsMapLayerType.VectorLayer:
            return None
        return layer

    def run(self):
        self._refresh_connection_state()
        dialog = ProjectStarterButlerDialog(self, self.iface.mainWindow())
        dialog.exec_()

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
        self.iface.messageBar().pushMessage(
            "Projektstarter Butler",
            f"Layer '{layer.name()}' wurde vom Butler getrennt.",
            level=Qgis.Info,
            duration=5,
        )
