from __future__ import annotations

from html import escape

from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStyle,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class MasterOverviewDialog(QDialog):
    FILTERS = (
        ("all", "Alle", QStyle.SP_FileDialogDetailedView),
        ("interactive", "Normale Tools", QStyle.SP_FileDialogListView),
        ("background", "Hintergrundtools", QStyle.SP_ComputerIcon),
        ("experimental", "Experimental", QStyle.SP_MessageBoxWarning),
        ("favorites", "Favoriten", QStyle.SP_DirHomeIcon),
    )

    def __init__(self, plugin_controller, parent=None):
        super().__init__(parent)
        self.plugin_controller = plugin_controller
        self._rows_by_key = {}
        self._all_rows = []

        self.setObjectName("masterOverviewDialog")
        self.setWindowTitle("Erweiterungen | Katalog")
        self.setWindowIcon(QIcon(str(plugin_controller.plugin_dir / "icon.svg")))
        self.resize(1260, 780)
        self.setMinimumSize(1080, 680)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.page_stack = QStackedWidget(self)
        self.page_stack.setObjectName("overviewPageStack")
        root_layout.addWidget(self.page_stack, 1)

        self.auth_page = QWidget(self.page_stack)
        self.auth_page.setObjectName("authPage")
        auth_page_layout = QVBoxLayout(self.auth_page)
        auth_page_layout.setContentsMargins(26, 26, 26, 26)
        auth_page_layout.setSpacing(16)
        auth_page_layout.addStretch(1)

        auth_card = QFrame(self.auth_page)
        auth_card.setObjectName("authCard")
        auth_card_layout = QVBoxLayout(auth_card)
        auth_card_layout.setContentsMargins(28, 28, 28, 28)
        auth_card_layout.setSpacing(14)

        self.auth_title_label = QLabel("Geschuetzten Plugin-Katalog entsperren", auth_card)
        self.auth_title_label.setObjectName("authTitleLabel")
        self.auth_title_label.setWordWrap(True)
        auth_card_layout.addWidget(self.auth_title_label)

        self.auth_intro_label = QLabel(
            "Die Plugin-Pakete liegen geschuetzt in Nextcloud. Vor dem Laden des Katalogs wird eine Browser-Anmeldung ueber Nextcloud benoetigt.",
            auth_card,
        )
        self.auth_intro_label.setObjectName("authIntroLabel")
        self.auth_intro_label.setWordWrap(True)
        auth_card_layout.addWidget(self.auth_intro_label)

        self.auth_status_label = QLabel("", auth_card)
        self.auth_status_label.setObjectName("authStatusLabel")
        self.auth_status_label.setWordWrap(True)
        auth_card_layout.addWidget(self.auth_status_label)

        self.auth_account_label = QLabel("", auth_card)
        self.auth_account_label.setObjectName("authAccountLabel")
        self.auth_account_label.setWordWrap(True)
        auth_card_layout.addWidget(self.auth_account_label)

        auth_button_row = QHBoxLayout()
        auth_button_row.setSpacing(8)
        auth_card_layout.addLayout(auth_button_row)

        self.auth_login_button = QPushButton("Im Browser anmelden", auth_card)
        self.auth_login_button.setObjectName("primaryButton")
        self.auth_login_button.clicked.connect(self._start_catalog_login)
        auth_button_row.addWidget(self.auth_login_button)

        self.auth_refresh_button = QPushButton("Verbindung pruefen", auth_card)
        self.auth_refresh_button.setObjectName("subtleButton")
        self.auth_refresh_button.clicked.connect(self._refresh_catalog_login)
        auth_button_row.addWidget(self.auth_refresh_button)

        self.auth_logout_button = QPushButton("Anmeldung entfernen", auth_card)
        self.auth_logout_button.setObjectName("secondaryButton")
        self.auth_logout_button.clicked.connect(self._remove_catalog_login)
        auth_button_row.addWidget(self.auth_logout_button)

        self.auth_settings_button = QPushButton("Einstellungen", auth_card)
        self.auth_settings_button.setObjectName("subtleButton")
        self.auth_settings_button.clicked.connect(self.plugin_controller.show_settings)
        auth_button_row.addWidget(self.auth_settings_button)

        auth_button_row.addStretch(1)
        auth_page_layout.addWidget(auth_card, 0, Qt.AlignHCenter)
        auth_page_layout.addStretch(1)
        self.page_stack.addWidget(self.auth_page)

        self.catalog_page = QWidget(self.page_stack)
        self.catalog_page.setObjectName("catalogPage")
        layout = QHBoxLayout(self.catalog_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar_frame = QFrame(self.catalog_page)
        sidebar_frame.setObjectName("sidebarFrame")
        sidebar_frame.setFixedWidth(184)
        sidebar_layout = QVBoxLayout(sidebar_frame)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        self.filter_list = QListWidget(sidebar_frame)
        self.filter_list.setObjectName("filterList")
        self.filter_list.setFrameShape(QFrame.Box)
        self.filter_list.setLineWidth(0)
        self.filter_list.setSpacing(0)
        self.filter_list.setIconSize(QSize(28, 28))
        self.filter_list.setUniformItemSizes(True)
        self.filter_list.currentItemChanged.connect(self._apply_filters)
        sidebar_layout.addWidget(self.filter_list, 1)
        layout.addWidget(sidebar_frame)

        workspace_frame = QFrame(self.catalog_page)
        workspace_frame.setObjectName("workspaceFrame")
        workspace_layout = QVBoxLayout(workspace_frame)
        workspace_layout.setContentsMargins(12, 12, 12, 12)
        workspace_layout.setSpacing(10)
        layout.addWidget(workspace_frame, 1)

        header_frame = QFrame(workspace_frame)
        header_frame.setObjectName("headerFrame")
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        workspace_layout.addWidget(header_frame)

        header_top_layout = QHBoxLayout()
        header_top_layout.setSpacing(12)
        header_layout.addLayout(header_top_layout)

        header_text_layout = QVBoxLayout()
        header_text_layout.setSpacing(4)
        header_top_layout.addLayout(header_text_layout, 1)

        workspace_title = QLabel("Plugin-Katalog", header_frame)
        workspace_title.setObjectName("workspaceTitleLabel")
        header_text_layout.addWidget(workspace_title)

        workspace_subtitle = QLabel("Verwalten direkt aus dem Mastertool.", header_frame)
        workspace_subtitle.setObjectName("workspaceSubtitleLabel")
        workspace_subtitle.setWordWrap(True)
        header_text_layout.addWidget(workspace_subtitle)

        self.catalog_count_badge = QLabel("", header_frame)
        self.catalog_count_badge.setObjectName("catalogCountBadge")
        self.catalog_count_badge.setAlignment(Qt.AlignCenter)
        header_top_layout.addWidget(self.catalog_count_badge, 0, Qt.AlignTop)

        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(8)
        header_layout.addLayout(controls_layout)

        self.search_field = QLineEdit(header_frame)
        self.search_field.setObjectName("searchField")
        self.search_field.setPlaceholderText("Plugins durchsuchen...")
        self.search_field.setClearButtonEnabled(True)
        self.search_field.textChanged.connect(self._apply_filters)
        controls_layout.addWidget(self.search_field, 1)

        self.content_splitter = QSplitter(Qt.Horizontal, workspace_frame)
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

        self.module_section_label = QLabel("Alle Module", module_panel)
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
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(12, 12, 12, 12)
        detail_layout.setSpacing(12)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)
        detail_layout.addLayout(header_layout)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(6)
        header_layout.addLayout(title_layout, 1)

        self.title_label = QLabel(detail_panel)
        self.title_label.setObjectName("detailTitleLabel")
        title_font = QFont(self.font())
        title_font.setPointSize(title_font.pointSize() + 12)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setWordWrap(True)
        title_layout.addWidget(self.title_label)

        self.description_label = QLabel(detail_panel)
        self.description_label.setObjectName("detailDescriptionLabel")
        description_font = QFont(self.font())
        description_font.setPointSize(description_font.pointSize() + 3)
        description_font.setBold(True)
        self.description_label.setFont(description_font)
        self.description_label.setWordWrap(True)
        title_layout.addWidget(self.description_label)

        self.status_label = QLabel(detail_panel)
        self.status_label.setObjectName("detailStatusLabel")
        self.status_label.setWordWrap(True)
        title_layout.addWidget(self.status_label)

        self.icon_label = QLabel(detail_panel)
        self.icon_label.setFixedSize(88, 88)
        self.icon_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        header_layout.addWidget(self.icon_label, 0, Qt.AlignTop)

        self.about_label = QLabel(detail_panel)
        self.about_label.setObjectName("detailAboutLabel")
        self.about_label.setWordWrap(True)
        self.about_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        detail_layout.addWidget(self.about_label)

        separator = QFrame(detail_panel)
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        detail_layout.addWidget(separator)

        self.metadata_form = QFormLayout()
        self.metadata_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.metadata_form.setFormAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.metadata_form.setHorizontalSpacing(16)
        self.metadata_form.setVerticalSpacing(10)
        detail_layout.addLayout(self.metadata_form)

        self.category_value = self._create_value_label(detail_panel)
        self.type_value = self._create_value_label(detail_panel)
        self.favorite_value = self._create_value_label(detail_panel)
        self.package_value = self._create_value_label(detail_panel)
        self.management_value = self._create_value_label(detail_panel)
        self.release_value = self._create_value_label(detail_panel)
        self.tags_value = self._create_value_label(detail_panel)
        self.author_value = self._create_value_label(detail_panel)
        self.version_value = self._create_value_label(detail_panel)
        self.links_value = self._create_value_label(detail_panel, rich_text=True)

        self.metadata_form.addRow("Kategorie", self.category_value)
        self.metadata_form.addRow("Typ", self.type_value)
        self.metadata_form.addRow("Favorit", self.favorite_value)
        self.metadata_form.addRow("Paket", self.package_value)
        self.metadata_form.addRow("Verwaltung", self.management_value)
        self.metadata_form.addRow("Freigabe", self.release_value)
        self.metadata_form.addRow("Tags", self.tags_value)
        self.metadata_form.addRow("Autor", self.author_value)
        self.metadata_form.addRow("Version", self.version_value)
        self.metadata_form.addRow("Weitere Informationen", self.links_value)

        detail_layout.addStretch(1)
        self.content_splitter.addWidget(detail_panel)
        self.content_splitter.setStretchFactor(0, 5)
        self.content_splitter.setStretchFactor(1, 6)

        footer_frame = QFrame(workspace_frame)
        footer_frame.setObjectName("footerFrame")
        actions_layout = QHBoxLayout(footer_frame)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        workspace_layout.addWidget(footer_frame)
        button_height = 30

        self.refresh_button = QPushButton("Katalog neu laden", footer_frame)
        self.refresh_button.setObjectName("subtleButton")
        self.refresh_button.setFixedHeight(button_height)
        self.refresh_button.clicked.connect(self._refresh_catalog_and_view)
        actions_layout.addWidget(self.refresh_button)

        self.settings_button = QPushButton("Einstellungen", footer_frame)
        self.settings_button.setObjectName("subtleButton")
        self.settings_button.setFixedHeight(button_height)
        self.settings_button.clicked.connect(self.plugin_controller.show_settings)
        actions_layout.addWidget(self.settings_button)

        actions_layout.addStretch(1)

        self.favorite_button = QToolButton(footer_frame)
        self.favorite_button.setObjectName("favoriteButton")
        self.favorite_button.setText("")
        self.favorite_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.favorite_button.setIconSize(QSize(18, 18))
        self.favorite_button.setFixedSize(button_height, button_height)
        self.favorite_button.clicked.connect(self._toggle_selected_favorite)
        actions_layout.addWidget(self.favorite_button)

        self.open_button = QPushButton("Oeffnen", footer_frame)
        self.open_button.setObjectName("subtleButton")
        self.open_button.setFixedHeight(button_height)
        self.open_button.clicked.connect(self._open_selected_module)
        self.open_button.hide()
        actions_layout.addWidget(self.open_button)

        self.primary_button = QPushButton("Installieren", footer_frame)
        self.primary_button.setObjectName("primaryButton")
        self.primary_button.setFixedHeight(button_height)
        self.primary_button.clicked.connect(self._run_primary_action)
        actions_layout.addWidget(self.primary_button)

        self.secondary_button = QPushButton("Entfernen", footer_frame)
        self.secondary_button.setObjectName("secondaryButton")
        self.secondary_button.setFixedHeight(button_height)
        self.secondary_button.clicked.connect(self._run_secondary_action)
        actions_layout.addWidget(self.secondary_button)

        button_box = QDialogButtonBox(QDialogButtonBox.Close, footer_frame)
        button_box.setObjectName("dialogButtonBox")
        button_box.rejected.connect(self.reject)
        close_button = button_box.button(QDialogButtonBox.Close)
        if close_button is not None:
            close_button.setObjectName("subtleButton")
            close_button.setFixedHeight(button_height)
        actions_layout.addWidget(button_box)

        self.page_stack.addWidget(self.catalog_page)
        self._apply_window_styling()
        self.refresh()

    def refresh(self):
        self._sync_auth_page()
        if not self.plugin_controller.can_access_catalog():
            self.page_stack.setCurrentWidget(self.auth_page)
            self.setWindowTitle("Erweiterungen | Anmeldung")
            return

        self.page_stack.setCurrentWidget(self.catalog_page)
        current_item = self.module_list.currentItem()
        current_key = current_item.data(0, Qt.UserRole) if current_item is not None else None
        self._all_rows = sorted(
            self.plugin_controller.get_module_rows(),
            key=lambda row: row["label"].lower(),
        )
        self._rows_by_key = {
            row["key"]: row for row in self._all_rows
        }

        self._populate_filters()
        self._apply_filters(preferred_key=current_key)
        self.catalog_count_badge.setText(f"{len(self._all_rows)} Module")
        self.setWindowTitle(
            f"Erweiterungen | Katalog ({len(self._all_rows)})"
        )

    def _sync_auth_page(self):
        status = self.plugin_controller.auth_status()
        detail = self.plugin_controller.auth_status_detail()
        display_name = self.plugin_controller.auth_display_name()
        groups = self.plugin_controller.auth_groups()
        has_saved_login = self.plugin_controller.has_saved_catalog_login()
        can_access = self.plugin_controller.can_access_catalog()

        if can_access:
            self.auth_title_label.setText("Nextcloud-Verbindung aktiv")
            self.auth_login_button.setText("Erneut anmelden")
        elif status == "authorizing":
            self.auth_title_label.setText("Browser-Login laeuft")
            self.auth_login_button.setText("Browser-Login laeuft...")
        elif has_saved_login:
            self.auth_title_label.setText("Gespeicherte Anmeldung pruefen")
            self.auth_login_button.setText("Neu anmelden")
        else:
            self.auth_title_label.setText("Geschuetzten Plugin-Katalog entsperren")
            self.auth_login_button.setText("Im Browser anmelden")

        self.auth_status_label.setText(detail or "Noch nicht bei Nextcloud angemeldet.")

        account_parts = []
        if display_name:
            account_parts.append(f"<b>Konto:</b> {escape(display_name)}")
        if groups:
            account_parts.append(f"<b>Gruppen:</b> {escape(', '.join(groups))}")
        if not account_parts:
            account_parts.append(
                f"<b>Server:</b> {escape(self.plugin_controller.get_shared_settings().get('nextcloud_base_url', '') or '-')}"
            )
        self.auth_account_label.setText("<br>".join(account_parts))
        self.auth_account_label.setTextFormat(Qt.RichText)

        is_authorizing = status == "authorizing"
        self.auth_login_button.setEnabled(not is_authorizing)
        self.auth_refresh_button.setEnabled(has_saved_login and not is_authorizing)
        self.auth_logout_button.setEnabled(has_saved_login and not is_authorizing)
        self.auth_logout_button.setVisible(has_saved_login)

    def _apply_window_styling(self):
        self.setStyleSheet(
            """
            QDialog#masterOverviewDialog {
                background: palette(window);
                color: palette(window-text);
            }
            QStackedWidget#overviewPageStack,
            QWidget#authPage,
            QWidget#catalogPage {
                background: transparent;
            }
            QFrame#authCard {
                background: palette(base);
                border: 1px solid palette(midlight);
                border-radius: 10px;
            }
            QFrame#sidebarFrame {
                background: #8f8f8f;
                border-right: 1px solid palette(mid);
            }
            QListWidget#filterList {
                background: #8f8f8f;
                border: none;
                outline: 0;
                color: white;
                padding: 0;
            }
            QListWidget#filterList::item {
                padding: 7px 8px 7px 18px;
                margin: 0;
            }
            QListWidget#filterList::item:hover {
                background: #9a9a9a;
                padding: 7px 8px 7px 18px;
            }
            QListWidget#filterList::item:selected {
                background: palette(window);
                color: palette(window-text);
                padding: 7px 8px 7px 18px;
            }
            QFrame#workspaceFrame {
                background: transparent;
            }
            QFrame#headerFrame,
            QFrame#modulePanel,
            QFrame#detailPanel,
            QFrame#footerFrame {
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
                color: palette(window-text);
                font-size: 20px;
                font-weight: 700;
            }
            QLabel#authIntroLabel,
            QLabel#authAccountLabel {
                color: palette(mid);
            }
            QLabel#authStatusLabel {
                color: palette(window-text);
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
            "all": sum(
                1 for row in self._all_rows if not row["is_experimental"]
            ),
            "interactive": sum(
                1
                for row in self._all_rows
                if row["tool_type"] == "interactive" and not row["is_experimental"]
            ),
            "background": sum(
                1
                for row in self._all_rows
                if row["tool_type"] == "background" and not row["is_experimental"]
            ),
            "experimental": sum(
                1 for row in self._all_rows if row["is_experimental"]
            ),
            "favorites": sum(
                1
                for row in self._all_rows
                if row["is_favorite"] and not row["is_experimental"]
            ),
        }

        self.filter_list.blockSignals(True)
        self.filter_list.clear()
        style = self.style()
        fallback_item = None

        for filter_key, label, icon_role in self.FILTERS:
            item = QListWidgetItem(style.standardIcon(icon_role), label)
            item.setData(Qt.UserRole, filter_key)
            item.setToolTip(f"{label}: {counts[filter_key]} Module")
            item.setSizeHint(QSize(0, 50))
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

    def _apply_filters(self, *_args, preferred_key=None):
        filter_key = self._active_filter_key()
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
            return not row["is_experimental"]
        if filter_key in {"interactive", "background"}:
            return row["tool_type"] == filter_key and not row["is_experimental"]
        if filter_key == "experimental":
            return row["is_experimental"]
        if filter_key == "favorites":
            return row["is_favorite"] and not row["is_experimental"]
        return False

    def _filter_label(self, filter_key):
        for candidate_key, label, _icon_role in self.FILTERS:
            if candidate_key == filter_key:
                return label
        return "Alle"

    def _module_list_label(self, row):
        label = row["label"]
        if row.get("is_experimental"):
            return f"{label} [Experimental]"
        return label

    def _results_summary_text(self, result_count, filter_key):
        filter_label = self._filter_label(filter_key)
        return f"{result_count} Module | {filter_label}"

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
                "favorit" if row["is_favorite"] else "",
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
        item = self.module_list.currentItem()
        if item is None:
            self._update_favorite_button(None)
            self.open_button.setEnabled(False)
            self.open_button.hide()
            self.primary_button.setEnabled(False)
            self.secondary_button.setEnabled(False)
            self.primary_button.setText("Installieren")
            self.secondary_button.setText("Entfernen")
            return

        row = self._rows_by_key.get(item.data(0, Qt.UserRole))
        if row is None:
            self._update_favorite_button(None)
            self.open_button.setEnabled(False)
            self.open_button.hide()
            self.primary_button.setEnabled(False)
            self.secondary_button.setEnabled(False)
            self.primary_button.setText("Installieren")
            self.secondary_button.setText("Entfernen")
            return

        self._update_favorite_button(row)
        can_open = self.plugin_controller.can_open_module(row)
        self.open_button.setVisible(can_open)
        self.open_button.setEnabled(can_open)
        self.open_button.setText(
            self.plugin_controller.get_open_action_label(row) or "Oeffnen"
        )
        self.primary_button.setEnabled(
            self.plugin_controller.can_run_primary_action(row)
        )
        self.primary_button.setText(
            self.plugin_controller.get_primary_action_label(row) or "Aktion"
        )
        self.secondary_button.setEnabled(
            self.plugin_controller.can_run_secondary_action(row)
        )
        self.secondary_button.setText(
            self.plugin_controller.get_secondary_action_label(row) or "Entfernen"
        )
        self._render_module_details(row)

    def _render_empty_state(self, search_term):
        self.title_label.setText("Keine Module gefunden")
        if search_term:
            self.description_label.setText(
                f"Keine Treffer fuer '{escape(search_term)}'."
            )
        else:
            self.description_label.setText("Der aktuelle Filter enthaelt keine Module.")
        self.status_label.setText("Passe Suche oder Filter an.")
        self.about_label.setText(
            "Der Trassify-Masterkatalog orientiert sich an der nativen QGIS-Erweiterungsliste."
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
        self.title_label.setText(row["label"])
        self.description_label.setText(
            row["description"] or "Kein Beschreibungstext verfuegbar."
        )
        self.status_label.setText(
            f"<b>Status:</b> {escape(row['status_text'])} | {escape(row['detail'])}"
        )
        self.status_label.setTextFormat(Qt.RichText)

        about_text = row["about"]
        favorite_hint = ""
        if row["is_favorite"] and row["tool_type"] == "background":
            favorite_hint = (
                " Dieses Hintergrundtool ist als Favorit gespeichert und erscheint in der Favoritenliste."
            )
        elif row["is_favorite"]:
            favorite_hint = (
                " Dieses Tool ist als Favorit gespeichert und bleibt als Merkliste im Master-Katalog sichtbar."
            )

        if about_text and about_text != row["description"]:
            self.about_label.setText(about_text + favorite_hint)
        elif row["tool_type"] == "background":
            self.about_label.setText(
                "Dieses Modul ist als Hintergrundtool vorgesehen. Nach der Installation kann es bei Bedarf aktiviert werden, "
                "um Kontextmenues oder stille Hilfsfunktionen bereitzustellen."
                + favorite_hint
            )
        else:
            self.about_label.setText(
                "Dieses Modul wird bei Bedarf separat installiert und erst danach in QGIS aktiviert. "
                "Sobald es im lokalen QGIS-Profil liegt, kann der Master auch Aktualisieren und Entfernen uebernehmen."
                + favorite_hint
            )

        self.category_value.setText(row["category"] or "-")
        self.type_value.setText(row["tool_type_label"] or "-")
        self.favorite_value.setText("")
        self.favorite_value.setPixmap(
            self._favorite_icon(row["is_favorite"]).pixmap(18, 18)
        )
        self.favorite_value.setToolTip(
            "Favorit gespeichert" if row["is_favorite"] else "Nicht als Favorit gespeichert"
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
                f"<a href=\"{escape(row['homepage'])}\">Homepage</a>"
            )
        if row["tracker"]:
            links.append(
                f"<a href=\"{escape(row['tracker'])}\">Fehlerverfolgung</a>"
            )
        if row["repository"]:
            links.append(
                f"<a href=\"{escape(row['repository'])}\">Coderepository</a>"
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
            "Aus Favoriten entfernen" if is_favorite else "Als Favorit speichern"
        )
        self.favorite_button.setStatusTip(self.favorite_button.toolTip())
