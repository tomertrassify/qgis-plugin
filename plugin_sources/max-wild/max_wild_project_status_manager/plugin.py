import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QDate, QSettings, Qt
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QAction,
    QCalendarWidget,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabWidget,
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
STATUS_STYLES = {
    "Neu": {
        "background": "#d9ebff",
        "foreground": "#0b4f8a",
        "border": "#8ec0f7",
    },
    "in Arbeit": {
        "background": "#ffe3bf",
        "foreground": "#8a4b08",
        "border": "#f4b368",
    },
    "Fehlende Betreiber Antwort": {
        "background": "#ffd6d6",
        "foreground": "#8d1f1f",
        "border": "#f0a1a1",
    },
    "Fertig": {
        "background": "#d6f5df",
        "foreground": "#1b6b3b",
        "border": "#92d2a8",
    },
}
DEFAULT_STATUS_STYLE = {
    "background": "#ece8df",
    "foreground": "#4a4338",
    "border": "#cdbfa9",
}
SHARE_URL_PATTERN = re.compile(r"/(?:index\.php/)?s/([^/?#]+)")
NEXTCLOUD_SETTINGS_PREFIX = "TrassifyMasterTools/shared_settings"
NEXTCLOUD_LIST_KEYS = {"local_nextcloud_roots"}
DEFAULT_NEXTCLOUD_SETTINGS = {
    "nextcloud_base_url": "https://nextcloud.trassify.cloud",
    "nextcloud_user": "",
    "nextcloud_app_password": "",
    "local_nextcloud_roots": [],
    "nextcloud_folder_marker": "Nextcloud",
}
NEXTCLOUD_SHARE_CACHE = {}
DEFAULT_CLICKUP_SETTINGS = {
    "clickup_api_token": "",
    "clickup_list_id": "",
}
CLICKUP_API_BASE_URL = "https://api.clickup.com/api/v2"
CLICKUP_TASKS_CACHE = {}
CLICKUP_LIST_CACHE = {}
CLICKUP_STATUS_ALIASES = {
    "Neu": ("neu", "to do", "todo", "open"),
    "in Arbeit": ("in arbeit", "in progress", "in bearbeitung", "working on it"),
    "Fehlende Betreiber Antwort": (
        "fehlende betreiber antwort",
        "awaiting operator response",
        "waiting for operator response",
        "operator response missing",
    ),
    "Fertig": ("fertig", "done", "complete", "completed", "closed"),
}


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

    raise ValueError(f"Ungueltiges Datum '{text}'. Erwartet wird dd.MM.yyyy.")


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


def parse_string_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    if value is None:
        return []

    text = str(value).strip()
    if not text:
        return []

    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]

    return [line.strip() for line in text.splitlines() if line.strip()]


def normalize_nextcloud_settings(config):
    source = config or {}
    normalized = dict(DEFAULT_NEXTCLOUD_SETTINGS)

    for key, default in DEFAULT_NEXTCLOUD_SETTINGS.items():
        value = source.get(key, default)
        if key in NEXTCLOUD_LIST_KEYS:
            normalized[key] = parse_string_list(value)
        else:
            normalized[key] = str(value or "").strip()

    return normalized


def load_nextcloud_settings_from_qsettings():
    settings = QSettings()
    loaded = dict(DEFAULT_NEXTCLOUD_SETTINGS)

    for key, default in DEFAULT_NEXTCLOUD_SETTINGS.items():
        full_key = f"{NEXTCLOUD_SETTINGS_PREFIX}/{key}"
        if not settings.contains(full_key):
            continue
        raw = settings.value(full_key, default)
        if key in NEXTCLOUD_LIST_KEYS:
            loaded[key] = parse_string_list(raw)
        else:
            loaded[key] = str(raw or "").strip()

    return normalize_nextcloud_settings(loaded)


def normalize_clickup_settings(config):
    source = config or {}
    normalized = dict(DEFAULT_CLICKUP_SETTINGS)

    for key, default in DEFAULT_CLICKUP_SETTINGS.items():
        normalized[key] = str(source.get(key, default) or "").strip()

    return normalized


def load_clickup_settings_from_qsettings():
    settings = QSettings()
    loaded = dict(DEFAULT_CLICKUP_SETTINGS)

    for key, default in DEFAULT_CLICKUP_SETTINGS.items():
        full_key = f"{NEXTCLOUD_SETTINGS_PREFIX}/{key}"
        if not settings.contains(full_key):
            continue
        loaded[key] = str(settings.value(full_key, default) or "").strip()

    return normalize_clickup_settings(loaded)


def status_style_for(status_text):
    normalized = normalize_status_value(status_text)
    return STATUS_STYLES.get(normalized, DEFAULT_STATUS_STYLE)


def map_clickup_status_to_plugin(status_text):
    normalized = str(status_text or "").strip().casefold()
    if not normalized:
        return ""

    for plugin_status, aliases in CLICKUP_STATUS_ALIASES.items():
        if normalized == plugin_status.casefold():
            return plugin_status
        if normalized in aliases:
            return plugin_status
    return ""


def extract_nextcloud_share_token(share_url):
    match = SHARE_URL_PATTERN.search(str(share_url or "").strip())
    if not match:
        return ""
    return match.group(1).strip()


