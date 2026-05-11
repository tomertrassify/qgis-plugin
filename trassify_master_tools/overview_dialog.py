from __future__ import annotations

from html import escape

from qgis.PyQt.QtCore import QEasingCurve, QSize, Qt, QTimer, QVariantAnimation
from qgis.PyQt.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .settings_dialog import MasterSettingsWidget


class AnimatedSidebarButton(QPushButton):
    def __init__(self, label, icon_factory, parent=None):
        super().__init__(label, parent)
        self._icon_factory = icon_factory
        self._progress = 0.0
        self._hovered = False
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(140)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._on_animation_value_changed)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.toggled.connect(self._sync_visual_state)
        self._apply_visual_state()

    def enterEvent(self, event):
        self._hovered = True
        self._sync_visual_state()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._sync_visual_state()
        super().leaveEvent(event)

    def _target_progress(self):
        return 1.0 if (self.isChecked() or self._hovered) else 0.0

    def _sync_visual_state(self):
        target = self._target_progress()
        if abs(self._progress - target) < 0.001:
            self._progress = target
            self._apply_visual_state()
            return
        self._animation.stop()
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(target)
        self._animation.start()

    def _on_animation_value_changed(self, value):
        self._progress = float(value)
        self._apply_visual_state()

    def _apply_visual_state(self):
        background = self._blend_color(QColor("#050505"), QColor("#ffffff"), self._progress)
        foreground = self._blend_color(QColor("#ffffff"), QColor("#111111"), self._progress)
        border = self._blend_color(QColor("#1f1f1f"), QColor("#d9d9d4"), self._progress)
        self.setStyleSheet(
            (
                "QPushButton {"
                f"background: {background.name()};"
                f"color: {foreground.name()};"
                "border: none;"
                f"border-top: 1px solid {border.name()};"
                "text-align: left;"
                "padding: 0 14px 0 16px;"
                "font-size: 11px;"
                "font-weight: 500;"
                "}"
            )
        )
        self.setIcon(self._icon_factory(foreground))

    @staticmethod
    def _blend_color(start, end, progress):
        progress = max(0.0, min(1.0, float(progress)))
        return QColor(
            int(round(start.red() + (end.red() - start.red()) * progress)),
            int(round(start.green() + (end.green() - start.green()) * progress)),
            int(round(start.blue() + (end.blue() - start.blue()) * progress)),
        )


