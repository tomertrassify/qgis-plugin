import os
import sys

from qgis.PyQt.QtCore import QEvent, QObject, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QApplication

from .quick_search_dialog import QuickSearchDialog


class MapSearchProPlugin(QObject):
    def __init__(self, iface):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.action = None
        self.dialog = None
        self._event_filter_installed = False

    def _shortcut_text(self):
        return "Meta+F" if sys.platform == "darwin" else "Ctrl+F"

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        self.action = QAction(
            QIcon(icon_path), "Map Search Pro Quick Search", self.iface.mainWindow()
        )
        self.action.setObjectName("MapSearchProQuickSearchAction")
        self.action.setShortcut(self._shortcut_text())
        self.action.setShortcutContext(Qt.ApplicationShortcut)
        self.action.setStatusTip("Search OSM places and POIs")
        self.action.triggered.connect(self.show_quick_search)

        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&Map Search Pro", self.action)
        self.iface.registerMainWindowAction(self.action, self._shortcut_text())

        app = QApplication.instance()
        if app is not None and not self._event_filter_installed:
            app.installEventFilter(self)
            self._event_filter_installed = True

    def unload(self):
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None

        app = QApplication.instance()
        if app is not None and self._event_filter_installed:
            app.removeEventFilter(self)
            self._event_filter_installed = False

        if self.action is not None:
            self.iface.unregisterMainWindowAction(self.action)
            self.iface.removePluginMenu("&Map Search Pro", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None

    def show_quick_search(self):
        if self.dialog is None:
            self.dialog = QuickSearchDialog(self.iface, self.iface.mainWindow())
        self.dialog.show_overlay()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.ShortcutOverride, QEvent.KeyPress):
            if self._is_find_shortcut(event):
                event.accept()
                if event.type() == QEvent.KeyPress:
                    self.show_quick_search()
                return True
        return super().eventFilter(watched, event)

    def _is_find_shortcut(self, event):
        if event.key() != Qt.Key_F:
            return False

        modifiers = event.modifiers() & (
            Qt.ControlModifier | Qt.MetaModifier | Qt.AltModifier | Qt.ShiftModifier
        )

        if sys.platform == "darwin":
            return modifiers == Qt.MetaModifier
        return modifiers == Qt.ControlModifier
