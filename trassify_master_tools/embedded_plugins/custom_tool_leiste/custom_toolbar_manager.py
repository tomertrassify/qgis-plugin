import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .toolbar_manager_dock import ToolbarManagerDock


class CustomToolbarManagerPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dock = None

    def initGui(self):
        self.dock = ToolbarManagerDock(self.iface, self.plugin_dir)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.hide()

        action_icon = QIcon(os.path.join(self.plugin_dir, "icon.svg"))
        self.action = QAction(
            action_icon,
            "Custom Tool-Leiste oeffnen/schliessen",
            self.iface.mainWindow(),
        )
        self.action.triggered.connect(self._toggle_dock)

        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("Custom Tool-Leiste", self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginMenu("Custom Tool-Leiste", self.action)
            self.action.deleteLater()
            self.action = None

        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

    def _toggle_dock(self):
        if self.dock is None:
            return

        if self.dock.isVisible():
            self.dock.hide()
        else:
            self.dock.refresh()
            self.dock.show()
            self.dock.raise_()
