from __future__ import annotations

import json

from qgis.PyQt.QtCore import QSettings


SETTINGS_PREFIX = "TrassifyMasterTools/shared_settings"
UI_SETTINGS_PREFIX = "TrassifyMasterTools/ui"
ATTRIBUTION_BUTTLER_PREFIX = "AttributionButler/user_config"

DEFAULT_SHARED_SETTINGS = {
    "workspace_root": "",
    "nextcloud_base_url": "https://nextcloud.trassify.cloud",
    "nextcloud_user": "",
    "nextcloud_app_password": "",
    "local_nextcloud_roots": [],
    "nextcloud_folder_marker": "Nextcloud",
    "database_connection_name": "Standard",
    "database_host": "",
    "database_port": "5432",
    "database_name": "",
    "database_schema": "",
    "database_user": "",
    "database_password": "",
    "database_sslmode": "prefer",
}

LIST_KEYS = {"local_nextcloud_roots"}
ATTRIBUTION_BUTTLER_NEXTCLOUD_KEYS = (
    "nextcloud_base_url",
    "nextcloud_user",
    "nextcloud_app_password",
    "local_nextcloud_roots",
    "nextcloud_folder_marker",
)


def setting_key(name: str) -> str:
    return f"{SETTINGS_PREFIX}/{name}"


def attribution_butler_key(name: str) -> str:
    return f"{ATTRIBUTION_BUTTLER_PREFIX}/{name}"


def ui_setting_key(name: str) -> str:
    return f"{UI_SETTINGS_PREFIX}/{name}"


def load_shared_settings() -> dict:
    settings = QSettings()
    config = dict(DEFAULT_SHARED_SETTINGS)

    for key, default in DEFAULT_SHARED_SETTINGS.items():
        full_key = setting_key(key)
        if not settings.contains(full_key):
            continue

        raw = settings.value(full_key, default)
        if key in LIST_KEYS:
            config[key] = _parse_string_list(raw)
        else:
            config[key] = str(raw or "").strip()

    return config


def has_saved_shared_settings() -> bool:
    settings = QSettings()
    return any(
        settings.contains(setting_key(key))
        for key in DEFAULT_SHARED_SETTINGS
    )


def load_favorite_module_keys() -> list[str]:
    settings = QSettings()
    raw = settings.value(ui_setting_key("favorite_module_keys"), "[]")
    return _parse_string_list(raw)


def save_favorite_module_keys(keys: list[str] | tuple[str, ...]) -> list[str]:
    settings = QSettings()
    normalized = []
    seen = set()

    for key in keys:
        text = str(key or "").strip()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)

    settings.setValue(ui_setting_key("favorite_module_keys"), json.dumps(normalized))
    return normalized


def save_shared_settings(config: dict) -> dict:
    settings = QSettings()
    normalized = normalize_shared_settings(config)

    for key, default in DEFAULT_SHARED_SETTINGS.items():
        value = normalized.get(key, default)
        if key in LIST_KEYS:
            settings.setValue(setting_key(key), json.dumps(value))
        else:
            settings.setValue(setting_key(key), str(value or "").strip())

    return normalized


def normalize_shared_settings(config: dict | None) -> dict:
    source = config or {}
    normalized = dict(DEFAULT_SHARED_SETTINGS)

    for key, default in DEFAULT_SHARED_SETTINGS.items():
        value = source.get(key, default)
        if key in LIST_KEYS:
            normalized[key] = _parse_string_list(value)
        else:
            normalized[key] = str(value or "").strip()

    return normalized


def sync_attribution_butler_settings(config: dict) -> None:
    settings = QSettings()
    normalized = normalize_shared_settings(config)

    for key in ATTRIBUTION_BUTTLER_NEXTCLOUD_KEYS:
        value = normalized.get(key, DEFAULT_SHARED_SETTINGS.get(key))
        if key in LIST_KEYS:
            settings.setValue(attribution_butler_key(key), json.dumps(value))
        else:
            settings.setValue(attribution_butler_key(key), str(value or "").strip())


def build_postgres_ogr_uri(config: dict | None) -> str:
    normalized = normalize_shared_settings(config)
    host = normalized.get("database_host", "")
    database = normalized.get("database_name", "")
    if not host or not database:
        return ""

    parts = [
        f"host='{_escape_uri_value(host)}'",
        f"port='{_escape_uri_value(normalized.get('database_port', '5432') or '5432')}'",
        f"dbname='{_escape_uri_value(database)}'",
        f"sslmode='{_escape_uri_value(normalized.get('database_sslmode', 'prefer') or 'prefer')}'",
    ]

    if normalized.get("database_user"):
        parts.append(f"user='{_escape_uri_value(normalized['database_user'])}'")
    if normalized.get("database_password"):
        parts.append(
            f"password='{_escape_uri_value(normalized['database_password'])}'"
        )
    if normalized.get("database_schema"):
        schema = _escape_uri_value(normalized["database_schema"])
        parts.append(f"schemas='{schema}'")
        parts.append(f"active_schema='{schema}'")

    return "PG:" + " ".join(parts)


def _parse_string_list(value) -> list[str]:
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


def _escape_uri_value(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace("'", "\\'")
