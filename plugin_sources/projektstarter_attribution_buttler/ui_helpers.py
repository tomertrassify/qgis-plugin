from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QInputDialog, QMessageBox as QtQMessageBox


_PLUGIN_DIR = Path(__file__).resolve().parent
_DEFAULT_ICON_PATH = _PLUGIN_DIR / "assets" / "projektstarter-butler.svg"
_DEFAULT_ICON = None


def butler_window_icon(parent=None) -> QIcon:
    if parent is not None:
        try:
            parent_icon = parent.windowIcon()
        except Exception:
            parent_icon = None
        if parent_icon is not None and not parent_icon.isNull():
            return parent_icon

    global _DEFAULT_ICON
    if _DEFAULT_ICON is None:
        _DEFAULT_ICON = QIcon(str(_DEFAULT_ICON_PATH))
    return _DEFAULT_ICON


def apply_butler_window_icon(widget, parent=None):
    if widget is None:
        return None

    icon_parent = parent
    if icon_parent is None:
        try:
            icon_parent = widget.parentWidget()
        except Exception:
            icon_parent = None

    try:
        widget.setWindowIcon(butler_window_icon(icon_parent))
    except Exception:
        pass
    return widget


class ButlerMessageBox(QtQMessageBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        apply_butler_window_icon(self, parent)

    @classmethod
    def _show_message(
        cls,
        icon,
        parent,
        title,
        text,
        buttons=QtQMessageBox.Ok,
        default_button=QtQMessageBox.NoButton,
    ):
        box = cls(parent)
        box.setIcon(icon)
        box.setWindowTitle(str(title or ""))
        box.setText(str(text or ""))
        box.setStandardButtons(buttons)
        if default_button != QtQMessageBox.NoButton:
            box.setDefaultButton(default_button)
        return box.exec_()

    @classmethod
    def information(
        cls,
        parent,
        title,
        text,
        buttons=QtQMessageBox.Ok,
        default_button=QtQMessageBox.NoButton,
    ):
        return cls._show_message(
            QtQMessageBox.Information,
            parent,
            title,
            text,
            buttons,
            default_button,
        )

    @classmethod
    def warning(
        cls,
        parent,
        title,
        text,
        buttons=QtQMessageBox.Ok,
        default_button=QtQMessageBox.NoButton,
    ):
        return cls._show_message(
            QtQMessageBox.Warning,
            parent,
            title,
            text,
            buttons,
            default_button,
        )

    @classmethod
    def critical(
        cls,
        parent,
        title,
        text,
        buttons=QtQMessageBox.Ok,
        default_button=QtQMessageBox.NoButton,
    ):
        return cls._show_message(
            QtQMessageBox.Critical,
            parent,
            title,
            text,
            buttons,
            default_button,
        )

    @classmethod
    def question(
        cls,
        parent,
        title,
        text,
        buttons=QtQMessageBox.StandardButtons(QtQMessageBox.Yes | QtQMessageBox.No),
        default_button=QtQMessageBox.NoButton,
    ):
        return cls._show_message(
            QtQMessageBox.Question,
            parent,
            title,
            text,
            buttons,
            default_button,
        )


def get_butler_item(parent, title, label, items, current=0, editable=False):
    dialog = QInputDialog(parent)
    apply_butler_window_icon(dialog, parent)
    dialog.setWindowTitle(str(title or ""))
    dialog.setLabelText(str(label or ""))
    dialog.setInputMode(QInputDialog.TextInput)
    combo_items = [str(item or "") for item in items]
    dialog.setComboBoxItems(combo_items)
    dialog.setComboBoxEditable(bool(editable))
    if combo_items:
        safe_index = max(0, min(int(current), len(combo_items) - 1))
        dialog.setTextValue(combo_items[safe_index])
    accepted = dialog.exec_() == dialog.Accepted
    return dialog.textValue(), accepted
