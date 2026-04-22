import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .github_dialog import TrassifyGithubDialog


class TrassifyGithubPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None
        self._plugin_menu_registered = False
        self._toolbar_registered = False
        self._plugin_menu = "&Trassify Github"
        self._plugin_dir = os.path.dirname(__file__)

    def initGui(self):
        self.action = QAction(
            QIcon(os.path.join(self._plugin_dir, "icon.svg")),
            "Trassify Github",
            self.iface.mainWindow(),
        )
        self.action.setObjectName("trassifyGithubAction")
        self.action.triggered.connect(self.run)

        if hasattr(self.iface, "addToolBarIcon"):
            self.iface.addToolBarIcon(self.action)
            self._toolbar_registered = True

        if hasattr(self.iface, "addPluginToMenu"):
            self.iface.addPluginToMenu(self._plugin_menu, self.action)
            self._plugin_menu_registered = True

    def unload(self):
        if self.dialog is not None:
            self.dialog.shutdown()
            self.dialog.deleteLater()
            self.dialog = None

        if self.action is None:
            return

        if self._toolbar_registered and hasattr(self.iface, "removeToolBarIcon"):
            self.iface.removeToolBarIcon(self.action)

        if self._plugin_menu_registered and hasattr(self.iface, "removePluginMenu"):
            self.iface.removePluginMenu(self._plugin_menu, self.action)

        self.action.deleteLater()
        self.action = None

    def run(self):
        if self.dialog is None:
            self.dialog = TrassifyGithubDialog(
                self.iface,
                self.iface.mainWindow(),
            )

        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