def _normalize_path(path):
    normalized = str(path or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("file://"):
        parsed = urllib.parse.urlparse(normalized)
        normalized = urllib.parse.unquote(parsed.path or "")
    normalized = normalized.replace("\\", "/")
    return re.sub(r"/{2,}", "/", normalized)


def _join_root_and_relative(root, relative_nc_path):
    return root.rstrip("/") + "/" + relative_nc_path.lstrip("/")


def _canonical_nextcloud_path(nc_path):
    normalized = _normalize_path(nc_path)
    if not normalized:
        return ""

    canonical = "/" + normalized.lstrip("/")
    if canonical != "/":
        canonical = canonical.rstrip("/")
    return canonical


def _nextcloud_path_variants(nc_path):
    canonical = _canonical_nextcloud_path(nc_path)
    if not canonical:
        return []

    variants = [canonical]
    if canonical != "/":
        without_leading = canonical.lstrip("/")
        if without_leading and without_leading != canonical:
            variants.append(without_leading)

    unique = []
    seen = set()
    for candidate in variants:
        token = str(candidate or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        unique.append(token)
    return unique


def _share_path_bases(canonical_path, config):
    if not canonical_path or canonical_path == "/":
        return []

    candidates = [_canonical_nextcloud_path(canonical_path)]
    root_folder_names = []
    for root in config.get("local_nextcloud_roots", []) or []:
        base_name = os.path.basename(_normalize_path(root).rstrip("/"))
        token = str(base_name or "").strip().strip("/")
        if token:
            root_folder_names.append(token)

    path_body = canonical_path.lstrip("/")
    first_segment = path_body.split("/", 1)[0] if path_body else ""
    remainder = path_body[len(first_segment):] if first_segment else ""

    for folder_name in root_folder_names:
        prefixed = _canonical_nextcloud_path(f"/{folder_name}/{path_body}")
        if prefixed:
            candidates.append(prefixed)
        if first_segment and first_segment.casefold() == folder_name.casefold():
            stripped = _canonical_nextcloud_path("/" + remainder.lstrip("/"))
            if stripped and stripped != "/":
                candidates.append(stripped)

    unique = []
    seen = set()
    for candidate in candidates:
        canonical = _canonical_nextcloud_path(candidate)
        if not canonical or canonical == "/" or canonical in seen:
            continue
        seen.add(canonical)
        unique.append(canonical)
    return unique


def _share_request_paths(canonical_path, config):
    request_paths = []
    for base_path in _share_path_bases(canonical_path, config):
        request_paths.extend(_nextcloud_path_variants(base_path))

    unique = []
    seen = set()
    for candidate in request_paths:
        token = str(candidate or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        unique.append(token)
    return unique


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _to_int(value, default=-1):
    try:
        return int(value)
    except Exception:
        return default


def _extract_public_share_url(ocs_payload, accepted_paths=None):
    accepted = {path for path in (accepted_paths or set()) if path and path != "/"}
    for entry in _as_list(ocs_payload.get("ocs", {}).get("data")):
        if _to_int(entry.get("share_type")) != 3:
            continue
        if accepted:
            entry_path = _canonical_nextcloud_path(str(entry.get("path", "") or ""))
            if entry_path not in accepted:
                continue
        url = str(entry.get("url") or "").strip()
        if url:
            return url
    return ""


def _to_nextcloud_and_local_path(raw_path, config):
    if not raw_path:
        return None, None

    path = _normalize_path(raw_path)
    if not path:
        return None, None

    roots = [_normalize_path(root).rstrip("/") for root in config.get("local_nextcloud_roots", []) if root]
    lower_path = path.casefold()

    for root in roots:
        lower_root = root.casefold()
        if lower_path == lower_root or lower_path.startswith(lower_root + "/"):
            tail = path[len(root):]
            if not tail.startswith("/"):
                tail = "/" + tail
            return tail, _join_root_and_relative(root, tail)

    for root in roots:
        root_name = os.path.basename(root)
        if not root_name:
            continue
        index = lower_path.find(root_name.casefold())
        if index < 0:
            continue
        tail = path[index + len(root_name):]
        if not tail.startswith("/"):
            tail = "/" + tail
        return tail, _join_root_and_relative(root, tail)

    marker = str(config.get("nextcloud_folder_marker", "Nextcloud")).strip("/")
    if marker:
        token = "/" + marker.casefold() + "/"
        marker_pos = lower_path.find(token)
        if marker_pos >= 0:
            tail = path[marker_pos + len(token):]
            tail = "/" + tail.lstrip("/")
            base = roots[0] if roots else ""
            abs_path = _join_root_and_relative(base, tail) if base else tail
            return tail, abs_path

    return None, None


def _ocs_request(config, method, endpoint_url, params=None, data=None):
    all_params = {"format": "json"}
    if params:
        all_params.update(params)

    query = urllib.parse.urlencode(all_params, doseq=True)
    url = f"{endpoint_url}?{query}"

    user = config["nextcloud_user"]
    app_password = config["nextcloud_app_password"]
    encoded_auth = base64.b64encode(f"{user}:{app_password}".encode("utf-8")).decode("ascii")

    headers = {
        "Authorization": f"Basic {encoded_auth}",
        "OCS-APIRequest": "true",
        "Accept": "application/json",
    }

    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    request = urllib.request.Request(url=url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        response_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Nextcloud HTTP {exc.code}: {response_text}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Nextcloud nicht erreichbar: {exc}") from exc

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ungueltige API-Antwort: {payload[:300]}") from exc

    meta = parsed.get("ocs", {}).get("meta", {})
    status = int(meta.get("statuscode", 0) or 0)
    if status not in (100, 200):
        message = meta.get("message", "Unbekannt")
        raise RuntimeError(f"Nextcloud API-Fehler {status}: {message}")

    return parsed


def get_or_create_public_link(config, nc_path):
    canonical_path = _canonical_nextcloud_path(nc_path)
    if not canonical_path:
        raise RuntimeError("Leerer Nextcloud-Pfad fuer Share-Link.")
    if canonical_path == "/":
        raise RuntimeError("Der Nextcloud-Root kann nicht als oeffentlicher Link geteilt werden.")

    cache_key = (
        str(config.get("nextcloud_base_url", "")).rstrip("/"),
        str(config.get("nextcloud_user", "")).strip(),
        canonical_path,
    )
    cached = NEXTCLOUD_SHARE_CACHE.get(cache_key)
    if cached:
        return cached

    base_url = str(config["nextcloud_base_url"]).rstrip("/")
    endpoints = (
        f"{base_url}/ocs/v2.php/apps/files_sharing/api/v1/shares",
        f"{base_url}/ocs/v1.php/apps/files_sharing/api/v1/shares",
    )
    request_paths = _share_request_paths(canonical_path, config)
    accepted_paths = {
        _canonical_nextcloud_path(path)
        for path in request_paths
        if _canonical_nextcloud_path(path) and _canonical_nextcloud_path(path) != "/"
    }
    if not request_paths:
        raise RuntimeError(f"Kein gueltiger Nextcloud-Pfad fuer Share-Link: '{canonical_path}'")

    errors = []

    for endpoint in endpoints:
        for candidate_path in request_paths:
            try:
                existing = _ocs_request(
                    config=config,
                    method="GET",
                    endpoint_url=endpoint,
                    params={"path": candidate_path, "reshares": "true", "subfiles": "false"},
                )
                link = _extract_public_share_url(
                    existing,
                    accepted_paths={_canonical_nextcloud_path(candidate_path)},
                )
                if link:
                    NEXTCLOUD_SHARE_CACHE[cache_key] = link
                    return link
            except Exception as exc:
                errors.append(f"GET {endpoint} path='{candidate_path}' -> {exc}")

        try:
            existing_all = _ocs_request(
                config=config,
                method="GET",
                endpoint_url=endpoint,
                params={"reshares": "true"},
            )
            link = _extract_public_share_url(existing_all, accepted_paths=accepted_paths)
            if link:
                NEXTCLOUD_SHARE_CACHE[cache_key] = link
                return link
        except Exception as exc:
            errors.append(f"GET {endpoint} all(reshares=true) -> {exc}")

        for candidate_path in request_paths:
            try:
                created = _ocs_request(
                    config=config,
                    method="POST",
                    endpoint_url=endpoint,
                    data={"path": candidate_path, "shareType": "3", "permissions": "1"},
                )
                link = str((created.get("ocs", {}).get("data") or {}).get("url") or "").strip()
                if link:
                    NEXTCLOUD_SHARE_CACHE[cache_key] = link
                    return link
            except Exception as exc:
                errors.append(f"POST {endpoint} path='{candidate_path}' -> {exc}")

    detail = errors[-1] if errors else "Unbekannter Fehler"
    raise RuntimeError(f"Kein Share-Link erzeugt fuer '{canonical_path}'. Letzter Fehler: {detail}")


def _clickup_request(config, method, endpoint, params=None, data=None):
    token = str(config.get("clickup_api_token", "")).strip()
    if not token:
        raise RuntimeError("ClickUp-Token fehlt.")

    base_url = CLICKUP_API_BASE_URL.rstrip("/")
    path = str(endpoint or "").strip().lstrip("/")
    url = f"{base_url}/{path}"
    if params:
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{url}?{query}"

    headers = {
        "Authorization": token,
        "Accept": "application/json",
    }
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url=url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        response_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ClickUp HTTP {exc.code}: {response_text}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"ClickUp nicht erreichbar: {exc}") from exc

    try:
        return json.loads(payload) if payload else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ungueltige ClickUp-Antwort: {payload[:300]}") from exc


def _clickup_cache_key(config):
    return (
        str(config.get("clickup_api_token", "")).strip(),
        str(config.get("clickup_list_id", "")).strip(),
    )


def invalidate_clickup_cache(config):
    cache_key = _clickup_cache_key(config)
    CLICKUP_TASKS_CACHE.pop(cache_key, None)
    CLICKUP_LIST_CACHE.pop(cache_key, None)


def get_clickup_list_info(config):
    list_id = str(config.get("clickup_list_id", "")).strip()
    if not list_id:
        raise RuntimeError("ClickUp-Listen-ID fehlt.")

    cache_key = _clickup_cache_key(config)
    cached = CLICKUP_LIST_CACHE.get(cache_key)
    if cached is not None:
        return cached

    payload = _clickup_request(config, "GET", f"list/{list_id}")
    CLICKUP_LIST_CACHE[cache_key] = payload
    return payload


def get_clickup_tasks(config):
    list_id = str(config.get("clickup_list_id", "")).strip()
    if not list_id:
        raise RuntimeError("ClickUp-Listen-ID fehlt.")

    cache_key = _clickup_cache_key(config)
    cached = CLICKUP_TASKS_CACHE.get(cache_key)
    if cached is not None:
        return list(cached)

    tasks = []
    page = 0
    while True:
        payload = _clickup_request(
            config,
            "GET",
            f"list/{list_id}/task",
            params={"page": page, "include_closed": "true", "subtasks": "true"},
        )
        chunk = payload.get("tasks") or []
        tasks.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1

    CLICKUP_TASKS_CACHE[cache_key] = list(tasks)
    return tasks


def task_map_by_id(tasks):
    return {
        str(task.get("id") or "").strip(): task
        for task in tasks
        if str(task.get("id") or "").strip()
    }


def resolve_clickup_status_name(config, plugin_status):
    target = normalize_status_value(plugin_status)
    list_info = get_clickup_list_info(config)
    available_statuses = list_info.get("statuses") or []
    normalized_map = {}

    for entry in available_statuses:
        status_name = str(entry.get("status") or entry.get("name") or "").strip()
        if status_name:
            normalized_map[status_name.casefold()] = status_name

    if target.casefold() in normalized_map:
        return normalized_map[target.casefold()]

    for alias in CLICKUP_STATUS_ALIASES.get(target, ()):
        if alias in normalized_map:
            return normalized_map[alias]

    raise RuntimeError(
        f"Kein passender ClickUp-Status fuer '{target}' in Liste {config.get('clickup_list_id', '')} gefunden."
    )


def update_clickup_task_status(config, task_id, plugin_status):
    clickup_status = resolve_clickup_status_name(config, plugin_status)
    _clickup_request(
        config,
        "PUT",
        f"task/{task_id}",
        data={"status": clickup_status},
    )
    invalidate_clickup_cache(config)


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


class ClickUpTaskPickerDialog(QDialog):
    def __init__(self, tasks, project_name="", selected_task_id="", parent=None):
        super().__init__(parent)
        self.tasks = sorted(
            list(tasks or []),
            key=lambda task: str(task.get("name") or "").casefold(),
        )
        self.selected_task = None
        self.selected_task_id = str(selected_task_id or "").strip()

        self.setWindowTitle(f"ClickUp-Task verknuepfen | {project_name}".strip(" |"))
        self.resize(760, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.filter_input = QLineEdit(self)
        self.filter_input.setPlaceholderText("Taskname oder Status filtern")
        self.filter_input.textChanged.connect(lambda _text: self._populate_items())
        layout.addWidget(self.filter_input)

        self.list_widget = QListWidget(self)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.list_widget, 1)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=self,
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self._populate_items()

    def _populate_items(self):
        needle = self.filter_input.text().strip().casefold()
        self.list_widget.clear()
        preselect_row = -1

        for task in self.tasks:
            task_id = str(task.get("id") or "").strip()
            task_name = str(task.get("name") or "").strip() or "(ohne Namen)"
            raw_status = task.get("status") or {}
            task_status = (
                str(raw_status.get("status") or raw_status.get("name") or "").strip()
                if isinstance(raw_status, dict)
                else str(raw_status or "").strip()
            )
            row_text = f"{task_name} {task_status} {task_id}".casefold()
            if needle and needle not in row_text:
                continue

            label = task_name
            if task_status:
                label = f"{label} [{task_status}]"

            item = QListWidgetItem(label, self.list_widget)
            item.setData(Qt.UserRole, task)
            item.setToolTip(task_id)

            if task_id and task_id == self.selected_task_id:
                preselect_row = self.list_widget.count() - 1

        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(preselect_row if preselect_row >= 0 else 0)

    def selected_task_data(self):
        item = self.list_widget.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def accept(self):
        self.selected_task = self.selected_task_data()
        if self.selected_task is None:
            QMessageBox.warning(self, "ClickUp", "Bitte einen Task auswaehlen.")
            return
        super().accept()


class ProjectStatusManagerDialog(QDialog):
    TAB_ACTIVE = "active"
    TAB_ALL = "all"

    COLUMN_PROJECT = 0
    COLUMN_STATUS_URL = 1
    COLUMN_STATUS = 2
    COLUMN_DOWNLOAD_TOKEN = 3
    COLUMN_BAUBEGINN = 4
    COLUMN_CLICKUP = 5
    COLUMN_NEXTCLOUD = 6

    def __init__(self, plugin, parent=None):
        super().__init__(parent or plugin.iface.mainWindow())
        self.plugin = plugin
        self.projects = []
        self.projects_by_key = {}
        self.tables = {}
        self.row_lookup = {
            self.TAB_ACTIVE: {},
            self.TAB_ALL: {},
        }
        self.widget_lookup = {
            self.TAB_ACTIVE: {},
            self.TAB_ALL: {},
        }

        self.setWindowTitle("Projektstatus Butler")
        self.setWindowIcon(QIcon(str(plugin._icon_path())))
        self.resize(1580, 920)

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
        self.filter_input.setPlaceholderText("Nach Projektname, Status, Token, Datum oder URL filtern")
        self.filter_input.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.filter_input, 1)

        self.summary_label = QLabel("", self)
        filter_row.addWidget(self.summary_label)

        self.reload_button = QPushButton("Neu laden", self)
        self.reload_button.clicked.connect(self.reload_rows)
        filter_row.addWidget(self.reload_button)

        self.clickup_pull_button = QPushButton("Status von ClickUp laden", self)
        self.clickup_pull_button.clicked.connect(self._pull_statuses_from_clickup)
        filter_row.addWidget(self.clickup_pull_button)

        root_layout.addLayout(filter_row)

        self.tab_widget = QTabWidget(self)
        self.tab_widget.currentChanged.connect(lambda _index: self._apply_filters())
        root_layout.addWidget(self.tab_widget, 1)

        self.active_page = QWidget(self.tab_widget)
        active_layout = QVBoxLayout(self.active_page)
        active_layout.setContentsMargins(0, 0, 0, 0)
        self.active_table = self._build_table(self.TAB_ACTIVE)
        active_layout.addWidget(self.active_table)
        self.tab_widget.addTab(self.active_page, "Aktive Projekte")

        self.all_page = QWidget(self.tab_widget)
        all_layout = QVBoxLayout(self.all_page)
        all_layout.setContentsMargins(0, 0, 0, 0)
        self.all_table = self._build_table(self.TAB_ALL)
        all_layout.addWidget(self.all_table)
        self.tab_widget.addTab(self.all_page, "Alle")

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Close,
            parent=self,
        )
        self.button_box.accepted.connect(self.save_rows)
        self.button_box.rejected.connect(self.reject)
        root_layout.addWidget(self.button_box)

        self.reload_rows()

    def _build_table(self, table_key):
        table = QTableWidget(self)
        table.setColumnCount(7)
        table.setHorizontalHeaderLabels(
            (
                "Projektordner",
                "Status URL",
                "Status",
                "Download Token",
                "Baubeginn",
                "ClickUp",
                "Nextcloud",
            )
        )
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.SelectedClicked
        )
        table.verticalHeader().setVisible(False)
        table.itemChanged.connect(
            lambda item, source=table_key: self._handle_item_changed(source, item)
        )

        header = table.horizontalHeader()
        header.setSectionResizeMode(self.COLUMN_PROJECT, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COLUMN_STATUS_URL, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COLUMN_STATUS, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COLUMN_DOWNLOAD_TOKEN, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COLUMN_BAUBEGINN, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COLUMN_CLICKUP, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COLUMN_NEXTCLOUD, QHeaderView.ResizeToContents)

        self.tables[table_key] = table
        return table

    def reload_rows(self):
        try:
            loaded_projects = self.plugin.load_projects()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Projektstatus Butler",
                f"Projektordner konnten nicht geladen werden:\n{exc}",
            )
            return

        self.projects = []
        for project in loaded_projects:
            key = str(project["status_path"])
            working_copy = self._working_copy(project["data"])
            self.projects.append(
                {
                    **project,
                    "key": key,
                    "edited_data": working_copy,
                    "share_url": "",
                }
            )
        self.projects_by_key = {project["key"]: project for project in self.projects}

        self.row_lookup = {
            self.TAB_ACTIVE: {},
            self.TAB_ALL: {},
        }
        self.widget_lookup = {
            self.TAB_ACTIVE: {},
            self.TAB_ALL: {},
        }

        for table_key, table in self.tables.items():
            table.setUpdatesEnabled(False)
            table.blockSignals(True)
            table.setRowCount(0)

            for row_index, project in enumerate(self.projects):
                table.insertRow(row_index)
                self.row_lookup[table_key][project["key"]] = row_index
                self._populate_row(table_key, row_index, project)

            table.blockSignals(False)
            table.setUpdatesEnabled(True)

        self._apply_filters()

    def _working_copy(self, data):
        return {
            "statusUrl": str(data.get("statusUrl", "") or "").strip(),
            "status": normalize_status_value(data.get("status", "")),
            "downloadToken": str(data.get("downloadToken", "") or "").strip(),
            "baubeginn": display_date_text(data.get("baubeginn", "")),
            "clickupTaskId": str(data.get("clickupTaskId", "") or "").strip(),
            "clickupTaskName": str(data.get("clickupTaskName", "") or "").strip(),
        }

    def _populate_row(self, table_key, row_index, project):
        table = self.tables[table_key]
        edited = project["edited_data"]

        project_item = QTableWidgetItem(project["name"])
        project_item.setFlags(project_item.flags() & ~Qt.ItemIsEditable)
        project_item.setData(Qt.UserRole, project["key"])
        project_item.setToolTip(str(project["status_path"]))
        table.setItem(row_index, self.COLUMN_PROJECT, project_item)

        status_url_item = QTableWidgetItem(edited.get("statusUrl", ""))
        status_url_item.setData(Qt.UserRole, project["key"])
        table.setItem(row_index, self.COLUMN_STATUS_URL, status_url_item)

        status_box = QComboBox(table)
        current_status = normalize_status_value(edited.get("status", ""))
        if current_status and current_status not in STATUS_OPTIONS:
            status_box.addItem(current_status)
        status_box.addItems(STATUS_OPTIONS)
        status_box.setCurrentText(current_status or "Neu")
        status_box.currentTextChanged.connect(
            lambda text, key=project["key"], source=table_key: self._handle_status_changed(
                key,
                text,
                source,
            )
        )
        self._apply_status_combo_style(status_box, status_box.currentText())
        table.setCellWidget(row_index, self.COLUMN_STATUS, status_box)

        download_token_item = QTableWidgetItem(edited.get("downloadToken", ""))
        download_token_item.setData(Qt.UserRole, project["key"])
        download_token_item.setToolTip(project.get("share_url", ""))
        table.setItem(row_index, self.COLUMN_DOWNLOAD_TOKEN, download_token_item)

        date_widget = DateInputWidget(table)
        date_widget.set_optional_text(edited.get("baubeginn", ""))
        date_widget.line_edit.textChanged.connect(
            lambda _text, key=project["key"], source=table_key, widget=date_widget: self._handle_date_changed(
                key,
                widget.optional_text(),
                source,
            )
        )
        table.setCellWidget(row_index, self.COLUMN_BAUBEGINN, date_widget)

        clickup_button = QPushButton(table)
        clickup_button.clicked.connect(
            lambda _checked=False, key=project["key"]: self._choose_clickup_task_for_project(key)
        )
        table.setCellWidget(row_index, self.COLUMN_CLICKUP, clickup_button)

        share_button = QPushButton(table)
        share_button.clicked.connect(
            lambda _checked=False, key=project["key"]: self._choose_nextcloud_folder_for_token(key)
        )
        table.setCellWidget(row_index, self.COLUMN_NEXTCLOUD, share_button)

        self.widget_lookup[table_key][project["key"]] = {
            "status_box": status_box,
            "date_widget": date_widget,
            "clickup_button": clickup_button,
            "share_button": share_button,
        }
        self._update_clickup_button(project["key"])
        self._update_share_button(project["key"])

    def _apply_status_combo_style(self, combo_box, status_text):
        current_style = status_style_for(status_text)
        combo_box.setStyleSheet(
            "QComboBox {"
            f"background: {current_style['background']};"
            f"color: {current_style['foreground']};"
            f"border: 1px solid {current_style['border']};"
            "border-radius: 6px;"
            "padding: 4px 8px;"
            "font-weight: 600;"
            "}"
        )

        for index in range(combo_box.count()):
            item_text = combo_box.itemText(index)
            item_style = status_style_for(item_text)
            combo_box.setItemData(index, QColor(item_style["background"]), Qt.BackgroundRole)
            combo_box.setItemData(index, QColor(item_style["foreground"]), Qt.ForegroundRole)

    def _handle_item_changed(self, table_key, item):
        if item is None:
            return

        project_key = item.data(Qt.UserRole)
        if not project_key:
            return

        if item.column() == self.COLUMN_STATUS_URL:
            self._set_project_field(
                project_key,
                "statusUrl",
                item.text().strip(),
                origin_table=table_key,
            )
        elif item.column() == self.COLUMN_DOWNLOAD_TOKEN:
            self._set_project_field(
                project_key,
                "downloadToken",
                item.text().strip(),
                origin_table=table_key,
            )

    def _handle_status_changed(self, project_key, status_text, origin_table):
        normalized = normalize_status_value(status_text)
        self._set_project_field(
            project_key,
            "status",
            normalized,
            origin_table=origin_table,
        )

    def _handle_date_changed(self, project_key, raw_text, origin_table):
        self._set_project_field(
            project_key,
            "baubeginn",
            str(raw_text or "").strip(),
            origin_table=origin_table,
        )

    def _set_project_field(self, project_key, field_name, value, origin_table=None, share_url=None):
        project = self.projects_by_key.get(project_key)
        if project is None:
            return

        project["edited_data"][field_name] = value
        if field_name == "downloadToken" and share_url is None:
            project["share_url"] = ""
        elif share_url is not None:
            project["share_url"] = share_url

        if field_name == "statusUrl":
            for table_key in self.tables:
                if table_key == origin_table:
                    continue
                self._set_table_item_text(table_key, project_key, self.COLUMN_STATUS_URL, value)
        elif field_name == "downloadToken":
            tooltip = project.get("share_url", "")
            for table_key in self.tables:
                if table_key == origin_table:
                    continue
                self._set_table_item_text(
                    table_key,
                    project_key,
                    self.COLUMN_DOWNLOAD_TOKEN,
                    value,
                    tooltip=tooltip,
                )
            if origin_table in self.tables:
                self._set_item_tooltip(origin_table, project_key, self.COLUMN_DOWNLOAD_TOKEN, tooltip)
        elif field_name == "status":
            for table_key in self.tables:
                widget = self.widget_lookup.get(table_key, {}).get(project_key, {}).get("status_box")
                if widget is None:
                    continue
                self._set_combo_value(widget, value, update_style=True)
        elif field_name == "baubeginn":
            for table_key in self.tables:
                if table_key == origin_table:
                    continue
                widget = self.widget_lookup.get(table_key, {}).get(project_key, {}).get("date_widget")
                if widget is None:
                    continue
                self._set_date_widget_value(widget, value)
        elif field_name in {"clickupTaskId", "clickupTaskName"}:
            self._update_clickup_button(project_key)

        self._update_share_button(project_key)
        self._apply_filters()

    def _set_table_item_text(self, table_key, project_key, column, value, tooltip=None):
        table = self.tables.get(table_key)
        row_index = self.row_lookup.get(table_key, {}).get(project_key)
        if table is None or row_index is None:
            return

        item = table.item(row_index, column)
        if item is None:
            return

        previous = table.signalsBlocked()
        table.blockSignals(True)
        item.setText(str(value or ""))
        if tooltip is not None:
            item.setToolTip(str(tooltip or ""))
        table.blockSignals(previous)

    def _set_item_tooltip(self, table_key, project_key, column, tooltip):
        table = self.tables.get(table_key)
        row_index = self.row_lookup.get(table_key, {}).get(project_key)
        if table is None or row_index is None:
            return

        item = table.item(row_index, column)
        if item is None:
            return
        item.setToolTip(str(tooltip or ""))

    def _set_combo_value(self, combo_box, value, update_style=False):
        previous = combo_box.blockSignals(True)
        if combo_box.findText(value) < 0:
            combo_box.addItem(value)
        combo_box.setCurrentText(value)
        combo_box.blockSignals(previous)
        if update_style:
            self._apply_status_combo_style(combo_box, value)

    def _set_date_widget_value(self, date_widget, value):
        previous = date_widget.line_edit.blockSignals(True)
        date_widget.set_optional_text(value)
        date_widget.line_edit.blockSignals(previous)

    def _project_row_text(self, project):
        edited = project["edited_data"]
        parts = [
            project["name"],
            edited.get("statusUrl", ""),
            edited.get("status", ""),
            edited.get("downloadToken", ""),
            edited.get("baubeginn", ""),
            edited.get("clickupTaskId", ""),
            edited.get("clickupTaskName", ""),
        ]
        return " ".join(str(part or "") for part in parts).casefold()

    def _apply_filters(self):
        needle = str(self.filter_input.text() or "").strip().casefold()
        active_counts = {
            self.TAB_ACTIVE: {"visible": 0, "total": 0},
            self.TAB_ALL: {"visible": 0, "total": 0},
        }

        for table_key, table in self.tables.items():
            for project in self.projects:
                row_index = self.row_lookup.get(table_key, {}).get(project["key"])
                if row_index is None:
                    continue

                status_value = normalize_status_value(project["edited_data"].get("status", ""))
                in_scope = table_key != self.TAB_ACTIVE or status_value != "Fertig"
                matches_text = not needle or needle in self._project_row_text(project)

                if in_scope:
                    active_counts[table_key]["total"] += 1
                visible = in_scope and matches_text
                if visible:
                    active_counts[table_key]["visible"] += 1
                table.setRowHidden(row_index, not visible)

        self.tab_widget.setTabText(
            0,
            (
                f"Aktive Projekte "
                f"({active_counts[self.TAB_ACTIVE]['visible']}/{active_counts[self.TAB_ACTIVE]['total']})"
            ),
        )
        self.tab_widget.setTabText(
            1,
            (
                f"Alle "
                f"({active_counts[self.TAB_ALL]['visible']}/{active_counts[self.TAB_ALL]['total']})"
            ),
        )

        current_tab = self.TAB_ACTIVE if self.tab_widget.currentIndex() == 0 else self.TAB_ALL
        self.summary_label.setText(
            (
                f"{active_counts[current_tab]['visible']} / "
                f"{active_counts[current_tab]['total']} Projekte"
            )
        )

    def _clickup_button_text(self, project):
        task_name = str(project["edited_data"].get("clickupTaskName", "")).strip()
        if task_name:
            return task_name
        if str(project["edited_data"].get("clickupTaskId", "")).strip():
            return "Task verknuepft"
        return "Task verknuepfen..."

    def _update_clickup_button(self, project_key):
        project = self.projects_by_key.get(project_key)
        if project is None:
            return

        button_text = self._clickup_button_text(project)
        task_id = str(project["edited_data"].get("clickupTaskId", "")).strip()
        task_name = str(project["edited_data"].get("clickupTaskName", "")).strip()
        tooltip = (
            f"ClickUp-Task: {task_name or task_id}\nTask-ID: {task_id}"
            if task_id
            else "ClickUp-Task aus der konfigurierten Liste auswaehlen."
        )

        for table_key in self.tables:
            button = self.widget_lookup.get(table_key, {}).get(project_key, {}).get("clickup_button")
            if button is None:
                continue
            button.setText(button_text)
            button.setToolTip(tooltip)

    def _choose_clickup_task_for_project(self, project_key):
        project = self.projects_by_key.get(project_key)
        if project is None:
            return

        config = self.plugin.get_clickup_settings()
        missing = self._missing_clickup_settings(config)
        if missing:
            QMessageBox.warning(
                self,
                "Projektstatus Butler",
                (
                    "Die ClickUp-Konfiguration ist unvollstaendig.\n\n"
                    f"Es fehlen: {', '.join(missing)}\n\n"
                    "Bitte die gemeinsamen ClickUp-Einstellungen in Trassify Master Tools pflegen."
                ),
            )
            return

        try:
            tasks = get_clickup_tasks(config)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Projektstatus Butler",
                f"ClickUp-Tasks konnten nicht geladen werden:\n{exc}",
            )
            return

        dialog = ClickUpTaskPickerDialog(
            tasks=tasks,
            project_name=project["name"],
            selected_task_id=project["edited_data"].get("clickupTaskId", ""),
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted or dialog.selected_task is None:
            return

        selected_task = dialog.selected_task
        task_id = str(selected_task.get("id") or "").strip()
        task_name = str(selected_task.get("name") or "").strip()
        task_status = selected_task.get("status") or {}
        clickup_status = (
            str(task_status.get("status") or task_status.get("name") or "").strip()
            if isinstance(task_status, dict)
            else str(task_status or "").strip()
        )
        plugin_status = map_clickup_status_to_plugin(clickup_status)

        self._set_project_field(project_key, "clickupTaskId", task_id)
        self._set_project_field(project_key, "clickupTaskName", task_name)
        if plugin_status:
            self._set_project_field(project_key, "status", plugin_status)

    def _pull_statuses_from_clickup(self):
        config = self.plugin.get_clickup_settings()
        missing = self._missing_clickup_settings(config)
        if missing:
            QMessageBox.warning(
                self,
                "Projektstatus Butler",
                (
                    "Die ClickUp-Konfiguration ist unvollstaendig.\n\n"
                    f"Es fehlen: {', '.join(missing)}"
                ),
            )
            return

        try:
            tasks = get_clickup_tasks(config)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Projektstatus Butler",
                f"ClickUp-Tasks konnten nicht geladen werden:\n{exc}",
            )
            return

        tasks_by_id = task_map_by_id(tasks)
        updated_count = 0
        unmatched = []
        unsupported = []

        for project in self.projects:
            task_id = str(project["edited_data"].get("clickupTaskId", "")).strip()
            if not task_id:
                continue

            task = tasks_by_id.get(task_id)
            if task is None:
                unmatched.append(project["name"])
                continue

            task_name = str(task.get("name") or "").strip()
            raw_status = task.get("status") or {}
            clickup_status = (
                str(raw_status.get("status") or raw_status.get("name") or "").strip()
                if isinstance(raw_status, dict)
                else str(raw_status or "").strip()
            )
            plugin_status = map_clickup_status_to_plugin(clickup_status)
            if not plugin_status:
                unsupported.append(f"{project['name']} -> {clickup_status or '(leer)'}")
                continue

            self._set_project_field(project["key"], "clickupTaskName", task_name)
            self._set_project_field(project["key"], "status", plugin_status)
            updated_count += 1

        details = [f"{updated_count} Projektstatus(e) aus ClickUp uebernommen."]
        if unmatched:
            details.append(f"Nicht gefunden: {', '.join(unmatched[:6])}")
        if unsupported:
            details.append(f"Nicht gemappt: {', '.join(unsupported[:6])}")

        QMessageBox.information(
            self,
            "Projektstatus Butler",
            "\n\n".join(details),
        )

    def _missing_clickup_settings(self, config):
        missing = []
        if not config.get("clickup_api_token"):
            missing.append("API-Token")
        if not config.get("clickup_list_id"):
            missing.append("Listen-ID")
        return missing

    def _share_button_text(self, project):
        if str(project["edited_data"].get("downloadToken", "")).strip():
            return "Freigabe erneuern..."
        return "Freigabe erstellen..."

    def _update_share_button(self, project_key):
        project = self.projects_by_key.get(project_key)
        if project is None:
            return

        button_text = self._share_button_text(project)
        share_url = project.get("share_url", "")
        tooltip = (
            f"Letzte Freigabe: {share_url}"
            if share_url
            else "Nextcloud-Ordner waehlen, oeffentlichen Link erzeugen und Token eintragen."
        )

        for table_key in self.tables:
            button = self.widget_lookup.get(table_key, {}).get(project_key, {}).get("share_button")
            if button is None:
                continue
            button.setText(button_text)
            button.setToolTip(tooltip)

    def _choose_nextcloud_folder_for_token(self, project_key):
        project = self.projects_by_key.get(project_key)
        if project is None:
            return

        config = self.plugin.get_nextcloud_settings()
        missing = self._missing_nextcloud_settings(config)
        if missing:
            QMessageBox.warning(
                self,
                "Projektstatus Butler",
                (
                    "Die Nextcloud-Konfiguration ist unvollstaendig.\n\n"
                    f"Es fehlen: {', '.join(missing)}\n\n"
                    "Bitte die gemeinsamen Nextcloud-Einstellungen in Trassify Master Tools pflegen."
                ),
            )
            return

        start_dir = self._initial_nextcloud_directory(config)
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            f"Nextcloud-Ordner fuer {project['name']} waehlen",
            start_dir,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not selected_dir:
            return

        try:
            nc_path, _local_path = _to_nextcloud_and_local_path(selected_dir, config)
            if not nc_path:
                raise RuntimeError(
                    "Der gewaehlte Ordner konnte keinem konfigurierten Nextcloud-Sync-Root zugeordnet werden."
                )

            share_url = get_or_create_public_link(config, nc_path)
            token = extract_nextcloud_share_token(share_url)
            if not token:
                raise RuntimeError(f"Kein Token im Share-Link gefunden: {share_url}")

            self._set_project_field(
                project_key,
                "downloadToken",
                token,
                share_url=share_url,
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Projektstatus Butler",
                f"Nextcloud-Freigabe konnte nicht erstellt werden:\n{exc}",
            )
            return

        QMessageBox.information(
            self,
            "Projektstatus Butler",
            (
                f"Der Download-Token fuer '{project['name']}' wurde aus der Nextcloud-Freigabe uebernommen.\n\n"
                "Mit 'Speichern' wird die status.json aktualisiert."
            ),
        )

    def _missing_nextcloud_settings(self, config):
        missing = []
        if not config.get("nextcloud_base_url"):
            missing.append("Nextcloud URL")
        if not config.get("nextcloud_user"):
            missing.append("Benutzer")
        if not config.get("nextcloud_app_password"):
            missing.append("App-Passwort")
        if not config.get("local_nextcloud_roots"):
            missing.append("lokale Sync-Roots")
        return missing

    def _initial_nextcloud_directory(self, config):
        for root in config.get("local_nextcloud_roots", []):
            if os.path.isdir(root):
                return root
        return str(Path.home())

    def save_rows(self):
        updates = []

        for project in self.projects:
            edited = project["edited_data"]

            try:
                normalized_date = normalize_date_text(edited.get("baubeginn", ""))
            except ValueError as exc:
                QMessageBox.warning(
                    self,
                    "Projektstatus Butler",
                    f"{project['name']}: {exc}",
                )
                return

            new_data = self._build_updated_data(
                original_data=project["data"],
                status_url=edited.get("statusUrl", ""),
                status=normalize_status_value(edited.get("status", "")),
                download_token=edited.get("downloadToken", ""),
                baubeginn=normalized_date,
                clickup_task_id=edited.get("clickupTaskId", ""),
                clickup_task_name=edited.get("clickupTaskName", ""),
            )
            updates.append((project, new_data))

        changed_count = 0
        clickup_synced = 0
        clickup_failures = []
        clickup_config = self.plugin.get_clickup_settings()
        clickup_ready = not self._missing_clickup_settings(clickup_config)

        for project, new_data in updates:
            old_status = normalize_status_value(project["data"].get("status", ""))
            new_status = normalize_status_value(new_data.get("status", ""))
            clickup_task_id = str(new_data.get("clickupTaskId", "") or "").strip()

            if new_data == project["data"]:
                continue

            project["status_path"].write_text(
                json.dumps(new_data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            project["data"] = new_data
            changed_count += 1

            if clickup_task_id and old_status != new_status:
                if clickup_ready:
                    try:
                        update_clickup_task_status(clickup_config, clickup_task_id, new_status)
                        clickup_synced += 1
                    except Exception as exc:
                        clickup_failures.append(f"{project['name']}: {exc}")
                else:
                    clickup_failures.append(
                        f"{project['name']}: ClickUp nicht konfiguriert, Status nur lokal gespeichert."
                    )

        message_lines = [f"{changed_count} status.json-Datei(en) gespeichert."]
        if clickup_synced:
            message_lines.append(f"{clickup_synced} ClickUp-Status aktualisiert.")
        if clickup_failures:
            message_lines.append(
                "ClickUp-Probleme:\n" + "\n".join(clickup_failures[:8])
            )

        QMessageBox.information(self, "Projektstatus Butler", "\n\n".join(message_lines))
        self.reload_rows()

    def _build_updated_data(
        self,
        original_data,
        status_url,
        status,
        download_token,
        baubeginn,
        clickup_task_id,
        clickup_task_name,
    ):
        managed_keys = {
            "statusUrl",
            "status",
            "downloadToken",
            "baubeginn",
            "clickupTaskId",
            "clickupTaskName",
        }
        new_data = {}

        if str(status_url or "").strip():
            new_data["statusUrl"] = str(status_url).strip()
        new_data["status"] = status
        if str(download_token or "").strip():
            new_data["downloadToken"] = str(download_token).strip()
        if str(baubeginn or "").strip():
            new_data["baubeginn"] = str(baubeginn).strip()
        if str(clickup_task_id or "").strip():
            new_data["clickupTaskId"] = str(clickup_task_id).strip()
        if str(clickup_task_name or "").strip():
            new_data["clickupTaskName"] = str(clickup_task_name).strip()

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
        self.trassify_master_settings = {}

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

    def set_master_settings(self, shared_settings=None):
        self.trassify_master_settings = dict(shared_settings or {})

    def get_nextcloud_settings(self):
        settings = load_nextcloud_settings_from_qsettings()

        for key, value in normalize_nextcloud_settings(self.trassify_master_settings).items():
            if key in NEXTCLOUD_LIST_KEYS:
                if value:
                    settings[key] = list(value)
            elif str(value or "").strip():
                settings[key] = str(value).strip()

        return normalize_nextcloud_settings(settings)

    def get_clickup_settings(self):
        settings = load_clickup_settings_from_qsettings()

        for key, value in normalize_clickup_settings(self.trassify_master_settings).items():
            if str(value or "").strip():
                settings[key] = str(value).strip()

        return normalize_clickup_settings(settings)

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
