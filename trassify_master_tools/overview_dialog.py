from __future__ import annotations

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)


class MasterOverviewDialog(QDialog):
    def __init__(self, plugin_controller, parent=None):
        super().__init__(parent)
        self.plugin_controller = plugin_controller

        self.setWindowTitle("Trassify Master Tools")
        self.setWindowIcon(QIcon(str(plugin_controller.plugin_dir / "icon.svg")))
        self.resize(760, 460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.summary_label = QLabel(self)
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.module_list = QTreeWidget(self)
        self.module_list.setColumnCount(3)
        self.module_list.setHeaderLabels(["Modul", "Paket", "Status"])
        self.module_list.setAlternatingRowColors(True)
        self.module_list.setRootIsDecorated(False)
        self.module_list.setUniformRowHeights(True)
        self.module_list.itemDoubleClicked.connect(self._handle_item_double_click)
        self.module_list.itemSelectionChanged.connect(self._sync_buttons)
        layout.addWidget(self.module_list, 1)

        self.details_label = QLabel(self)
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.details_label)

        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(8)
        self.load_button = QPushButton("Ausgewaehltes Modul laden", self)
        self.load_button.clicked.connect(self._load_selected_module)
        actions_layout.addWidget(self.load_button)

        self.refresh_button = QPushButton("Aktualisieren", self)
        self.refresh_button.clicked.connect(self.refresh)
        actions_layout.addWidget(self.refresh_button)
        actions_layout.addStretch(1)
        layout.addLayout(actions_layout)

        button_box = QDialogButtonBox(QDialogButtonBox.Close, self)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.refresh()

    def refresh(self):
        items_by_key = {}
        current_item = self.module_list.currentItem()
        current_key = current_item.data(0, Qt.UserRole) if current_item is not None else None

        self.module_list.clear()

        rows = self.plugin_controller.get_module_rows()
        loaded_count = sum(1 for row in rows if row["status_code"] == "loaded")
        ready_count = sum(1 for row in rows if row["status_code"] == "ready")
        blocked_count = sum(1 for row in rows if row["status_code"] in {"conflict", "error"})

        self.summary_label.setText(
            f"{loaded_count} geladen, {ready_count} bereit, {blocked_count} mit Hinweis."
        )

        for row in rows:
            item = QTreeWidgetItem([row["label"], row["package"], row["status_text"]])
            item.setData(0, Qt.UserRole, row["key"])
            item.setData(0, Qt.UserRole + 1, row["status_code"])
            item.setData(0, Qt.UserRole + 2, row["detail"])
            item.setToolTip(0, row["detail"])
            item.setToolTip(1, row["package"])
            item.setToolTip(2, row["detail"])
            self.module_list.addTopLevelItem(item)
            items_by_key[row["key"]] = item

        self.module_list.resizeColumnToContents(0)
        self.module_list.resizeColumnToContents(1)

        if current_key in items_by_key:
            self.module_list.setCurrentItem(items_by_key[current_key])
        elif self.module_list.topLevelItemCount() > 0:
            self.module_list.setCurrentItem(self.module_list.topLevelItem(0))

        self._sync_buttons()

    def _sync_buttons(self):
        item = self.module_list.currentItem()
        if item is None:
            self.load_button.setEnabled(False)
            self.details_label.setText("Kein Modul ausgewaehlt.")
            return

        status_code = item.data(0, Qt.UserRole + 1)
        detail = item.data(0, Qt.UserRole + 2)
        self.load_button.setEnabled(status_code == "ready")
        self.details_label.setText(detail)

    def _load_selected_module(self):
        item = self.module_list.currentItem()
        if item is None:
            return

        key = item.data(0, Qt.UserRole)
        if key is None:
            return

        self.plugin_controller.load_module_by_key(key)
        self.refresh()

    def _handle_item_double_click(self, item, _column):
        if item.data(0, Qt.UserRole + 1) != "ready":
            return
        self._load_selected_module()