class MasterOverviewDialog(QDialog):
    FILTERS = (
        ("all", "overview.filter.all", "PhPuzzlePiece.svg"),
        ("installed", "overview.filter.installed", "IcOutlineLibraryAddCheck.svg"),
        ("not_installed", "overview.filter.not_installed", "IcOutlineLibraryCross.svg"),
        ("background", "overview.filter.background", "PhSelectionBackground.svg"),
        ("experimental", "overview.filter.experimental", "IcOutlineScience.svg"),
        ("favorites", "overview.filter.favorites", "IcBaselineStarBorder.svg"),
        ("other", "overview.filter.other", "PhPuzzlePiece.svg"),
    )

    def __init__(self, plugin_controller, parent=None):
        super().__init__(parent)
        self.plugin_controller = plugin_controller
        self._rows_by_key = {}
        self._all_rows = []
        self.auth_icon_path = self.plugin_controller.plugin_dir / "icon.svg"
        self.auth_hero_path = self.plugin_controller.plugin_dir / "assets" / "nextcloud_login_hero.png"
        self.auth_logo_path = self.plugin_controller.plugin_dir / "assets" / "trassify-logo.png"
        self._catalog_default_size = QSize(1260, 780)
        self._catalog_min_size = QSize(1080, 680)
        self._auth_default_size = QSize(372, 482)
        self._auth_min_size = QSize(340, 438)
        self._dialog_mode = None
        self._settings_active = False
        self._language_switchers = []

        self.setObjectName("masterOverviewDialog")
        self.setWindowTitle(self._tr("overview.window.catalog_plain"))
        self.setWindowIcon(QIcon(str(plugin_controller.plugin_dir / "icon.svg")))
        self.resize(self._catalog_default_size)
        self.setMinimumSize(self._catalog_min_size)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.page_stack = QStackedWidget(self)
        self.page_stack.setObjectName("overviewPageStack")
        root_layout.addWidget(self.page_stack, 1)

        self.auth_page = QWidget(self.page_stack)
        self.auth_page.setObjectName("authPage")
        auth_page_layout = QVBoxLayout(self.auth_page)
        auth_page_layout.setContentsMargins(10, 10, 10, 0)
        auth_page_layout.setSpacing(0)
        auth_header_layout = QHBoxLayout()
        auth_header_layout.setContentsMargins(0, 0, 0, 0)
        auth_header_layout.setSpacing(0)
        auth_header_layout.addStretch(1)
        self.auth_language_switcher = self._create_language_switcher(self.auth_page)
        auth_header_layout.addWidget(self.auth_language_switcher["widget"], 0, Qt.AlignTop | Qt.AlignRight)
        auth_page_layout.addLayout(auth_header_layout)
        self.auth_widgets = self._create_auth_card(self.auth_page, compact=True)
        auth_page_layout.addWidget(self.auth_widgets["frame"], 1)
        self.page_stack.addWidget(self.auth_page)

        self.catalog_page = QWidget(self.page_stack)
        self.catalog_page.setObjectName("catalogPage")
        layout = QHBoxLayout(self.catalog_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar_frame = QFrame(self.catalog_page)
        self.sidebar_frame.setObjectName("sidebarFrame")
        self.sidebar_frame.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(self.sidebar_frame)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        self.filter_list = QListWidget(self.sidebar_frame)
        self.filter_list.setObjectName("filterList")
        self.filter_list.setFrameShape(QFrame.Box)
        self.filter_list.setLineWidth(0)
        self.filter_list.setSpacing(0)
        self.filter_list.setIconSize(QSize(18, 18))
        self.filter_list.setUniformItemSizes(True)
        self.filter_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.filter_list.currentItemChanged.connect(self._handle_filter_selection_changed)
        sidebar_layout.addWidget(self.filter_list, 1)

        self.settings_nav_button = AnimatedSidebarButton(
            self._tr("overview.sidebar.settings"),
            lambda color: self._single_color_sidebar_icon("CarbonSettings.svg", color, 18),
            self.sidebar_frame,
        )
        self.settings_nav_button.setObjectName("sidebarSettingsButton")
        self.settings_nav_button.setCheckable(True)
        self.settings_nav_button.setIconSize(QSize(18, 18))
        self.settings_nav_button.setFixedHeight(58)
        self.settings_nav_button.clicked.connect(self._open_settings_from_sidebar)
        sidebar_layout.addWidget(self.settings_nav_button)
        layout.addWidget(self.sidebar_frame)

        self.workspace_frame = QFrame(self.catalog_page)
        self.workspace_frame.setObjectName("workspaceFrame")
        workspace_layout = QVBoxLayout(self.workspace_frame)
        workspace_layout.setContentsMargins(12, 12, 12, 12)
        workspace_layout.setSpacing(10)
        layout.addWidget(self.workspace_frame, 1)

        self.header_frame = QFrame(self.workspace_frame)
        self.header_frame.setObjectName("headerFrame")
        header_layout = QVBoxLayout(self.header_frame)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        workspace_layout.addWidget(self.header_frame)

        header_top_layout = QHBoxLayout()
        header_top_layout.setSpacing(12)
        header_layout.addLayout(header_top_layout)

        header_text_layout = QVBoxLayout()
        header_text_layout.setSpacing(4)
        header_top_layout.addLayout(header_text_layout, 1)

        self.workspace_title_label = QLabel(self._tr("overview.header.catalog_title"), self.header_frame)
        self.workspace_title_label.setObjectName("workspaceTitleLabel")
        header_text_layout.addWidget(self.workspace_title_label)

        self.workspace_subtitle_label = QLabel(self._tr("overview.header.catalog_subtitle"), self.header_frame)
        self.workspace_subtitle_label.setObjectName("workspaceSubtitleLabel")
        self.workspace_subtitle_label.setWordWrap(True)
        header_text_layout.addWidget(self.workspace_subtitle_label)

        self.catalog_count_badge = QLabel("", self.header_frame)
        self.catalog_count_badge.setObjectName("catalogCountBadge")
        self.catalog_count_badge.setAlignment(Qt.AlignCenter)
        header_top_layout.addWidget(self.catalog_count_badge, 0, Qt.AlignTop)

        self.catalog_language_switcher = self._create_language_switcher(self.header_frame)
        header_top_layout.addWidget(self.catalog_language_switcher["widget"], 0, Qt.AlignTop | Qt.AlignRight)

        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(8)
        header_layout.addLayout(controls_layout)

        self.search_field = QLineEdit(self.header_frame)
        self.search_field.setObjectName("searchField")
        self.search_field.setPlaceholderText(self._tr("overview.search_placeholder"))
        self.search_field.setClearButtonEnabled(True)
        self.search_field.textChanged.connect(self._apply_filters)
        controls_layout.addWidget(self.search_field, 1)

        self.access_gate_widgets = self._create_auth_card(self.workspace_frame, compact=False)
        self.access_gate_frame = self.access_gate_widgets["frame"]
        workspace_layout.addWidget(self.access_gate_frame, 0, Qt.AlignHCenter)

        self.settings_frame = QFrame(self.workspace_frame)
        self.settings_frame.setObjectName("settingsFrame")
        settings_layout = QVBoxLayout(self.settings_frame)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(12)

        self.settings_status_label = QLabel("", self.settings_frame)
        self.settings_status_label.setObjectName("settingsStatusLabel")
        self.settings_status_label.setWordWrap(True)
        self.settings_status_label.hide()
        settings_layout.addWidget(self.settings_status_label)

        self.settings_widget = MasterSettingsWidget(self.plugin_controller, self.settings_frame)
        settings_layout.addWidget(self.settings_widget, 1)

        settings_actions_layout = QHBoxLayout()
        settings_actions_layout.setContentsMargins(0, 0, 0, 0)
        settings_actions_layout.setSpacing(8)
        settings_layout.addLayout(settings_actions_layout)

        self.settings_save_button = QPushButton(self._tr("overview.settings.save"), self.settings_frame)
        self.settings_save_button.setObjectName("primaryButton")
        self.settings_save_button.clicked.connect(self._save_settings_view)
        settings_actions_layout.addWidget(self.settings_save_button)

        self.settings_restore_button = QPushButton(self._tr("overview.settings.restore"), self.settings_frame)
        self.settings_restore_button.setObjectName("subtleButton")
        self.settings_restore_button.clicked.connect(self._restore_settings_view)
        settings_actions_layout.addWidget(self.settings_restore_button)

        settings_actions_layout.addStretch(1)

        self.settings_reload_button = QPushButton(self._tr("overview.settings.reload"), self.settings_frame)
        self.settings_reload_button.setObjectName("subtleButton")
        self.settings_reload_button.clicked.connect(self._refresh_catalog_and_view)
        settings_actions_layout.addWidget(self.settings_reload_button)

        self.settings_logout_button = QPushButton(self._tr("overview.settings.logout"), self.settings_frame)
        self.settings_logout_button.setObjectName("subtleButton")
        self.settings_logout_button.clicked.connect(self._remove_catalog_login)
        settings_actions_layout.addWidget(self.settings_logout_button)

        workspace_layout.addWidget(self.settings_frame, 1)

        self.content_splitter = QSplitter(Qt.Horizontal, self.workspace_frame)
        self.content_splitter.setObjectName("contentSplitter")
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(1)
        workspace_layout.addWidget(self.content_splitter, 1)

        module_panel = QFrame(self.content_splitter)
        module_panel.setObjectName("modulePanel")
        module_layout = QVBoxLayout(module_panel)
        module_layout.setContentsMargins(0, 0, 0, 0)
        module_layout.setSpacing(8)

        module_header_layout = QHBoxLayout()
        module_header_layout.setSpacing(10)
        module_layout.addLayout(module_header_layout)

        self.module_section_label = QLabel(self._tr("overview.section.all_modules"), module_panel)
        self.module_section_label.setObjectName("sectionTitleLabel")
        module_header_layout.addWidget(self.module_section_label, 1)

        self.results_summary_label = QLabel("", module_panel)
        self.results_summary_label.setObjectName("resultsSummaryLabel")
        self.results_summary_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        module_header_layout.addWidget(self.results_summary_label)

        self.module_list = QTreeWidget(module_panel)
        self.module_list.setObjectName("moduleList")
        self.module_list.setColumnCount(2)
        self.module_list.setHeaderHidden(True)
        self.module_list.setRootIsDecorated(False)
        self.module_list.setIndentation(0)
        self.module_list.setAlternatingRowColors(True)
        self.module_list.setUniformRowHeights(True)
        self.module_list.setFrameShape(QFrame.NoFrame)
        self.module_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.module_list.setIconSize(QSize(20, 20))
        self.module_list.header().setStretchLastSection(False)
        self.module_list.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.module_list.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.module_list.itemSelectionChanged.connect(self._sync_details)
        self.module_list.itemDoubleClicked.connect(self._handle_item_double_click)
        module_layout.addWidget(self.module_list, 1)
        self.content_splitter.addWidget(module_panel)

        detail_panel = QFrame(self.content_splitter)
        detail_panel.setObjectName("detailPanel")
        detail_panel.setMinimumWidth(420)
        detail_panel_layout = QVBoxLayout(detail_panel)
        detail_panel_layout.setContentsMargins(0, 0, 0, 0)
        detail_panel_layout.setSpacing(0)

        self.detail_scroll_area = QScrollArea(detail_panel)
        self.detail_scroll_area.setObjectName("detailScrollArea")
        self.detail_scroll_area.setWidgetResizable(True)
        self.detail_scroll_area.setFrameShape(QFrame.NoFrame)
        self.detail_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.detail_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.detail_scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        detail_panel_layout.addWidget(self.detail_scroll_area)

        self.detail_content = QWidget(self.detail_scroll_area)
        self.detail_content.setObjectName("detailContent")
        self.detail_scroll_area.setWidget(self.detail_content)

        detail_layout = QVBoxLayout(self.detail_content)
        detail_layout.setContentsMargins(12, 12, 12, 12)
        detail_layout.setSpacing(12)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)
        detail_layout.addLayout(header_layout)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(6)
        header_layout.addLayout(title_layout, 1)

        self.title_label = QLabel(self.detail_content)
        self.title_label.setObjectName("detailTitleLabel")
        title_font = QFont(self.font())
        title_font.setPointSize(title_font.pointSize() + 12)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setWordWrap(True)
        title_layout.addWidget(self.title_label)

        self.description_label = QLabel(self.detail_content)
        self.description_label.setObjectName("detailDescriptionLabel")
        description_font = QFont(self.font())
        description_font.setPointSize(description_font.pointSize() + 3)
        description_font.setBold(True)
        self.description_label.setFont(description_font)
        self.description_label.setWordWrap(True)
        title_layout.addWidget(self.description_label)

        self.status_label = QLabel(self.detail_content)
        self.status_label.setObjectName("detailStatusLabel")
        self.status_label.setWordWrap(True)
        title_layout.addWidget(self.status_label)

        self.icon_label = QLabel(self.detail_content)
        self.icon_label.setFixedSize(88, 88)
        self.icon_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        header_layout.addWidget(self.icon_label, 0, Qt.AlignTop)

        self.about_label = QLabel(self.detail_content)
        self.about_label.setObjectName("detailAboutLabel")
        self.about_label.setWordWrap(True)
        self.about_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        detail_layout.addWidget(self.about_label)

        separator = QFrame(self.detail_content)
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        detail_layout.addWidget(separator)

        self.metadata_form = QFormLayout()
        self.metadata_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.metadata_form.setFormAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.metadata_form.setHorizontalSpacing(16)
        self.metadata_form.setVerticalSpacing(10)
        detail_layout.addLayout(self.metadata_form)

        self.category_value = self._create_value_label(self.detail_content)
        self.type_value = self._create_value_label(self.detail_content)
        self.favorite_value = self._create_value_label(self.detail_content)
        self.package_value = self._create_value_label(self.detail_content)
        self.management_value = self._create_value_label(self.detail_content)
        self.release_value = self._create_value_label(self.detail_content)
        self.tags_value = self._create_value_label(self.detail_content)
        self.author_value = self._create_value_label(self.detail_content)
        self.version_value = self._create_value_label(self.detail_content)
        self.links_value = self._create_value_label(self.detail_content, rich_text=True)

        self.metadata_form.addRow(self._tr("overview.metadata.category"), self.category_value)
        self.metadata_form.addRow(self._tr("overview.metadata.type"), self.type_value)
        self.metadata_form.addRow(self._tr("overview.metadata.favorite"), self.favorite_value)
        self.metadata_form.addRow(self._tr("overview.metadata.package"), self.package_value)
        self.metadata_form.addRow(self._tr("overview.metadata.management"), self.management_value)
        self.metadata_form.addRow(self._tr("overview.metadata.release"), self.release_value)
        self.metadata_form.addRow(self._tr("overview.metadata.tags"), self.tags_value)
        self.metadata_form.addRow(self._tr("overview.metadata.author"), self.author_value)
        self.metadata_form.addRow(self._tr("overview.metadata.version"), self.version_value)
        self.metadata_form.addRow(self._tr("overview.metadata.links"), self.links_value)

        detail_layout.addStretch(1)
        self.content_splitter.addWidget(detail_panel)
        self.content_splitter.setStretchFactor(0, 5)
        self.content_splitter.setStretchFactor(1, 6)

        self.footer_frame = QFrame(self.workspace_frame)
        self.footer_frame.setObjectName("footerFrame")
        actions_layout = QHBoxLayout(self.footer_frame)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        workspace_layout.addWidget(self.footer_frame)
        button_height = 30

        self.favorite_button = QToolButton(self.footer_frame)
        self.favorite_button.setObjectName("favoriteButton")
        self.favorite_button.setText("")
        self.favorite_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.favorite_button.setIconSize(QSize(18, 18))
        self.favorite_button.setFixedSize(button_height, button_height)
        self.favorite_button.clicked.connect(self._toggle_selected_favorite)
        actions_layout.addWidget(self.favorite_button)

        self.open_button = QPushButton(self._tr("overview.action.open"), self.footer_frame)
        self.open_button.setObjectName("subtleButton")
        self.open_button.setFixedHeight(button_height)
        self.open_button.clicked.connect(self._open_selected_module)
        self.open_button.hide()
        actions_layout.addWidget(self.open_button)

        self.primary_button = QPushButton(self._tr("overview.action.install"), self.footer_frame)
        self.primary_button.setObjectName("primaryButton")
        self.primary_button.setFixedHeight(button_height)
        self.primary_button.clicked.connect(self._run_primary_action)
        actions_layout.addWidget(self.primary_button)

        self.secondary_button = QPushButton(self._tr("overview.action.remove"), self.footer_frame)
        self.secondary_button.setObjectName("secondaryButton")
        self.secondary_button.setFixedHeight(button_height)
        self.secondary_button.clicked.connect(self._run_secondary_action)
        actions_layout.addWidget(self.secondary_button)

        actions_layout.addStretch(1)

        button_box = QDialogButtonBox(QDialogButtonBox.Close, self.footer_frame)
        button_box.setObjectName("dialogButtonBox")
        button_box.rejected.connect(self.reject)
        close_button = button_box.button(QDialogButtonBox.Close)
        if close_button is not None:
            close_button.setObjectName("subtleButton")
            close_button.setFixedHeight(button_height)
            close_button.setText(self._tr("overview.action.close"))
        actions_layout.addWidget(button_box)

        self.page_stack.addWidget(self.catalog_page)
        self._apply_window_styling()
        self._apply_language_to_static_widgets()
        self.refresh()

    def _create_auth_card(self, parent, compact):
        if compact:
            return self._create_compact_auth_card(parent)
        return self._create_access_gate_card(parent)

    def _create_compact_auth_card(self, parent):
        frame = QFrame(parent)
        frame.setObjectName("authDialogFrame")
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(16, 10, 16, 14)
        frame_layout.setSpacing(0)
        frame_layout.addStretch(1)

        dialog_card = QFrame(frame)
        dialog_card.setObjectName("authDialogCard")
        dialog_card.setFixedWidth(320)
        dialog_card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        frame_layout.addWidget(dialog_card, 0, Qt.AlignHCenter | Qt.AlignVCenter)
        frame_layout.addStretch(1)

        shadow = QGraphicsDropShadowEffect(dialog_card)
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 1)
        shadow.setColor(QColor(0, 0, 0, 10))
        dialog_card.setGraphicsEffect(shadow)

        dialog_layout = QVBoxLayout(dialog_card)
        dialog_layout.setContentsMargins(22, 24, 22, 18)
        dialog_layout.setSpacing(0)

        content_column = QWidget(dialog_card)
        content_column.setObjectName("authDialogColumn")
        content_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        dialog_layout.addWidget(content_column)

        content_layout = QVBoxLayout(content_column)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        icon_label = QLabel(content_column)
        icon_label.setObjectName("authIconBadge")
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setFixedSize(44, 44)
        icon_pixmap = self._contain_pixmap(self.auth_icon_path, 44, 44)
        if not icon_pixmap.isNull():
            icon_label.setPixmap(icon_pixmap)
        content_layout.addWidget(icon_label, 0, Qt.AlignHCenter)

        content_layout.addSpacing(14)

        title_label = QLabel(self._tr("overview.auth.dialog.title"), content_column)
        title_label.setObjectName("authDialogTitleLabel")
        title_label.setWordWrap(True)
        title_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(title_label)

        subtitle_label = QLabel(
            self._tr("overview.auth.dialog.subtitle"),
            content_column,
        )
        subtitle_label.setObjectName("authDialogSubtitleLabel")
        subtitle_label.setWordWrap(True)
        subtitle_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(subtitle_label)

        content_layout.addSpacing(30)
        body_width = 244

        access_label = QLabel(self._tr("overview.auth.dialog.access"), content_column)
        access_label.setObjectName("authPermissionCaptionLabel")
        access_label.setFixedWidth(body_width)
        access_label.setWordWrap(True)
        content_layout.addWidget(access_label, 0, Qt.AlignHCenter)

        content_layout.addSpacing(10)

        permission_card = QFrame(content_column)
        permission_card.setObjectName("authPermissionCard")
        permission_card.setFixedWidth(body_width)
        permission_layout = QVBoxLayout(permission_card)
        permission_layout.setContentsMargins(18, 14, 18, 14)
        permission_layout.setSpacing(0)
        content_layout.addWidget(permission_card, 0, Qt.AlignHCenter)

        permission_header_layout = QHBoxLayout()
        permission_header_layout.setContentsMargins(0, 0, 0, 0)
        permission_header_layout.setSpacing(12)
        permission_layout.addLayout(permission_header_layout)

        permission_check_label = QLabel("✓", permission_card)
        permission_check_label.setObjectName("authPermissionCheckLabel")
        permission_header_layout.addWidget(permission_check_label, 0, Qt.AlignTop)

        permission_title_label = QLabel(self._tr("overview.auth.dialog.permission_title"), permission_card)
        permission_title_label.setObjectName("authPermissionTitleLabel")
        permission_header_layout.addWidget(permission_title_label, 1)

        permission_layout.addSpacing(10)

        permission_item_labels = []
        for text in (
            self._tr("overview.auth.dialog.permission_item_account"),
            self._tr("overview.auth.dialog.permission_item_email"),
            self._tr("overview.auth.dialog.permission_item_password"),
        ):
            bullet_label = QLabel(f"•    {text}", permission_card)
            bullet_label.setObjectName("authPermissionItemLabel")
            bullet_label.setWordWrap(True)
            permission_layout.addWidget(bullet_label)
            permission_layout.addSpacing(7)
            permission_item_labels.append(bullet_label)

        permission_layout.addSpacing(2)

        separator = QFrame(permission_card)
        separator.setObjectName("authPermissionSeparator")
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Plain)
        permission_layout.addWidget(separator)

        permission_layout.addSpacing(10)

        legal_label = QLabel(self._tr("overview.auth.dialog.legal"), permission_card)
        legal_label.setObjectName("authPermissionFootnoteLabel")
        legal_label.setWordWrap(True)
        legal_label.setTextFormat(Qt.RichText)
        permission_layout.addWidget(legal_label)

        status_label = QLabel("", content_column)
        status_label.setObjectName("authDialogStatusLabel")
        status_label.setWordWrap(True)
        status_label.setTextFormat(Qt.PlainText)
        status_label.setAlignment(Qt.AlignCenter)
        status_label.setFixedWidth(body_width)
        content_layout.addSpacing(12)
        content_layout.addWidget(status_label, 0, Qt.AlignHCenter)

        content_layout.addSpacing(14)

        buttons_widget = QWidget(content_column)
        buttons_widget.setFixedWidth(body_width)
        buttons_layout = QHBoxLayout(buttons_widget)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(8)
        content_layout.addWidget(buttons_widget, 0, Qt.AlignHCenter)

        cancel_button = QPushButton(self._tr("overview.auth.dialog.cancel"), content_column)
        cancel_button.setObjectName("authCancelButton")
        cancel_button.setFixedHeight(34)
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_button, 1)

        login_button = QPushButton(self._tr("overview.auth.dialog.authorize"), content_column)
        login_button.setObjectName("authAuthorizeButton")
        login_button.setFixedHeight(34)
        login_button.setAutoDefault(True)
        login_button.setDefault(True)
        login_button.clicked.connect(self._start_catalog_login)
        buttons_layout.addWidget(login_button, 1)

        content_layout.addSpacing(16)

        redirect_label = QLabel("", content_column)
        redirect_label.setObjectName("authRedirectLabel")
        redirect_label.setFixedWidth(body_width)
        redirect_label.setWordWrap(True)
        redirect_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(redirect_label, 0, Qt.AlignHCenter)

        return {
            "frame": frame,
            "compact": True,
            "title": title_label,
            "subtitle": subtitle_label,
            "access": access_label,
            "permission_title": permission_title_label,
            "permission_items": permission_item_labels,
            "legal": legal_label,
            "status": status_label,
            "login": login_button,
            "cancel": cancel_button,
            "redirect": redirect_label,
        }

    def _create_access_gate_card(self, parent):
        frame = QFrame(parent)
        frame.setObjectName("authCard")
        frame.setFixedWidth(566)
        frame.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        card_layout = QVBoxLayout(frame)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        hero_image = QLabel(frame)
        hero_image.setObjectName("authHeroImage")
        hero_image.setFixedHeight(150)
        hero_image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        hero_image.setAlignment(Qt.AlignCenter)
        hero_image.setMargin(0)
        card_layout.addWidget(hero_image)

        content_widget = QWidget(frame)
        content_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(24, 20, 24, 24)
        content_layout.setSpacing(12)

        logo_label = QLabel(content_widget)
        logo_label.setObjectName("authLogoLabel")
        logo_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(logo_label, 0, Qt.AlignHCenter)

        title_label = QLabel(self._tr("overview.auth.gate.welcome_title"), content_widget)
        title_label.setObjectName("authTitleLabel")
        title_label.setWordWrap(True)
        title_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(title_label)

        intro_label = QLabel(
            self._tr("overview.auth.gate.welcome_intro"),
            content_widget,
        )
        intro_label.setObjectName("authIntroLabel")
        intro_label.setWordWrap(True)
        intro_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(intro_label)

        status_label = QLabel("", content_widget)
        status_label.setObjectName("authStatusCardLabel")
        status_label.setWordWrap(True)
        status_label.setTextFormat(Qt.PlainText)
        status_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(status_label)

        account_label = QLabel("", content_widget)
        account_label.setObjectName("authAccountLabel")
        account_label.setWordWrap(True)
        account_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(account_label)

        primary_row = QHBoxLayout()
        primary_row.setSpacing(10)
        primary_row.addStretch(1)
        content_layout.addLayout(primary_row)

        login_button = QPushButton(self._tr("overview.auth.gate.login"), content_widget)
        login_button.setObjectName("authPrimaryButton")
        login_button.setFixedWidth(132)
        login_button.setFixedHeight(36)
        login_button.setAutoDefault(True)
        login_button.setDefault(True)
        login_button.clicked.connect(self._start_catalog_login)
        primary_row.addWidget(login_button)
        primary_row.addStretch(1)

        footer_row = QHBoxLayout()
        footer_row.setSpacing(0)
        footer_row.addStretch(1)
        content_layout.addLayout(footer_row)

        refresh_button = QPushButton(self._tr("overview.auth.gate.refresh"), content_widget)
        refresh_button.setObjectName("authTextButton")
        refresh_button.setFlat(True)
        refresh_button.clicked.connect(self._refresh_catalog_login)
        footer_row.addWidget(refresh_button)

        logout_button = QPushButton(self._tr("overview.auth.gate.logout"), content_widget)
        logout_button.setObjectName("authTextButton")
        logout_button.setFlat(True)
        logout_button.clicked.connect(self._remove_catalog_login)
        footer_row.addWidget(logout_button)
        footer_row.addStretch(1)

        card_layout.addWidget(content_widget)

        return {
            "frame": frame,
            "compact": False,
            "hero": hero_image,
            "logo": logo_label,
            "title": title_label,
            "intro": intro_label,
            "status": status_label,
            "account": account_label,
            "login": login_button,
            "refresh": refresh_button,
            "logout": logout_button,
        }

    def _contain_pixmap(self, path, width, height):
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return QPixmap()
        return pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _tinted_svg_pixmap(self, asset_name, color, size):
        svg_path = self.plugin_controller.plugin_dir / "assets" / asset_name
        try:
            svg_text = svg_path.read_text(encoding="utf-8")
        except OSError:
            return QPixmap()

        tint = color if isinstance(color, QColor) else QColor(str(color))
        pixmap = self._svg_pixmap_from_text(svg_text, size)
        if pixmap.isNull():
            return QPixmap()

        if "currentColor" in svg_text:
            tinted_pixmap = self._svg_pixmap_from_text(
                svg_text.replace("currentColor", tint.name()),
                size,
            )
            if not tinted_pixmap.isNull():
                return tinted_pixmap

        tinted = QPixmap(pixmap.size())
        tinted.fill(Qt.transparent)
        painter = QPainter(tinted)
        painter.drawPixmap(0, 0, pixmap)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(tinted.rect(), tint)
        painter.end()
        tinted.setDevicePixelRatio(pixmap.devicePixelRatio())
        return tinted

    def _svg_pixmap(self, asset_name, size):
        svg_path = self.plugin_controller.plugin_dir / "assets" / asset_name
        try:
            svg_text = svg_path.read_text(encoding="utf-8")
        except OSError:
            return QPixmap()
        return self._svg_pixmap_from_text(svg_text, size)

    def _svg_pixmap_from_text(self, svg_text, size):
        pixmap = QPixmap()
        if not pixmap.loadFromData(svg_text.encode("utf-8"), "SVG"):
            return QPixmap()

        device_pixel_ratio = max(2.0, float(self.devicePixelRatioF()))
        target_size = max(1, int(round(size * device_pixel_ratio)))
        scaled = pixmap.scaled(
            target_size,
            target_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(device_pixel_ratio)
        return scaled

    def _sidebar_icon(self, asset_name, size=20):
        icon = QIcon()
        normal = self._tinted_svg_pixmap(asset_name, QColor("#f5f5f3"), size)
        selected = self._tinted_svg_pixmap(asset_name, QColor("#111111"), size)
        disabled = self._tinted_svg_pixmap(asset_name, QColor("#999999"), size)
        if not normal.isNull():
            icon.addPixmap(normal, QIcon.Normal, QIcon.Off)
            icon.addPixmap(normal, QIcon.Active, QIcon.Off)
        if not selected.isNull():
            icon.addPixmap(selected, QIcon.Selected, QIcon.Off)
            icon.addPixmap(selected, QIcon.Normal, QIcon.On)
            icon.addPixmap(selected, QIcon.Active, QIcon.On)
        if not disabled.isNull():
            icon.addPixmap(disabled, QIcon.Disabled, QIcon.Off)
        return icon

    def _single_color_sidebar_icon(self, asset_name, color, size=18):
        icon = QIcon()
        pixmap = self._tinted_svg_pixmap(asset_name, color, size)
        if not pixmap.isNull():
            icon.addPixmap(pixmap, QIcon.Normal, QIcon.Off)
            icon.addPixmap(pixmap, QIcon.Active, QIcon.Off)
            icon.addPixmap(pixmap, QIcon.Selected, QIcon.Off)
            icon.addPixmap(pixmap, QIcon.Normal, QIcon.On)
        return icon

    def _language_icon_asset(self, language_code):
        return {
            "de": "de.svg",
            "en": "gb.svg",
        }.get(language_code, f"{language_code}.svg")

    def _create_language_switcher(self, parent):
        frame = QFrame(parent)
        frame.setObjectName("languageSwitcherFrame")

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        buttons = {"widget": frame}
        for language_code in ("de", "en"):
            button = QToolButton(frame)
            button.setObjectName("languageSwitcherButton")
            button.setCursor(Qt.PointingHandCursor)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setIcon(
                QIcon(self._svg_pixmap(self._language_icon_asset(language_code), 18))
            )
            button.setIconSize(QSize(18, 18))
            button.setFixedSize(28, 24)
            button.clicked.connect(
                lambda _checked=False, lang=language_code: self._set_language(lang)
            )
            layout.addWidget(button)
            buttons[language_code] = button

        self._language_switchers.append(buttons)
        return buttons

    def _sync_language_switchers(self):
        current_language = self._current_language()
        for switcher in self._language_switchers:
            for language_code in ("de", "en"):
                button = switcher.get(language_code)
                if button is None:
                    continue
                button.blockSignals(True)
                button.setChecked(language_code == current_language)
                button.setToolTip(self._tr(f"language.{language_code}"))
                button.blockSignals(False)

    def _apply_language_to_static_widgets(self):
        self.settings_nav_button.setText(self._tr("overview.sidebar.settings"))
        self.search_field.setPlaceholderText(self._tr("overview.search_placeholder"))
        self.module_section_label.setText(self._tr("overview.section.all_modules"))
        self.settings_save_button.setText(self._tr("overview.settings.save"))
        self.settings_restore_button.setText(self._tr("overview.settings.restore"))
        self.settings_reload_button.setText(self._tr("overview.settings.reload"))
        self.settings_logout_button.setText(self._tr("overview.settings.logout"))
        self.open_button.setText(self._tr("overview.action.open"))
        self.primary_button.setText(self._tr("overview.action.install"))
        self.secondary_button.setText(self._tr("overview.action.remove"))

        metadata_labels = (
            (self.category_value, "overview.metadata.category"),
            (self.type_value, "overview.metadata.type"),
            (self.favorite_value, "overview.metadata.favorite"),
            (self.package_value, "overview.metadata.package"),
            (self.management_value, "overview.metadata.management"),
            (self.release_value, "overview.metadata.release"),
            (self.tags_value, "overview.metadata.tags"),
            (self.author_value, "overview.metadata.author"),
            (self.version_value, "overview.metadata.version"),
            (self.links_value, "overview.metadata.links"),
        )
        for field, key in metadata_labels:
            label = self.metadata_form.labelForField(field)
            if label is not None:
                label.setText(self._tr(key))

        close_button = self.findChild(QDialogButtonBox, "dialogButtonBox")
        if close_button is not None:
            button = close_button.button(QDialogButtonBox.Close)
            if button is not None:
                button.setText(self._tr("overview.action.close"))

        self.settings_widget.apply_language()
        self._sync_language_switchers()

    def _set_language(self, language):
        self.plugin_controller.set_ui_language(language)
        self.refresh()

    def _current_language(self):
        return self.plugin_controller.get_ui_language()

    def _tr(self, key, **kwargs):
        return self.plugin_controller.tr(key, **kwargs)

    def _cover_pixmap(self, path, width, height):
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return QPixmap()
        scaled = pixmap.scaled(width, height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        offset_x = max(0, (scaled.width() - width) // 2)
        offset_y = max(0, (scaled.height() - height) // 2)
        return scaled.copy(offset_x, offset_y, width, height)

    def _set_dialog_mode(self, mode):
        if self._dialog_mode == mode:
            return
        self._dialog_mode = mode
        if mode == "auth":
            self.setMaximumSize(16777215, 16777215)
            self.setMinimumSize(self._auth_min_size)
            self.resize(self._auth_default_size)
            self._update_auth_artwork()
            return

        self.setMaximumSize(16777215, 16777215)
        self.setMinimumSize(self._catalog_min_size)
        if self.width() < self._catalog_min_size.width() or self.height() < self._catalog_min_size.height():
            self.resize(self._catalog_default_size)
        self._update_auth_artwork()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_auth_artwork()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._update_auth_artwork)
        QTimer.singleShot(25, self._update_auth_artwork)

    def _update_auth_artwork(self):
        hero_label = self.access_gate_widgets["hero"]
        hero_width = max(1, hero_label.width())
        hero_height = max(1, hero_label.height())
        hero_label.setPixmap(
            self._cover_pixmap(self.auth_hero_path, hero_width, hero_height)
        )

        self.access_gate_widgets["logo"].setPixmap(
            self._contain_pixmap(self.auth_logo_path, 210, 42)
        )

    def refresh(self):
        self._apply_language_to_static_widgets()
        self._sync_auth_page()
        if not self.plugin_controller.can_access_catalog():
            self._set_dialog_mode("auth")
            self.page_stack.setCurrentWidget(self.auth_page)
            self.setWindowTitle(self._tr("overview.window.auth"))
            return

        self._set_dialog_mode("catalog")
        current_item = self.module_list.currentItem()
        current_key = current_item.data(0, Qt.UserRole) if current_item is not None else None
        self._all_rows = sorted(
            self.plugin_controller.get_module_rows(),
            key=lambda row: row["label"].lower(),
        )
        self._rows_by_key = {
            row["key"]: row for row in self._all_rows
        }

        if not self._all_rows:
            self.page_stack.setCurrentWidget(self.catalog_page)
            self._set_catalog_access_state(False)
            self._sync_empty_catalog_gate()
            self.setWindowTitle(self._tr("overview.window.nextcloud"))
            return

        self.page_stack.setCurrentWidget(self.catalog_page)
        self._set_catalog_access_state(True)
        self._populate_filters()
        self._apply_filters(preferred_key=current_key)
        self.catalog_count_badge.setText(
            self._tr("overview.count_badge", count=len(self._all_rows))
        )
        if self._settings_active:
            self.setWindowTitle(self._tr("overview.window.settings"))
        else:
            self.setWindowTitle(self._tr("overview.window.catalog", count=len(self._all_rows)))

    def _sync_auth_page(self):
        status = self.plugin_controller.auth_status()
        detail = self.plugin_controller.auth_status_detail()
        display_name = self.plugin_controller.auth_display_name()
        groups = self.plugin_controller.auth_groups()
        has_saved_login = self.plugin_controller.has_saved_catalog_login()
        can_access = self.plugin_controller.can_access_catalog()
        shared_settings = self.plugin_controller.get_shared_settings()
        base_url = str(shared_settings.get("nextcloud_base_url", "") or "").strip()
        if base_url and not base_url.endswith("/"):
            base_url = f"{base_url}/"

        gate_intro = self._tr("overview.auth.gate.welcome_intro")

        if can_access:
            gate_title_text = self._tr("overview.auth.gate.connected_title")
            gate_intro_text = self._tr("overview.auth.gate.connected_intro")
        elif status == "authorizing":
            gate_title_text = self._tr("overview.auth.gate.authorizing_title")
            gate_intro_text = self._tr("overview.auth.gate.authorizing_intro")
        elif has_saved_login:
            gate_title_text = self._tr("overview.auth.gate.saved_title")
            gate_intro_text = self._tr("overview.auth.gate.saved_intro")
        else:
            gate_title_text = self._tr("overview.auth.gate.welcome_title")
            gate_intro_text = gate_intro

        if status == "authorizing":
            gate_login_text = self._tr("overview.auth.gate.browser_open")
        elif has_saved_login and not can_access:
            gate_login_text = self._tr("overview.auth.gate.relogin")
        elif can_access:
            gate_login_text = self._tr("overview.auth.gate.reauth")
        else:
            gate_login_text = self._tr("overview.auth.gate.login")

        if status == "authorizing":
            popup_status_text = self._tr("overview.auth.gate.compact_authorizing")
        elif detail:
            popup_status_text = detail.strip()
        elif has_saved_login and not can_access:
            popup_status_text = self._tr("overview.auth.gate.saved_login_notice")
        else:
            popup_status_text = ""

        self.auth_widgets["title"].setText(self._tr("overview.auth.dialog.title"))
        self.auth_widgets["subtitle"].setText(self._tr("overview.auth.dialog.subtitle"))
        self.auth_widgets["access"].setText(self._tr("overview.auth.dialog.access"))
        self.auth_widgets["permission_title"].setText(
            self._tr("overview.auth.dialog.permission_title")
        )
        permission_item_texts = (
            self._tr("overview.auth.dialog.permission_item_account"),
            self._tr("overview.auth.dialog.permission_item_email"),
            self._tr("overview.auth.dialog.permission_item_password"),
        )
        for label, text in zip(self.auth_widgets["permission_items"], permission_item_texts):
            label.setText(f"•    {text}")
        self.auth_widgets["legal"].setText(self._tr("overview.auth.dialog.legal"))
        self.auth_widgets["status"].setText(popup_status_text)
        self.auth_widgets["status"].setVisible(bool(popup_status_text))
        self.auth_widgets["redirect"].setText(
            self._tr(
                "overview.auth.dialog.redirect",
                url=base_url or "https://nextcloud.trassify.cloud/",
            )
        )
        self.auth_widgets["login"].setText(
            self._tr("overview.auth.dialog.authorizing")
            if status == "authorizing"
            else self._tr("overview.auth.dialog.authorize")
        )
        self.auth_widgets["login"].setEnabled(status != "authorizing")
        self.auth_widgets["cancel"].setEnabled(status != "authorizing")
        self.auth_widgets["cancel"].setText(self._tr("overview.auth.dialog.cancel"))

        self.access_gate_widgets["title"].setText(gate_title_text)
        self.access_gate_widgets["intro"].setText(gate_intro_text)
        self.access_gate_widgets["login"].setText(gate_login_text)
        self.access_gate_widgets["refresh"].setText(self._tr("overview.auth.gate.refresh"))
        self.access_gate_widgets["logout"].setText(self._tr("overview.auth.gate.logout"))

        status_text = (detail or "").strip()
        show_status = bool(status_text)
        if status == "authorizing" and not show_status:
            status_text = self._tr("overview.auth.gate.waiting")
            show_status = True

        self.access_gate_widgets["status"].setText(status_text)

        account_parts = []
        if display_name:
            account_parts.append(
                self._tr("overview.auth.gate.account", account=escape(display_name))
            )
        if groups:
            account_parts.append(
                self._tr(
                    "overview.auth.gate.groups",
                    groups=escape(", ".join(groups)),
                )
            )
        account_text = "<br>".join(account_parts)
        self.access_gate_widgets["account"].setText(account_text)
        self.access_gate_widgets["account"].setTextFormat(Qt.RichText)

        is_authorizing = status == "authorizing"
        self.access_gate_widgets["login"].setEnabled(not is_authorizing)
        self.access_gate_widgets["status"].setVisible(show_status)
        self.access_gate_widgets["account"].setVisible(bool(account_text))
        self.access_gate_widgets["refresh"].setEnabled(has_saved_login and not is_authorizing)
        self.access_gate_widgets["refresh"].setVisible(has_saved_login)
        self.access_gate_widgets["logout"].setEnabled(has_saved_login and not is_authorizing)
        self.access_gate_widgets["logout"].setVisible(has_saved_login)
        self.settings_reload_button.setEnabled(not is_authorizing)
        self.settings_logout_button.setEnabled(has_saved_login and not is_authorizing)
        self.settings_logout_button.setVisible(has_saved_login)

    def _set_catalog_access_state(self, has_access):
        self.sidebar_frame.setVisible(has_access)
        self.header_frame.setVisible(has_access)
        self.footer_frame.setVisible(has_access)
        self.access_gate_frame.setVisible(not has_access)
        self.settings_frame.setVisible(False)
        self.content_splitter.setVisible(has_access)

    def _sync_empty_catalog_gate(self):
        error_detail = str(
            getattr(self.plugin_controller, "catalog_refresh_error", "") or ""
        ).strip()
        groups = [group for group in self.plugin_controller.auth_groups() if group]
        if error_detail:
            self.access_gate_widgets["title"].setText(self._tr("overview.auth.gate.empty_error_title"))
            self.access_gate_widgets["intro"].setText(
                self._tr("overview.auth.gate.empty_error_intro")
            )
            self.access_gate_widgets["status"].setText(error_detail)
            self.access_gate_widgets["status"].setVisible(True)
            return

        self.access_gate_widgets["title"].setText(self._tr("overview.auth.gate.empty_none_title"))
        self.access_gate_widgets["intro"].setText(
            self._tr("overview.auth.gate.empty_none_intro")
        )
        if groups:
            self.access_gate_widgets["status"].setText(
                self._tr(
                    "overview.auth.gate.empty_none_groups",
                    groups=", ".join(groups),
                )
            )
        else:
            self.access_gate_widgets["status"].setText(
                self._tr("overview.auth.gate.empty_none_account")
            )
        self.access_gate_widgets["status"].setVisible(True)

    def _apply_window_styling(self):
        self.setStyleSheet(
            """
            QDialog#masterOverviewDialog {
                background: palette(window);
                color: palette(window-text);
            }
            QStackedWidget#overviewPageStack,
            QWidget#catalogPage {
                background: transparent;
            }
            QWidget#authPage {
                background: #fafafa;
            }
            QFrame#languageSwitcherFrame {
                background: transparent;
                border: none;
            }
            QToolButton#languageSwitcherButton {
                background: rgba(255, 255, 255, 0.92);
                border: 1px solid #d8d8d3;
                border-radius: 6px;
                padding: 2px;
            }
            QToolButton#languageSwitcherButton:hover {
                border-color: #9bbb93;
                background: #ffffff;
            }
            QToolButton#languageSwitcherButton:checked {
                border-color: #6f9158;
                background: #edf5ea;
            }
            QFrame#authDialogFrame {
                background: transparent;
                border: none;
            }
            QFrame#authDialogCard {
                background: #ffffff;
                border: 1px solid #e8e6e0;
                border-radius: 14px;
            }
            QLabel#authIconBadge {
                background: transparent;
                border: none;
            }
            QLabel#authDialogTitleLabel {
                color: #111111;
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#authDialogSubtitleLabel {
                color: #111111;
                font-size: 11px;
            }
            QLabel#authPermissionCaptionLabel {
                color: #202020;
                font-size: 11px;
                font-weight: 500;
            }
            QFrame#authPermissionCard {
                background: #ffffff;
                border: 1px solid #d3d1ca;
                border-radius: 6px;
            }
            QLabel#authPermissionCheckLabel {
                color: #5fa36d;
                font-size: 14px;
                font-weight: 700;
            }
            QLabel#authPermissionTitleLabel {
                color: #111111;
                font-size: 10px;
                font-weight: 600;
            }
            QLabel#authPermissionItemLabel {
                color: #767676;
                font-size: 9px;
                padding-left: 12px;
            }
            QFrame#authPermissionSeparator {
                background: #dfddd7;
                border: none;
                min-height: 1px;
                max-height: 1px;
            }
            QLabel#authPermissionFootnoteLabel {
                color: #8b8b8b;
                font-size: 8px;
                line-height: 1.4em;
            }
            QLabel#authDialogStatusLabel {
                color: #6f6f6f;
                font-size: 9px;
                padding-left: 8px;
                padding-right: 8px;
            }
            QLabel#authRedirectLabel {
                color: #7b7b7b;
                font-size: 8px;
            }
            QPushButton#authCancelButton {
                background: #ffffff;
                color: #111111;
                border: 1px solid #c8c7c0;
                border-radius: 7px;
                padding: 6px 12px;
                font-size: 10px;
                font-weight: 500;
            }
            QPushButton#authCancelButton:hover {
                background: #f7f7f4;
                border-color: #bcbab2;
            }
            QPushButton#authCancelButton:pressed {
                background: #ecebe6;
            }
            QPushButton#authAuthorizeButton {
                background: #a9c79d;
                color: white;
                border: 1px solid #a9c79d;
                border-radius: 7px;
                padding: 6px 12px;
                font-size: 10px;
                font-weight: 600;
            }
            QPushButton#authAuthorizeButton:hover {
                background: #94b688;
                border-color: #94b688;
            }
            QPushButton#authAuthorizeButton:pressed {
                background: #86a87a;
                border-color: #86a87a;
            }
            QPushButton#authAuthorizeButton:disabled {
                background: #c3d4bd;
                color: #f7faf6;
                border-color: #c3d4bd;
            }
            QFrame#authCard {
                background: white;
                border: 1px solid #c8c8c3;
                border-radius: 22px;
            }
            QLabel#authHeroImage {
                background: transparent;
                border: none;
                padding: 0;
                margin: 0;
                border-top-left-radius: 22px;
                border-top-right-radius: 22px;
            }
            QLabel#authLogoLabel {
                background: transparent;
                border: none;
            }
            QFrame#sidebarFrame {
                background: #666666;
                border-right: 1px solid #5d5d5d;
            }
            QListWidget#filterList {
                background: transparent;
                border: none;
                outline: 0;
                color: #f5f5f3;
                padding: 0;
                font-size: 11px;
                font-weight: 500;
                show-decoration-selected: 1;
            }
            QListWidget#filterList::item {
                padding: 0 12px 0 16px;
                margin: 0;
                border: none;
            }
            QListWidget#filterList::item:hover {
                background: #737373;
                color: #ffffff;
                padding: 0 12px 0 16px;
                border: none;
            }
            QListWidget#filterList::item:selected {
                background: #ffffff;
                color: #111111;
                padding: 0 12px 0 16px;
                border: none;
            }
            QPushButton#sidebarSettingsButton {
                border-radius: 0;
            }
            QFrame#workspaceFrame {
                background: transparent;
            }
            QFrame#headerFrame,
            QFrame#modulePanel,
            QFrame#detailPanel,
            QFrame#footerFrame,
            QFrame#settingsFrame {
                background: transparent;
                border: none;
            }
            QScrollArea#detailScrollArea,
            QWidget#detailContent {
                background: transparent;
                border: none;
            }
            QLabel#workspaceTitleLabel {
                color: palette(window-text);
                font-size: 17px;
                font-weight: 700;
            }
            QLabel#workspaceSubtitleLabel,
            QLabel#resultsSummaryLabel,
            QLabel#detailAboutLabel {
                color: palette(mid);
            }
            QLabel#catalogCountBadge {
                color: palette(mid);
                font-weight: 700;
            }
            QLabel#authTitleLabel {
                color: #111111;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#authIntroLabel {
                color: #202020;
                font-size: 15px;
                padding-left: 40px;
                padding-right: 40px;
            }
            QLabel#authAccountLabel {
                color: #7f7f7f;
                font-size: 12px;
            }
            QLabel#settingsStatusLabel {
                color: #2d5d32;
                background: #eef6ef;
                border: 1px solid #cadecb;
                border-radius: 8px;
                padding: 8px 10px;
            }
            QLabel#authStatusCardLabel {
                color: #6f6f6f;
                background: transparent;
                border: none;
                padding: 0 20px;
            }
            QPushButton#authPrimaryButton {
                background: #5b7847;
                color: white;
                border: 1px solid #49613a;
                border-radius: 7px;
                padding: 4px 16px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton#authPrimaryButton:hover {
                background: #6f9158;
                border-color: #3f5333;
            }
            QPushButton#authPrimaryButton:pressed {
                background: #4c663d;
                border-color: #3a4e2f;
            }
            QPushButton#authPrimaryButton:disabled {
                background: #a5b099;
                color: #f4f6f2;
                border-color: #96a38a;
            }
            QPushButton#authTextButton {
                background: transparent;
                color: #9a9a9a;
                border: none;
                padding: 4px 10px;
                font-size: 12px;
            }
            QPushButton#authTextButton:hover {
                color: #666666;
            }
            QLabel#sectionTitleLabel,
            QLabel#detailDescriptionLabel {
                color: palette(window-text);
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#detailTitleLabel {
                color: palette(window-text);
            }
            QLabel#detailStatusLabel {
                color: palette(window-text);
            }
            QHeaderView::section {
                background: transparent;
                border: none;
            }
            QSplitter::handle {
                background: palette(midlight);
            }
            """
        )

    def _start_catalog_login(self):
        self.plugin_controller.start_catalog_login()
        self.refresh()

    def _refresh_catalog_login(self):
        self.plugin_controller.refresh_catalog_login()
        self.refresh()

    def _remove_catalog_login(self):
        self.plugin_controller.remove_catalog_login()
        self.refresh()

    def _populate_filters(self):
        current_filter = self._active_filter_key()
        counts = {
            "all": len(self._all_rows),
            "installed": sum(
                1
                for row in self._all_rows
                if row["is_installed"]
            ),
            "not_installed": sum(
                1
                for row in self._all_rows
                if not row["is_installed"]
            ),
            "background": sum(
                1
                for row in self._all_rows
                if row["tool_type"] == "background"
            ),
            "experimental": sum(
                1 for row in self._all_rows if row["is_experimental"]
            ),
            "favorites": sum(
                1
                for row in self._all_rows
                if row["is_favorite"]
            ),
            "other": sum(
                1
                for row in self._all_rows
                if row.get("is_external")
            ),
        }

        self.filter_list.blockSignals(True)
        self.filter_list.clear()
        fallback_item = None

        for filter_key, label_key, asset_name in self.FILTERS:
            label = self._tr(label_key)
            item = QListWidgetItem(self._sidebar_icon(asset_name), label)
            item.setData(Qt.UserRole, filter_key)
            item.setToolTip(
                self._tr(
                    "overview.filter.tooltip",
                    label=label,
                    count=counts[filter_key],
                )
            )
            item.setSizeHint(QSize(0, 58))
            self.filter_list.addItem(item)
            if filter_key == current_filter:
                fallback_item = item
            if filter_key == "all" and fallback_item is None:
                fallback_item = item

        if fallback_item is not None:
            self.filter_list.setCurrentItem(fallback_item)
        self.filter_list.blockSignals(False)

    def _active_filter_key(self):
        current_item = self.filter_list.currentItem()
        if current_item is None:
            return "all"
        return current_item.data(Qt.UserRole) or "all"

    def _handle_filter_selection_changed(self, *_args):
        self._settings_active = False
        self.settings_nav_button.setChecked(False)
        self._apply_filters()

    def _open_settings_from_sidebar(self):
        self._settings_active = True
        self.settings_nav_button.setChecked(True)
        self._apply_filters()

    def _apply_filters(self, *_args, preferred_key=None):
        if self._settings_active:
            self._show_settings_view()
            self.setWindowTitle(self._tr("overview.window.settings"))
            return

        filter_key = self._active_filter_key()
        self._show_catalog_view()
        search_term = self.search_field.text().strip().lower()

        self.module_list.blockSignals(True)
        self.module_list.clear()

        visible_rows = []
        for row in self._all_rows:
            if not self._matches_filter(row, filter_key):
                continue
            if search_term and not self._matches_search(row, search_term):
                continue
            visible_rows.append(row)

        self.module_section_label.setText(self._filter_label(filter_key))
        self.results_summary_label.setText(
            self._results_summary_text(len(visible_rows), filter_key)
        )

        for row in visible_rows:
            item = QTreeWidgetItem([self._module_list_label(row), ""])
            item.setData(0, Qt.UserRole, row["key"])
            item.setData(0, Qt.UserRole + 1, row["status_code"])
            item.setToolTip(0, f"{row['status_text']}: {row['detail']}")
            item.setIcon(0, self._decorated_module_icon(row, 20, 12, show_favorite_badge=False))
            item.setTextAlignment(1, Qt.AlignCenter)
            item.setToolTip(1, item.toolTip(0))
            status_icon = self._status_icon(row)
            if status_icon is not None:
                item.setIcon(1, status_icon)

            font = item.font(0)
            if row["status_code"] in {"active", "update"}:
                font.setBold(True)
                item.setFont(0, font)

            self.module_list.addTopLevelItem(item)

        self.module_list.blockSignals(False)

        selected_item = None
        if preferred_key:
            selected_item = self._find_item_by_key(preferred_key)
        if selected_item is None and self.module_list.topLevelItemCount() > 0:
            selected_item = self.module_list.topLevelItem(0)

        if selected_item is not None:
            self.module_list.setCurrentItem(selected_item)
        else:
            self._render_empty_state(search_term)

        self._sync_details()

    def _matches_filter(self, row, filter_key):
        if filter_key == "all":
            return True
        if filter_key == "installed":
            return row["is_installed"]
        if filter_key == "not_installed":
            return not row["is_installed"]
        if filter_key == "background":
            return row["tool_type"] == "background"
        if filter_key == "experimental":
            return row["is_experimental"]
        if filter_key == "favorites":
            return row["is_favorite"]
        if filter_key == "other":
            return bool(row.get("is_external"))
        return False

    def _filter_label(self, filter_key):
        for candidate_key, label_key, _asset_name in self.FILTERS:
            if candidate_key == filter_key:
                return self._tr(label_key)
        return self._tr("overview.filter.all")

    def _module_list_label(self, row):
        label = row["label"]
        if row.get("is_experimental"):
            return f"{label} [{self._tr('plugin.release.experimental')}]"
        return label

    def _results_summary_text(self, result_count, filter_key):
        filter_label = self._filter_label(filter_key)
        return self._tr(
            "overview.results_summary",
            count=result_count,
            label=filter_label,
        )

    def _matches_search(self, row, search_term):
        search_haystack = " ".join(
            [
                row["label"],
                row["package"],
                row["description"],
                row["about"],
                row["author"],
                row["category"],
                row["tool_type_label"],
                row["release_state_label"],
                row["detail"],
                row["management_text"],
                self._tr("overview.filter.favorites").lower() if row["is_favorite"] else "",
                " ".join(row["tags"]),
            ]
        ).lower()
        return search_term in search_haystack

    def _find_item_by_key(self, wanted_key):
        for index in range(self.module_list.topLevelItemCount()):
            item = self.module_list.topLevelItem(index)
            if item.data(0, Qt.UserRole) == wanted_key:
                return item
        return None

    def _sync_details(self):
        if self._settings_active:
            return
        item = self.module_list.currentItem()
        if item is None:
            self._update_favorite_button(None)
            self.open_button.setEnabled(False)
            self.open_button.hide()
            self.primary_button.setEnabled(False)
            self.secondary_button.setEnabled(False)
            self.primary_button.setText(self._tr("overview.action.install"))
            self.secondary_button.setText(self._tr("overview.action.remove"))
            return

        row = self._rows_by_key.get(item.data(0, Qt.UserRole))
        if row is None:
            self._update_favorite_button(None)
            self.open_button.setEnabled(False)
            self.open_button.hide()
            self.primary_button.setEnabled(False)
            self.secondary_button.setEnabled(False)
            self.primary_button.setText(self._tr("overview.action.install"))
            self.secondary_button.setText(self._tr("overview.action.remove"))
            return

        self._update_favorite_button(row)
        can_open = self.plugin_controller.can_open_module(row)
        self.open_button.setVisible(can_open)
        self.open_button.setEnabled(can_open)
        self.open_button.setText(
            self.plugin_controller.get_open_action_label(row)
            or self._tr("overview.action.open")
        )
        self.primary_button.setEnabled(
            self.plugin_controller.can_run_primary_action(row)
        )
        self.primary_button.setText(
            self.plugin_controller.get_primary_action_label(row)
            or self._tr("plugin.action.fallback")
        )
        self.secondary_button.setEnabled(
            self.plugin_controller.can_run_secondary_action(row)
        )
        self.secondary_button.setText(
            self.plugin_controller.get_secondary_action_label(row)
            or self._tr("overview.action.remove")
        )
        self._render_module_details(row)

    def _render_empty_state(self, search_term):
        self.title_label.setText(self._tr("overview.empty.title"))
        if search_term:
            self.description_label.setText(
                self._tr("overview.empty.search", term=escape(search_term))
            )
        else:
            self.description_label.setText(self._tr("overview.empty.filter"))
        self.status_label.setText(self._tr("overview.empty.status"))
        self.about_label.setText(
            self._tr("overview.empty.about")
        )
        self.category_value.setText("-")
        self.type_value.setText("-")
        self.favorite_value.setText("-")
        self.package_value.setText("-")
        self.management_value.setText("-")
        self.release_value.setText("-")
        self.tags_value.setText("-")
        self.author_value.setText("-")
        self.version_value.setText("-")
        self.links_value.setText("-")
        self.icon_label.setPixmap(QIcon(
            str(self.plugin_controller.plugin_dir / "icon.svg")
        ).pixmap(88, 88))

    def _render_module_details(self, row):
        self.detail_scroll_area.verticalScrollBar().setValue(0)
        self.title_label.setText(row["label"])
        self.description_label.setText(
            row["description"] or self._tr("overview.detail.no_description")
        )
        self.status_label.setText(
            self._tr(
                "overview.detail.status",
                status=escape(row["status_text"]),
                detail=escape(row["detail"]),
            )
        )
        self.status_label.setTextFormat(Qt.RichText)

        about_text = row["about"]
        favorite_hint = ""
        if row["is_favorite"] and row["tool_type"] == "background":
            favorite_hint = self._tr("overview.detail.favorite_background")
        elif row["is_favorite"]:
            favorite_hint = self._tr("overview.detail.favorite_regular")

        if about_text and about_text != row["description"]:
            self.about_label.setText(about_text + favorite_hint)
        elif row["tool_type"] == "background":
            self.about_label.setText(self._tr("overview.detail.background_default") + favorite_hint)
        else:
            self.about_label.setText(self._tr("overview.detail.regular_default") + favorite_hint)

        self.category_value.setText(row["category"] or "-")
        self.type_value.setText(row["tool_type_label"] or "-")
        self.favorite_value.setText("")
        self.favorite_value.setPixmap(
            self._favorite_icon(row["is_favorite"]).pixmap(18, 18)
        )
        self.favorite_value.setToolTip(
            self._tr("overview.favorite.saved")
            if row["is_favorite"]
            else self._tr("overview.favorite.not_saved")
        )
        self.package_value.setText(row["package"] or "-")
        self.management_value.setText(row["management_text"] or "-")
        self.release_value.setText(row["release_state_label"] or "-")
        self.release_value.setToolTip(row["release_state_note"] or "")
        self.tags_value.setText(", ".join(row["tags"]) or "-")
        self.author_value.setText(row["author"] or "-")
        self.version_value.setText(row["version"] or "-")
        self.links_value.setText(self._build_links_html(row))

        self.icon_label.setPixmap(
            self._decorated_module_pixmap(
                row,
                88,
                28,
                show_favorite_badge=row["is_favorite"],
            )
        )

    def _build_links_html(self, row):
        links = []
        if row["homepage"]:
            links.append(
                f"<a href=\"{escape(row['homepage'])}\">{self._tr('overview.links.homepage')}</a>"
            )
        if row["tracker"]:
            links.append(
                f"<a href=\"{escape(row['tracker'])}\">{self._tr('overview.links.tracker')}</a>"
            )
        if row["repository"]:
            links.append(
                f"<a href=\"{escape(row['repository'])}\">{self._tr('overview.links.repository')}</a>"
            )
        return "   ".join(links) or "-"

    def _create_value_label(self, parent, rich_text=False):
        label = QLabel(parent)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if rich_text:
            label.setTextFormat(Qt.RichText)
            label.setOpenExternalLinks(True)
            label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        return label

    def _run_primary_action(self):
        item = self.module_list.currentItem()
        if item is None:
            return

        key = item.data(0, Qt.UserRole)
        if key is None:
            return

        self.plugin_controller.run_primary_action_by_key(key)
        self.refresh()

    def _run_secondary_action(self):
        item = self.module_list.currentItem()
        if item is None:
            return

        key = item.data(0, Qt.UserRole)
        if key is None:
            return

        self.plugin_controller.run_secondary_action_by_key(key)
        self.refresh()

    def _open_selected_module(self):
        item = self.module_list.currentItem()
        if item is None:
            return

        key = item.data(0, Qt.UserRole)
        if key is None:
            return

        self.plugin_controller.open_module_by_key(key)
        self.refresh()

    def _handle_item_double_click(self, item, _column):
        row = self._rows_by_key.get(item.data(0, Qt.UserRole))
        if row is None or not self.plugin_controller.can_run_primary_action(row):
            return
        self._run_primary_action()

    def _refresh_catalog_and_view(self):
        self.plugin_controller.refresh_catalog()
        self.refresh()

    def _show_settings_view(self):
        self._settings_active = True
        self.settings_nav_button.setChecked(True)
        self.workspace_title_label.setText(self._tr("overview.header.settings_title"))
        self.workspace_subtitle_label.setText(
            self._tr("overview.header.settings_subtitle")
        )
        self.catalog_count_badge.hide()
        self.search_field.hide()
        self.content_splitter.hide()
        self.settings_frame.show()
        self.footer_frame.show()
        self._set_module_action_visibility(False)
        self.settings_widget.set_values(self.plugin_controller.get_shared_settings())

    def _show_catalog_view(self):
        self._settings_active = False
        self.settings_nav_button.setChecked(False)
        self.workspace_title_label.setText(self._tr("overview.header.catalog_title"))
        self.workspace_subtitle_label.setText(self._tr("overview.header.catalog_subtitle"))
        self.catalog_count_badge.show()
        self.search_field.show()
        self.settings_frame.hide()
        self.content_splitter.show()
        self.footer_frame.show()
        self._set_module_action_visibility(True)

    def _set_module_action_visibility(self, visible):
        self.favorite_button.setVisible(visible)
        self.open_button.setVisible(visible and self.open_button.isEnabled())
        self.primary_button.setVisible(visible)
        self.secondary_button.setVisible(visible)

    def _save_settings_view(self):
        _settings, message = self.plugin_controller.apply_settings_values(
            self.settings_widget.values(),
            announce=False,
        )
        self.settings_status_label.setText(message)
        self.settings_status_label.show()
        self.refresh()

    def _restore_settings_view(self):
        self.settings_widget.restore_defaults()
        self.settings_status_label.setText(
            self._tr("overview.settings.saved_defaults")
        )
        self.settings_status_label.show()

    def _toggle_selected_favorite(self):
        item = self.module_list.currentItem()
        if item is None:
            return

        key = item.data(0, Qt.UserRole)
        if key is None:
            return

        self.plugin_controller.toggle_favorite_by_key(key)

    def _favorite_icon(self, is_favorite):
        icon_name = "IcBaselineStar.svg" if is_favorite else "IcBaselineStarBorder.svg"
        return QIcon(str(self.plugin_controller.plugin_dir / "assets" / icon_name))

    def _loaded_icon(self):
        return QIcon(
            str(self.plugin_controller.plugin_dir / "assets" / "CarbonCheckmarkFilled.svg")
        )

    def _status_icon(self, row):
        if row["status_code"] not in {"active", "update"}:
            return None
        return self._loaded_icon()

    def _decorated_module_icon(self, row, size, badge_size, show_favorite_badge):
        return QIcon(
            self._decorated_module_pixmap(
                row,
                size,
                badge_size,
                show_favorite_badge=show_favorite_badge,
            )
        )

    def _decorated_module_pixmap(self, row, size, badge_size, show_favorite_badge):
        base_icon = QIcon(row["icon_path"])
        base_pixmap = base_icon.pixmap(size, size)
        if base_pixmap.isNull():
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.transparent)
        else:
            pixmap = QPixmap(base_pixmap)

        if not show_favorite_badge or not row["is_favorite"]:
            return pixmap

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        badge_icon = self._favorite_icon(row["is_favorite"])
        badge_padding = max(1, badge_size // 6)
        badge_diameter = badge_size + (badge_padding * 2)
        badge_x = size - badge_diameter
        badge_y = size - badge_diameter
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawEllipse(badge_x, badge_y, badge_diameter, badge_diameter)
        painter.drawPixmap(
            badge_x + badge_padding,
            badge_y + badge_padding,
            badge_icon.pixmap(badge_size, badge_size),
        )
        painter.end()
        return pixmap

    def _update_favorite_button(self, row):
        is_enabled = row is not None
        is_favorite = bool(row and row["is_favorite"])

        self.favorite_button.setEnabled(is_enabled)
        self.favorite_button.setIcon(self._favorite_icon(is_favorite))
        self.favorite_button.setToolTip(
            self._tr("overview.favorite.remove")
            if is_favorite
            else self._tr("overview.favorite.add")
        )
        self.favorite_button.setStatusTip(self.favorite_button.toolTip())
