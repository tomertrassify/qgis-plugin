import json
from datetime import datetime
from pathlib import Path

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QDate, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QAction,
    QCalendarWidget,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)


STATUS_OPTIONS = (
    "Neu",
    "in Arbeit",
    "Fehlende Betreiber Antwort",
    "Fertig",
)
STATUS_LOOKUP = {status.casefold(): status for status in STATUS_OPTIONS}


def normalize_date_text(raw_value):
    text = str(raw_value or "").strip()
    if not text:
        return ""

    for date_format in (
        "%d.%m.%Y",
        "%d.%m.%y",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d-%m-%y",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%d/%m/%y",
    ):
        try:
            return datetime.strptime(text, date_format).strftime("%d.%m.%Y")
        except ValueError:
            continue

    raise ValueError(
        f"Ungueltiges Datum '{text}'. Erwartet wird dd.MM.yyyy."
    )


def display_date_text(raw_value):
    text = str(raw_value or "").strip()
    if not text:
        return ""

    try:
        return normalize_date_text(text)
    except ValueError:
        return text


def normalize_status_value(raw_value):
    text = str(raw_value or "").strip()
    if not text:
        return "Neu"
    return STATUS_LOOKUP.get(text.casefold(), text)


class DateInputWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.line_edit = QLineEdit(self)
        self.line_edit.setPlaceholderText("dd.MM.yyyy")
        self.line_edit.setClearButtonEnabled(True)
        layout.addWidget(self.line_edit, 1)

        self.calendar_button = QToolButton(self)
        self.calendar_button.setText("...")
        self.calendar_button.setToolTip("Kalender oeffnen")
        self.calendar_button.clicked.connect(self._open_calendar)
        layout.addWidget(self.calendar_button)

        self.calendar_menu = QMenu(self)
        self.calendar_widget = QCalendarWidget(self.calendar_menu)
        self.calendar_widget.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.calendar_widget.clicked.connect(self._apply_calendar_date)

        calendar_action = QWidgetAction(self.calendar_menu)
        calendar_action.setDefaultWidget(self.calendar_widget)
        self.calendar_menu.addAction(calendar_action)

    def optional_text(self):
        return self.line_edit.text().strip()

    def set_optional_text(self, value):
        self.line_edit.setText(display_date_text(value))

    def _open_calendar(self):
        current_date = QDate.currentDate()
        raw_text = self.optional_text()
        if raw_text:
            try:
                normalized = normalize_date_text(raw_text)
            except ValueError:
                normalized = ""
            if normalized:
                parsed_date = QDate.fromString(normalized, "dd.MM.yyyy")
                if parsed_date.isValid():
                    current_date = parsed_date

        self.calendar_widget.setSelectedDate(current_date)
        self.calendar_menu.popup(self.calendar_button.mapToGlobal(self.calendar_button.rect().bottomLeft()))

    def _apply_calendar_date(self, selected_date):
        self.line_edit.setText(selected_date.toString("dd.MM.yyyy"))
        self.calendar_menu.close()


