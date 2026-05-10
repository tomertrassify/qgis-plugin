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
        self.auth_hero_path = self.plugin_controller.plugin_dir / "assets" / "nextcloud_login_hero.png"
        self.auth_logo_path = self.plugin_controller.plugin_dir / "assets" / "trassify-logo.png"
        self._catalog_default_size = QSize(1260, 780)
        self._catalog_min_size = QSize(1080, 680)
        self._auth_dialog_size = QSize(566, 430)
        self._dialog_mode = None

        self.setObjectName("masterOverviewDialog")
        self.setWindowTitle("Erweiterungen | Katalog")
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
        auth_page_layout.setContentsMargins(0, 0, 0, 0)
        auth_page_layout.setSpacing(0)
        self.auth_widgets = self._create_auth_card(self.auth_page, compact=True)
        auth_page_layout.addWidget(self.auth_widgets["frame"], 0, Qt.AlignTop | Qt.AlignHCenter)
        self.page_stack.addWidget(self.auth_page)

        self.catalog_page = QWidget(self.page_stack)
        self.catalog_page.setObjectName("catalogPage")
        layout = QHBoxLayout(self.catalog_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar_frame = QFrame(self.catalog_page)
        self.sidebar_frame.setObjectName("sidebarFrame")
        self.sidebar_frame.setFixedWidth(184)
        sidebar_layout = QVBoxLayout(self.sidebar_frame)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        self.filter_list = QListWidget(self.sidebar_frame)
        self.filter_list.setObjectName("filterList")
        self.filter_list.setFrameShape(QFrame.Box)
        self.filter_list.setLineWidth(0)
        self.filter_list.setSpacing(0)
        self.filter_list.setIconSize(QSize(28, 28))
        self.filter_list.setUniformItemSizes(True)
        self.filter_list.currentItemChanged.connect(self._apply_filters)
        sidebar_layout.addWidget(self.filter_list, 1)
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

        workspace_title = QLabel("Plugin-Katalog", self.header_frame)
        workspace_title.setObjectName("workspaceTitleLabel")
        header_text_layout.addWidget(workspace_title)

        workspace_subtitle = QLabel("Verwalten direkt aus dem Mastertool.", self.header_frame)
        workspace_subtitle.setObjectName("workspaceSubtitleLabel")
        workspace_subtitle.setWordWrap(True)
        header_text_layout.addWidget(workspace_subtitle)

        self.catalog_count_badge = QLabel("", self.header_frame)
        self.catalog_count_badge.setObjectName("catalogCountBadge")
        self.catalog_count_badge.setAlignment(Qt.AlignCenter)
        header_top_layout.addWidget(self.catalog_count_badge, 0, Qt.AlignTop)

        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(8)
        header_layout.addLayout(controls_layout)

        self.search_field = QLineEdit(self.header_frame)
        self.search_field.setObjectName("searchField")
        self.search_field.setPlaceholderText("Plugins durchsuchen...")
        self.search_field.setClearButtonEnabled(True)
        self.search_field.textChanged.connect(self._apply_filters)
        controls_layout.addWidget(self.search_field, 1)

        self.access_gate_widgets = self._create_auth_card(self.workspace_frame, compact=False)
        self.access_gate_frame = self.access_gate_widgets["frame"]
        workspace_layout.addWidget(self.access_gate_frame, 0, Qt.AlignHCenter)

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

        self.footer_frame = QFrame(self.workspace_frame)
        self.footer_frame.setObjectName("footerFrame")
        actions_layout = QHBoxLayout(self.footer_frame)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        workspace_layout.addWidget(self.footer_frame)
        button_height = 30

        self.refresh_button = QPushButton("Katalog neu laden", self.footer_frame)
        self.refresh_button.setObjectName("subtleButton")
        self.refresh_button.setFixedHeight(button_height)
        self.refresh_button.clicked.connect(self._refresh_catalog_and_view)
        actions_layout.addWidget(self.refresh_button)

        self.settings_button = QPushButton("Einstellungen", self.footer_frame)
        self.settings_button.setObjectName("subtleButton")
        self.settings_button.setFixedHeight(button_height)
        self.settings_button.clicked.connect(self.plugin_controller.show_settings)
        actions_layout.addWidget(self.settings_button)

        self.catalog_logout_button = QPushButton("Nextcloud abmelden", self.footer_frame)
        self.catalog_logout_button.setObjectName("subtleButton")
        self.catalog_logout_button.setFixedHeight(button_height)
        self.catalog_logout_button.clicked.connect(self._remove_catalog_login)
        actions_layout.addWidget(self.catalog_logout_button)

        actions_layout.addStretch(1)

        self.favorite_button = QToolButton(self.footer_frame)
        self.favorite_button.setObjectName("favoriteButton")
        self.favorite_button.setText("")
        self.favorite_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.favorite_button.setIconSize(QSize(18, 18))
        self.favorite_button.setFixedSize(button_height, button_height)
        self.favorite_button.clicked.connect(self._toggle_selected_favorite)
        actions_layout.addWidget(self.favorite_button)

        self.open_button = QPushButton("Oeffnen", self.footer_frame)
        self.open_button.setObjectName("subtleButton")
        self.open_button.setFixedHeight(button_height)
        self.open_button.clicked.connect(self._open_selected_module)
        self.open_button.hide()
        actions_layout.addWidget(self.open_button)

        self.primary_button = QPushButton("Installieren", self.footer_frame)
        self.primary_button.setObjectName("primaryButton")
        self.primary_button.setFixedHeight(button_height)
        self.primary_button.clicked.connect(self._run_primary_action)
        actions_layout.addWidget(self.primary_button)

        self.secondary_button = QPushButton("Entfernen", self.footer_frame)
        self.secondary_button.setObjectName("secondaryButton")
        self.secondary_button.setFixedHeight(button_height)
        self.secondary_button.clicked.connect(self._run_secondary_action)
        actions_layout.addWidget(self.secondary_button)

        button_box = QDialogButtonBox(QDialogButtonBox.Close, self.footer_frame)
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

    def _create_auth_card(self, parent, compact):
        frame = QFrame(parent)
        frame.setObjectName("authCard")
        frame.setFixedWidth(566)

        card_layout = QVBoxLayout(frame)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        hero_image = QLabel(frame)
        hero_image.setObjectName("authHeroImage")
        hero_image.setFixedHeight(150)
        hero_image.setFixedWidth(566)
        hero_image.setAlignment(Qt.AlignCenter)
        hero_image.setMargin(0)
        hero_image.setPixmap(self._cover_pixmap(self.auth_hero_path, 566, 150))
        card_layout.addWidget(hero_image)

        content_widget = QWidget(frame)
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(28, 20, 28, 24)
        content_layout.setSpacing(12)

        logo_label = QLabel(content_widget)
        logo_label.setObjectName("authLogoLabel")
        logo_label.setAlignment(Qt.AlignCenter)
        logo_label.setPixmap(self._contain_pixmap(self.auth_logo_path, 210, 42))
        content_layout.addWidget(logo_label, 0, Qt.AlignHCenter)

        title_label = QLabel("Willkommen bei Trassify", content_widget)
        title_label.setObjectName("authTitleLabel")
        title_label.setWordWrap(True)
        title_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(title_label)

        intro_label = QLabel(
            "Melde dich mit deinem Trassify-Account an, um Zugriff auf unsere Plugin-Collection zu erhalten.",
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

        login_button = QPushButton("Log In", content_widget)
        login_button.setObjectName("authPrimaryButton")
        login_button.setFixedWidth(132)
        login_button.setFixedHeight(40)
        login_button.clicked.connect(self._start_catalog_login)
        primary_row.addWidget(login_button)
        primary_row.addStretch(1)

        footer_row = QHBoxLayout()
        footer_row.setSpacing(0)
        footer_row.addStretch(1)
        content_layout.addLayout(footer_row)

        refresh_button = QPushButton("Verbindung pruefen", content_widget)
        refresh_button.setObjectName("authTextButton")
        refresh_button.setFlat(True)
        refresh_button.clicked.connect(self._refresh_catalog_login)
        footer_row.addWidget(refresh_button)

        logout_button = QPushButton("Anmeldung entfernen", content_widget)
        logout_button.setObjectName("authTextButton")
        logout_button.setFlat(True)
        logout_button.clicked.connect(self._remove_catalog_login)
        footer_row.addWidget(logout_button)
        footer_row.addStretch(1)

        if compact:
            content_layout.addStretch(1)

        card_layout.addWidget(content_widget)

        return {
            "frame": frame,
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
            self.setMinimumSize(self._auth_dialog_size)
            self.setMaximumSize(self._auth_dialog_size)
            self.resize(self._auth_dialog_size)
            return

        self.setMaximumSize(16777215, 16777215)
        self.setMinimumSize(self._catalog_min_size)
        if self.width() < self._catalog_min_size.width() or self.height() < self._catalog_min_size.height():
            self.resize(self._catalog_default_size)

    def refresh(self):
        self._sync_auth_page()
        if not self.plugin_controller.can_access_catalog():
            self._set_dialog_mode("auth")
            self.page_stack.setCurrentWidget(self.auth_page)
            self.setWindowTitle("Authorize Trassify Tools")
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
            self.setWindowTitle("Erweiterungen | Nextcloud")
            return

        self.page_stack.setCurrentWidget(self.catalog_page)
        self._set_catalog_access_state(True)
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
        default_intro = (
            "Melde dich mit deinem Trassify-Account an, um Zugriff auf unsere Plugin-Collection zu erhalten."
        )

        if can_access:
            title_text = "Nextcloud verbunden"
            intro_text = "Dein Trassify-Konto ist verbunden. Der geschuetzte Plugin-Katalog kann geladen werden."
            login_text = "Erneut anmelden"
        elif status == "authorizing":
            title_text = "Browser-Login laeuft"
            intro_text = "Schliesse die Anmeldung in deinem Browser ab, um die Plugin-Collection freizuschalten."
            login_text = "Browser offen..."
        elif has_saved_login:
            title_text = "Gespeicherte Anmeldung pruefen"
            intro_text = "Es ist bereits eine Anmeldung gespeichert. Du kannst die Verbindung pruefen oder dich neu anmelden."
            login_text = "Neu anmelden"
        else:
            title_text = "Willkommen bei Trassify"
            intro_text = default_intro
            login_text = "Log In"

        for widgets in (self.auth_widgets, self.access_gate_widgets):
            widgets["title"].setText(title_text)
            widgets["intro"].setText(intro_text)
            widgets["login"].setText(login_text)

        status_text = (detail or "").strip()
        show_status = bool(status_text)
        if status == "authorizing" and not show_status:
            status_text = "Warte auf die Rueckmeldung aus Nextcloud."
            show_status = True

        self.auth_widgets["status"].setText(status_text)
        self.access_gate_widgets["status"].setText(status_text)

        account_parts = []
        if display_name:
            account_parts.append(f"<b>Konto:</b> {escape(display_name)}")
        if groups:
            account_parts.append(f"<b>Gruppen:</b> {escape(', '.join(groups))}")
        account_text = "<br>".join(account_parts)
        for widgets in (self.auth_widgets, self.access_gate_widgets):
            widgets["account"].setText(account_text)
            widgets["account"].setTextFormat(Qt.RichText)

        is_authorizing = status == "authorizing"
        for widgets in (self.auth_widgets, self.access_gate_widgets):
            widgets["login"].setEnabled(not is_authorizing)
            widgets["status"].setVisible(show_status)
            widgets["account"].setVisible(bool(account_text))
            widgets["refresh"].setEnabled(has_saved_login and not is_authorizing)
            widgets["refresh"].setVisible(has_saved_login)
            widgets["logout"].setEnabled(has_saved_login and not is_authorizing)
            widgets["logout"].setVisible(has_saved_login)
        self.catalog_logout_button.setEnabled(has_saved_login and not is_authorizing)
        self.catalog_logout_button.setVisible(has_saved_login)

    def _set_catalog_access_state(self, has_access):
        self.sidebar_frame.setVisible(has_access)
        self.header_frame.setVisible(has_access)
        self.content_splitter.setVisible(has_access)
        self.footer_frame.setVisible(has_access)
        self.access_gate_frame.setVisible(not has_access)

    def _sync_empty_catalog_gate(self):
        error_detail = str(
            getattr(self.plugin_controller, "catalog_refresh_error", "") or ""
        ).strip()
        groups = [group for group in self.plugin_controller.auth_groups() if group]
        if error_detail:
            self.access_gate_widgets["title"].setText("Katalog konnte nicht geladen werden")
            self.access_gate_widgets["intro"].setText(
                "Die Anmeldung ist vorhanden, aber der geschuetzte Katalog konnte nicht geladen werden."
            )
            self.access_gate_widgets["status"].setText(error_detail)
            self.access_gate_widgets["status"].setVisible(True)
            return

        self.access_gate_widgets["title"].setText("Keine Plugins verfuegbar")
        self.access_gate_widgets["intro"].setText(
            "Die Anmeldung ist vorhanden, aber aktuell sind keine Plugins fuer dieses Konto sichtbar."
        )
        if groups:
            self.access_gate_widgets["status"].setText(
                f"Keine freigeschalteten Plugins fuer Gruppen: {', '.join(groups)}."
            )
        else:
            self.access_gate_widgets["status"].setText(
                "Keine freigeschalteten Plugins fuer dieses Konto gefunden."
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
                background: #f1f1ef;
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
            QLabel#authStatusCardLabel {
                color: #6f6f6f;
                background: transparent;
                border: none;
                padding: 0 20px;
            }
            QPushButton#authPrimaryButton {
                background: #5d7d4f;
                color: white;
                border: 1px solid #4d6841;
                border-radius: 8px;
                padding: 6px 18px;
                font-size: 14px;
                font-weight: 500;
            }
            QPushButton#authPrimaryButton:hover {
                background: #6a8a5c;
            }
            QPushButton#authPrimaryButton:disabled {
                background: #9cac92;
                border-color: #899880;
                color: #f5f5f5;
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
