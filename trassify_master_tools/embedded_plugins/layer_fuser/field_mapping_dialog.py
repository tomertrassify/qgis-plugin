from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class FieldMappingDialog(QDialog):
    IGNORE_VALUE = "__ignore__"

    def __init__(self, target_layer, source_layer, parent=None):
        super().__init__(parent)
        self.target_layer = target_layer
        self.source_layer = source_layer
        self._mapping = {}
        self._combo_by_source_name = {}
        self._source_fields = [field for field in source_layer.fields()]
        self._target_fields = [field for field in target_layer.fields()]
        self._target_field_names = [field.name() for field in self._target_fields]

        self.setWindowTitle("Layer Fuser - Feldzuordnung")
        self.resize(820, 520)
        self._build_ui()

    def mapping(self):
        return dict(self._mapping)

    def accept(self):
        mapping = {}
        used_target_fields = {}

        for source_name, combo in self._combo_by_source_name.items():
            target_name = combo.currentData()
            if target_name == self.IGNORE_VALUE:
                continue

            if target_name in used_target_fields:
                QMessageBox.warning(
                    self,
                    "Layer Fuser",
                    (
                        "Das Zielfeld '{0}' ist mehrfach zugeordnet: '{1}' und '{2}'. "
                        "Bitte waehlen Sie eindeutige Zuordnungen oder ignorieren Sie eines der Felder."
                    ).format(target_name, used_target_fields[target_name], source_name),
                )
                return

            used_target_fields[target_name] = source_name
            mapping[source_name] = target_name

        self._mapping = mapping
        super().accept()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        intro_label = QLabel(
            "Gleich benannte Felder sind bereits vorausgewaehlt. "
            "Abweichende Felder koennen Sie einem Zielfeld zuordnen oder ignorieren."
        )
        intro_label.setWordWrap(True)
        intro_label.setAlignment(Qt.AlignTop)
        layout.addWidget(intro_label)

        source_names = [field.name() for field in self._source_fields]
        target_names = self._target_field_names
        same_names = [name for name in source_names if name in target_names]
        source_only = [name for name in source_names if name not in target_names]
        target_only = [name for name in target_names if name not in source_names]

        layout.addWidget(self._info_label("Ziellayer", self.target_layer.name()))
        layout.addWidget(self._info_label("Quellayer", self.source_layer.name()))
        layout.addWidget(self._info_label("Gleiche Feldnamen", self._format_names(same_names)))
        layout.addWidget(self._info_label("Nur im Quellayer", self._format_names(source_only)))
        layout.addWidget(self._info_label("Nur im Ziellayer", self._format_names(target_only)))

        self.table = QTableWidget(len(self._source_fields), 4, self)
        self.table.setHorizontalHeaderLabels(["Quellfeld", "Quelltyp", "Status", "Zielfeld"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)

        for row, field in enumerate(self._source_fields):
            source_name = field.name()
            suggested_target_name = self._suggest_target_name(source_name)
            status = "Gleicher Name" if source_name in target_names else "Abweichend"
            if suggested_target_name and suggested_target_name != source_name:
                status = "Vorschlag"

            self._set_item(row, 0, source_name)
            self._set_item(row, 1, field.typeName() or "Unbekannt")
            self._set_item(row, 2, status)

            combo = QComboBox(self.table)
            combo.addItem("Ignorieren", self.IGNORE_VALUE)
            for target_field in self._target_fields:
                combo.addItem(self._target_field_label(target_field), target_field.name())

            if suggested_target_name:
                selected_index = combo.findData(suggested_target_name)
                if selected_index >= 0:
                    combo.setCurrentIndex(selected_index)

            self.table.setCellWidget(row, 3, combo)
            self._combo_by_source_name[source_name] = combo

        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _format_names(self, names):
        return ", ".join(names) if names else "Keine"

    def _info_label(self, title, value):
        label = QLabel(f"<b>{title}:</b> {value}")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignTop)
        return label

    def _set_item(self, row, column, text):
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsEnabled)
        self.table.setItem(row, column, item)

    def _suggest_target_name(self, source_name):
        if source_name in self._target_field_names:
            return source_name

        lower_name_map = {name.lower(): name for name in self._target_field_names}
        return lower_name_map.get(source_name.lower())

    def _target_field_label(self, field):
        field_type = field.typeName() or "Unbekannt"
        return f"{field.name()} ({field_type})"
