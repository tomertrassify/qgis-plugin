from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMenu
from qgis.core import QgsProject

from .attribution_plugin import NextcloudFormPlugin as AttributionButlerHelper
from .projectstarter_plugin import ProjectStarterPlugin


class ProjectStarterAttributionButlerPlugin(ProjectStarterPlugin):
    TOOLBAR_NAME = "Projektstarter Butler"
    TOOLBAR_OBJECT_NAME = "ProjektstarterButlerToolbar"

    def __init__(self, iface):
        super().__init__(iface)
        self.action_configure_layer = None
        self.action_unbind_hidden = None
        self._attribution_helper = AttributionButlerHelper(iface)

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

        self.action_configure_layer = QAction(
            QIcon(str(self.plugin_dir / "icon-512.png")),
            "Betreiberattribute fuer aktiven Layer konfigurieren",
            self.iface.mainWindow(),
        )
        self.action_configure_layer.setToolTip("AttributionButler fuer aktiven Layer oeffnen")
        self.action_configure_layer.triggered.connect(self.bind_active_layer)
        self.iface.addPluginToMenu(self.TOOLBAR_NAME, self.action_configure_layer)

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
        action_configure_layer = self.action_configure_layer
        action_unbind_hidden = self.action_unbind_hidden

        self.action_configure_layer = None
        self.action_unbind_hidden = None

        if self._is_qt_object_alive(action_configure_layer):
            self._safe_qt_call(self.iface.removePluginMenu, self.TOOLBAR_NAME, action_configure_layer)
            self._safe_qt_call(action_configure_layer.deleteLater)
        if self._is_qt_object_alive(action_unbind_hidden):
            self._safe_qt_call(self.iface.mainWindow().removeAction, action_unbind_hidden)
            self._safe_qt_call(action_unbind_hidden.deleteLater)

        super().unload()

    def bind_active_layer(self):
        self._attribution_helper.bind_active_layer()

    def unbind_active_layer(self):
        self._attribution_helper.unbind_active_layer()

    def _show_connection_menu(self):
        menu = QMenu(self.iface.mainWindow())
        refresh_action = menu.addAction("Verbindung aktualisieren")
        leitungsauskunft_action = menu.addAction("Leitungsauskunft aktualisieren")
        configure_layer_action = menu.addAction("Betreiberattribute fuer aktiven Layer konfigurieren")
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
        elif selected_action is configure_layer_action:
            self.bind_active_layer()
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