class ProjectStatusManagerDialog(QDialog):
    COLUMN_PROJECT = 0
    COLUMN_STATUS_URL = 1
    COLUMN_STATUS = 2
    COLUMN_DOWNLOAD_TOKEN = 3
    COLUMN_BAUBEGINN = 4

    def __init__(self, plugin, parent=None):
        super().__init__(parent or plugin.iface.mainWindow())
        self.plugin = plugin
        self.projects = []

        self.setWindowTitle("Projektstatus Butler")
        self.setWindowIcon(QIcon(str(plugin._icon_path())))
        self.resize(1460, 860)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        title_label = QLabel("Projektstatus fuer Max Wild", self)
        title_label.setStyleSheet("font-size: 22px; font-weight: 700;")
        root_layout.addWidget(title_label)

        self.path_label = QLabel(f"Quelle: {self.plugin.PROJECTS_ROOT}", self)
        self.path_label.setWordWrap(True)
        root_layout.addWidget(self.path_label)

        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(8)

        filter_label = QLabel("Filter:", self)
        filter_row.addWidget(filter_label)

        self.filter_input = QLineEdit(self)
        self.filter_input.setPlaceholderText("Nach Projektname, Status, Token oder Datum filtern")
        self.filter_input.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self.filter_input, 1)

        self.summary_label = QLabel("", self)
        filter_row.addWidget(self.summary_label)

        self.reload_button = QPushButton("Neu laden", self)
        self.reload_button.clicked.connect(self.reload_rows)
        filter_row.addWidget(self.reload_button)

        root_layout.addLayout(filter_row)

        self.table = QTableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            (
                "Projektordner",
                "Status URL",
                "Status",
                "Download Token",
                "Baubeginn",
            )
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.SelectedClicked
        )
        self.table.itemChanged.connect(lambda _item: self._apply_filter(self.filter_input.text()))
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.COLUMN_PROJECT, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COLUMN_STATUS_URL, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COLUMN_STATUS, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COLUMN_DOWNLOAD_TOKEN, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COLUMN_BAUBEGINN, QHeaderView.ResizeToContents)
        root_layout.addWidget(self.table, 1)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Close,
            parent=self,
        )
        self.button_box.accepted.connect(self.save_rows)
        self.button_box.rejected.connect(self.reject)
        root_layout.addWidget(self.button_box)

        self.reload_rows()

    def reload_rows(self):
        try:
            self.projects = self.plugin.load_projects()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Projektstatus Butler",
                f"Projektordner konnten nicht geladen werden:\n{exc}",
            )
            return

        self.table.setRowCount(0)
        for row_index, project in enumerate(self.projects):
            self.table.insertRow(row_index)
            self._populate_row(row_index, project)

        self._apply_filter(self.filter_input.text())

    def _populate_row(self, row_index, project):
        data = project["data"]

        project_item = QTableWidgetItem(project["name"])
        project_item.setFlags(project_item.flags() & ~Qt.ItemIsEditable)
        project_item.setData(Qt.UserRole, str(project["status_path"]))
        project_item.setToolTip(str(project["status_path"]))
        self.table.setItem(row_index, self.COLUMN_PROJECT, project_item)

        status_url_item = QTableWidgetItem(str(data.get("statusUrl", "")))
        self.table.setItem(row_index, self.COLUMN_STATUS_URL, status_url_item)

        status_box = QComboBox(self.table)
        current_status = normalize_status_value(data.get("status", ""))
        if current_status and current_status not in STATUS_OPTIONS:
            status_box.addItem(current_status)
        status_box.addItems(STATUS_OPTIONS)
        if current_status:
            status_box.setCurrentText(current_status)
        else:
            status_box.setCurrentText("Neu")
        status_box.currentTextChanged.connect(lambda _text: self._apply_filter(self.filter_input.text()))
        self.table.setCellWidget(row_index, self.COLUMN_STATUS, status_box)

        download_token_item = QTableWidgetItem(str(data.get("downloadToken", "")))
        self.table.setItem(row_index, self.COLUMN_DOWNLOAD_TOKEN, download_token_item)

        date_widget = DateInputWidget(self.table)
        date_widget.set_optional_text(data.get("baubeginn", ""))
        date_widget.line_edit.textChanged.connect(
            lambda _text: self._apply_filter(self.filter_input.text())
        )
        self.table.setCellWidget(row_index, self.COLUMN_BAUBEGINN, date_widget)

    def _apply_filter(self, filter_text):
        needle = str(filter_text or "").strip().casefold()
        visible_rows = 0

        for row_index in range(self.table.rowCount()):
            row_text = self._row_text(row_index)
            matches = not needle or needle in row_text
            self.table.setRowHidden(row_index, not matches)
            if matches:
                visible_rows += 1

        self.summary_label.setText(f"{visible_rows} / {self.table.rowCount()} Projekte")

    def _row_text(self, row_index):
        parts = []
        for column in (self.COLUMN_PROJECT, self.COLUMN_STATUS_URL, self.COLUMN_DOWNLOAD_TOKEN):
            item = self.table.item(row_index, column)
            if item is not None:
                parts.append(item.text())

        status_box = self.table.cellWidget(row_index, self.COLUMN_STATUS)
        if isinstance(status_box, QComboBox):
            parts.append(status_box.currentText())

        date_widget = self.table.cellWidget(row_index, self.COLUMN_BAUBEGINN)
        if isinstance(date_widget, DateInputWidget):
            parts.append(date_widget.optional_text())

        return " ".join(parts).casefold()

    def save_rows(self):
        updates = []

        for row_index, project in enumerate(self.projects):
            status_url_item = self.table.item(row_index, self.COLUMN_STATUS_URL)
            download_token_item = self.table.item(row_index, self.COLUMN_DOWNLOAD_TOKEN)
            status_box = self.table.cellWidget(row_index, self.COLUMN_STATUS)
            date_widget = self.table.cellWidget(row_index, self.COLUMN_BAUBEGINN)

            if status_url_item is None or download_token_item is None:
                QMessageBox.warning(
                    self,
                    "Projektstatus Butler",
                    f"Zeile {row_index + 1} ist unvollstaendig und konnte nicht gespeichert werden.",
                )
                return

            if not isinstance(status_box, QComboBox) or not isinstance(date_widget, DateInputWidget):
                QMessageBox.warning(
                    self,
                    "Projektstatus Butler",
                    f"Editoren in Zeile {row_index + 1} konnten nicht gelesen werden.",
                )
                return

            try:
                normalized_date = normalize_date_text(date_widget.optional_text())
            except ValueError as exc:
                QMessageBox.warning(
                    self,
                    "Projektstatus Butler",
                    f"{project['name']}: {exc}",
                )
                return

            new_data = self._build_updated_data(
                original_data=project["data"],
                status_url=status_url_item.text().strip(),
                status=normalize_status_value(status_box.currentText()),
                download_token=download_token_item.text().strip(),
                baubeginn=normalized_date,
            )
            updates.append((project, new_data))

        changed_count = 0
        for project, new_data in updates:
            if new_data == project["data"]:
                continue

            project["status_path"].write_text(
                json.dumps(new_data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            project["data"] = new_data
            changed_count += 1

        QMessageBox.information(
            self,
            "Projektstatus Butler",
            f"{changed_count} status.json-Datei(en) gespeichert.",
        )
        self.reload_rows()

    def _build_updated_data(self, original_data, status_url, status, download_token, baubeginn):
        managed_keys = {"statusUrl", "status", "downloadToken", "baubeginn"}
        new_data = {}

        if status_url:
            new_data["statusUrl"] = status_url
        new_data["status"] = status
        if download_token:
            new_data["downloadToken"] = download_token
        if baubeginn:
            new_data["baubeginn"] = baubeginn

        for key, value in original_data.items():
            if key not in managed_keys:
                new_data[key] = value

        return new_data


class ProjectStatusManagerPlugin:
    PROJECTS_ROOT = Path("/Users/tomermaith/Documents/repo-webmap/max-wild/_projekte")
    TOOLBAR_NAME = "Projektstatus Butler"
    TOOLBAR_OBJECT_NAME = "ProjektstatusButlerToolbar"
    ICON_FILENAME = "icon.svg"

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = Path(__file__).resolve().parent
        self.action = None
        self.toolbar = None

    def initGui(self):
        self.action = QAction(
            QIcon(str(self._icon_path())),
            "Projektstatus Butler",
            self.iface.mainWindow(),
        )
        self.action.triggered.connect(self.run)

        self.toolbar = self.iface.addToolBar(self.TOOLBAR_NAME)
        self.toolbar.setObjectName(self.TOOLBAR_OBJECT_NAME)
        self.toolbar.setToolTip(self.TOOLBAR_NAME)
        self.toolbar.setWindowIcon(QIcon(str(self._icon_path())))
        self.toolbar.addAction(self.action)

        self.iface.addPluginToMenu(self.TOOLBAR_NAME, self.action)

    def unload(self):
        action = self.action
        toolbar = self._find_toolbar()

        self.action = None
        self.toolbar = None

        if self._is_qt_object_alive(action):
            self._safe_qt_call(self.iface.removePluginMenu, self.TOOLBAR_NAME, action)
            self._safe_qt_call(action.deleteLater)

        if self._is_qt_object_alive(toolbar):
            self._safe_qt_call(self.iface.mainWindow().removeToolBar, toolbar)
            self._safe_qt_call(toolbar.deleteLater)

    def run(self):
        dialog = ProjectStatusManagerDialog(self)
        dialog.exec()

    def load_projects(self):
        if not self.PROJECTS_ROOT.is_dir():
            raise FileNotFoundError(f"Projektpfad nicht gefunden: {self.PROJECTS_ROOT}")

        projects = []
        for project_dir in sorted(self.PROJECTS_ROOT.iterdir(), key=lambda path: path.name.casefold()):
            if not project_dir.is_dir():
                continue

            status_path = project_dir / "status.json"
            if not status_path.is_file():
                continue

            try:
                data = json.loads(status_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Ungueltige JSON-Datei: {status_path}\n{exc}") from exc

            if not isinstance(data, dict):
                raise ValueError(f"status.json ist kein JSON-Objekt: {status_path}")

            projects.append(
                {
                    "name": project_dir.name,
                    "project_dir": project_dir,
                    "status_path": status_path,
                    "data": data,
                }
            )

        return projects

    def _icon_path(self):
        return self.plugin_dir / self.ICON_FILENAME

    def _find_toolbar(self):
        try:
            return self.iface.mainWindow().findChild(QToolBar, self.TOOLBAR_OBJECT_NAME)
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
