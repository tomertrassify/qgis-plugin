from __future__ import annotations

from qgis.PyQt.QtCore import QEasingCurve, Qt
from qgis.PyQt.QtGui import QIcon, QPainter
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialogButtonBox,
    QFrame,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
)


def _enum(container, name, *scopes):
    value = getattr(container, name, None)
    if value is not None:
        return value

    for scope in scopes:
        nested = getattr(container, scope, None)
        if nested is None:
            continue
        value = getattr(nested, name, None)
        if value is not None:
            return value
        prefix = f"{scope}_"
        if name.startswith(prefix):
            value = getattr(nested, name[len(prefix) :], None)
            if value is not None:
                return value

    available_scopes = ", ".join(scopes) or "none"
    raise AttributeError(
        f"{container.__name__} has no enum member {name!r} in scopes: {available_scopes}"
    )


class QtCompat:
    AlignTop = _enum(Qt, "AlignTop", "AlignmentFlag")
    AlignRight = _enum(Qt, "AlignRight", "AlignmentFlag")
    AlignCenter = _enum(Qt, "AlignCenter", "AlignmentFlag")
    AlignHCenter = _enum(Qt, "AlignHCenter", "AlignmentFlag")
    AlignVCenter = _enum(Qt, "AlignVCenter", "AlignmentFlag")
    AlignLeft = _enum(Qt, "AlignLeft", "AlignmentFlag")
    Horizontal = _enum(Qt, "Horizontal", "Orientation")
    KeepAspectRatio = _enum(Qt, "KeepAspectRatio", "AspectRatioMode")
    KeepAspectRatioByExpanding = _enum(
        Qt,
        "KeepAspectRatioByExpanding",
        "AspectRatioMode",
    )
    MatchFixedString = _enum(Qt, "MatchFixedString", "MatchFlag")
    NoPen = _enum(Qt, "NoPen", "PenStyle")
    PlainText = _enum(Qt, "PlainText", "TextFormat")
    PointingHandCursor = _enum(Qt, "PointingHandCursor", "CursorShape")
    RichText = _enum(Qt, "RichText", "TextFormat")
    ScrollBarAlwaysOff = _enum(Qt, "ScrollBarAlwaysOff", "ScrollBarPolicy")
    ScrollBarAsNeeded = _enum(Qt, "ScrollBarAsNeeded", "ScrollBarPolicy")
    SmoothTransformation = _enum(Qt, "SmoothTransformation", "TransformationMode")
    TextBrowserInteraction = _enum(
        Qt,
        "TextBrowserInteraction",
        "TextInteractionFlag",
    )
    TextSelectableByMouse = _enum(
        Qt,
        "TextSelectableByMouse",
        "TextInteractionFlag",
    )
    Transparent = _enum(Qt, "transparent", "GlobalColor")
    ToolButtonIconOnly = _enum(Qt, "ToolButtonIconOnly", "ToolButtonStyle")
    UserRole = _enum(Qt, "UserRole", "ItemDataRole")


class QEasingCurveCompat:
    OutCubic = _enum(QEasingCurve, "OutCubic", "Type")


class QAbstractItemViewCompat:
    SingleSelection = _enum(QAbstractItemView, "SingleSelection", "SelectionMode")


class QDialogButtonBoxCompat:
    Cancel = _enum(QDialogButtonBox, "Cancel", "StandardButton")
    Close = _enum(QDialogButtonBox, "Close", "StandardButton")
    RestoreDefaults = _enum(QDialogButtonBox, "RestoreDefaults", "StandardButton")
    Save = _enum(QDialogButtonBox, "Save", "StandardButton")


class QFrameCompat:
    Box = _enum(QFrame, "Box", "Shape")
    HLine = _enum(QFrame, "HLine", "Shape")
    NoFrame = _enum(QFrame, "NoFrame", "Shape")
    Plain = _enum(QFrame, "Plain", "Shadow")
    Sunken = _enum(QFrame, "Sunken", "Shadow")


class QHeaderViewCompat:
    ResizeToContents = _enum(QHeaderView, "ResizeToContents", "ResizeMode")
    Stretch = _enum(QHeaderView, "Stretch", "ResizeMode")


class QIconCompat:
    Active = _enum(QIcon, "Active", "Mode")
    Disabled = _enum(QIcon, "Disabled", "Mode")
    Normal = _enum(QIcon, "Normal", "Mode")
    Off = _enum(QIcon, "Off", "State")
    On = _enum(QIcon, "On", "State")
    Selected = _enum(QIcon, "Selected", "Mode")


class QLineEditCompat:
    Password = _enum(QLineEdit, "Password", "EchoMode")


class QMessageBoxCompat:
    No = _enum(QMessageBox, "No", "StandardButton")
    Yes = _enum(QMessageBox, "Yes", "StandardButton")


class QPainterCompat:
    Antialiasing = _enum(QPainter, "Antialiasing", "RenderHint")
    CompositionMode_SourceIn = _enum(
        QPainter,
        "CompositionMode_SourceIn",
        "CompositionMode",
    )
    SmoothPixmapTransform = _enum(
        QPainter,
        "SmoothPixmapTransform",
        "RenderHint",
    )


class QSizePolicyCompat:
    Expanding = _enum(QSizePolicy, "Expanding", "Policy")
    Fixed = _enum(QSizePolicy, "Fixed", "Policy")
    Minimum = _enum(QSizePolicy, "Minimum", "Policy")
    Preferred = _enum(QSizePolicy, "Preferred", "Policy")


def unwrap_qt_type(value):
    while hasattr(value, "_base"):
        value = value._base
    return value
