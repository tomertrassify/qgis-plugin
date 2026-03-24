from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from qgis.PyQt.QtCore import Qt, QStringListModel, QSettings
from qgis.PyQt.QtWidgets import QComboBox, QCompleter, QLineEdit, QMessageBox, QWidget
from qgis.core import Qgis, QgsMessageLog, QgsProject, QgsVectorLayer

from .project_profile import expand_config_from_storage, load_layer_profile_config, load_shared_settings


PROPERTY_PREFIX = "nextcloud_form/"
LOCAL_ROOT_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*lokale\s*sync-roots\s*\}\}", flags=re.IGNORECASE)

DEFAULT_CONFIG = {
    "nextcloud_base_url": "https://nextcloud.trassify.cloud",
    "nextcloud_user": "",
    "nextcloud_app_password": "",
    "local_nextcloud_roots": [],
    "nextcloud_folder_marker": "Nextcloud",
    "path_field_name": "quelle_pfad",
    "file_link_field_name": "quelle_1",
    "folder_link_field_name": "quelle_2",
    "name_field_name": "",
    "stand_field_name": "Stand",
    "operator_name_field_name": "Betreiber",
    "operator_contact_field_name": "betr_anspr",
    "operator_phone_field_name": "betr_tel",
    "operator_email_field_name": "betr_email",
    "operator_fault_field_name": "stoer-nr",
    "operator_validity_field_name": "gueltigk",
    "operator_stand_field_name": "Stand",
    "overwrite_existing_values": True,
    "fill_on_form_open": False,
    "operators": [],
    "external_data_sources": [
        {
            "enabled": True,
            "name": "Betreiberliste-beta",
            "source_type": "file",
            "provider": "ogr",
            "source": "{{Lokale Sync-Roots}}/Trassify Allgemein/IT/Betreiberliste-beta.xlsx",
            "table": "",
            "operator_name_field": "Betreiber",
            "contact_name_field": "betr_anspr",
            "phone_field": "betr_tel",
            "email_field": "betr_email",
            "fault_number_field": "stoer-nr",
            "folder_path_field": "",
        }
    ],
}

MASTER_SETTINGS_PREFIX = "TrassifyMasterTools/shared_settings"
USER_CONFIG_KEYS = (
    "nextcloud_base_url",
    "nextcloud_user",
    "nextcloud_app_password",
    "local_nextcloud_roots",
    "nextcloud_folder_marker",
)

_SHARE_CACHE: dict[tuple[str, str, str], str] = {}
_SHARE_BACKOFF_UNTIL: dict[tuple[str, str, str], float] = {}
_DEFAULT_RATE_LIMIT_SECONDS = 60
_NEXTCLOUD_LOG_SEEN: set[str] = set()


class NextcloudRateLimitError(RuntimeError):
    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def _log_nextcloud_warning(message: str):
    text = str(message or "").strip()
    if not text:
        return
    if text in _NEXTCLOUD_LOG_SEEN:
        return
    _NEXTCLOUD_LOG_SEEN.add(text)
    QgsMessageLog.logMessage(text, "AttributionButler", Qgis.Warning)


def _property_key(name: str) -> str:
    return f"{PROPERTY_PREFIX}{name}"


def _master_setting_key(name: str) -> str:
    return f"{MASTER_SETTINGS_PREFIX}/{name}"


def _load_nextcloud_settings_for_prefix(prefix_key_builder) -> dict:
    settings = QSettings()
    cfg = {}
    for key in USER_CONFIG_KEYS:
        setting_key = prefix_key_builder(key)
        if not settings.contains(setting_key):
            continue
        raw = settings.value(setting_key, None)
        if key == "local_nextcloud_roots":
            cfg[key] = _parse_roots(raw)
        else:
            cfg[key] = str(raw or "").strip()
    return cfg


def _to_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "ja", "on")


def _parse_roots(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
        except Exception:
            pass
    return [line.strip() for line in text.splitlines() if line.strip()]


def _load_user_config() -> dict:
    cfg = dict(load_shared_settings())
    local_settings = _load_nextcloud_settings_for_prefix(_master_setting_key)
    for key, value in local_settings.items():
        if key in ("nextcloud_app_password", "local_nextcloud_roots"):
            cfg[key] = value
        elif key not in cfg or not cfg[key]:
            cfg[key] = value
    return cfg


def _normalize_operator_entry(entry) -> dict:
    if isinstance(entry, dict):
        return {
            "source_name": str(
                entry.get(
                    "source_name",
                    entry.get("_source_name", entry.get("data_source", entry.get("datenquelle", ""))),
                )
                or ""
            ).strip(),
            "operator_name": str(
                entry.get("operator_name", entry.get("betreiber", ""))
                or ""
            ).strip(),
            "validity": str(
                entry.get(
                    "validity",
                    entry.get(
                        "gueltigkeit",
                        entry.get("gültigkeit", entry.get("gueltigk", entry.get("gültigk", ""))),
                    ),
                )
                or ""
            ).strip(),
            "stand": str(entry.get("stand", entry.get("operator_stand", entry.get("stand_datum", ""))) or "").strip(),
            "contact_name": str(
                entry.get("contact_name", entry.get("ansprechpartner", entry.get("kontakt", "")))
                or ""
            ).strip(),
            "phone": str(entry.get("phone", entry.get("telefonnummer", "")) or "").strip(),
            "email": str(entry.get("email", entry.get("mail", "")) or "").strip(),
            "fault_number": str(
                entry.get("fault_number", entry.get("stoernummer", ""))
                or ""
            ).strip(),
            "folder_path": str(
                entry.get(
                    "folder_path",
                    entry.get("ordnerpfad", entry.get("ordner", entry.get("path", ""))),
                )
                or ""
            ).strip(),
            "nextcloud_link": str(
                entry.get(
                    "nextcloud_link",
                    entry.get(
                        "nextcloudlink",
                        entry.get(
                            "folder_link",
                            entry.get("ordnerlink", entry.get("share_folder", "")),
                        ),
                    ),
                )
                or ""
            ).strip(),
        }
    if isinstance(entry, (list, tuple)):
        raw_values = [str(v or "").strip() for v in list(entry)]
        if len(raw_values) >= 10:
            values = raw_values[:10]
        elif len(raw_values) >= 9:
            values = raw_values[:9] + [""]
        elif len(raw_values) >= 7:
            values = [
                raw_values[0],
                raw_values[1],
                "",
                "",
                raw_values[2],
                raw_values[3],
                raw_values[4],
                raw_values[5],
                raw_values[6],
                "",
            ]
        else:
            values = [""] + raw_values[:9]
        while len(values) < 10:
            values.append("")
        return {
            "source_name": values[0],
            "operator_name": values[1],
            "validity": values[2],
            "stand": values[3],
            "contact_name": values[4],
            "phone": values[5],
            "email": values[6],
            "fault_number": values[7],
            "folder_path": values[8],
            "nextcloud_link": values[9],
        }
    return {
        "source_name": "",
        "operator_name": str(entry or "").strip(),
        "validity": "",
        "stand": "",
        "contact_name": "",
        "phone": "",
        "email": "",
        "fault_number": "",
        "folder_path": "",
        "nextcloud_link": "",
    }


def _normalize_data_source_entry(entry) -> dict:
    if isinstance(entry, dict):
        source_type = str(entry.get("source_type", entry.get("type", "file")) or "file").strip().lower()
        if source_type not in ("file", "qgis_uri"):
            source_type = "file"

        provider = str(entry.get("provider", "ogr") or "ogr").strip() or "ogr"
        source_value = str(
            entry.get("source", entry.get("path", entry.get("uri", ""))) or ""
        ).strip()
        table_value = str(
            entry.get("table", entry.get("layer_name", entry.get("sheet", ""))) or ""
        ).strip()

        return {
            "enabled": _to_bool(entry.get("enabled", entry.get("active", True)), True),
            "name": str(entry.get("name", entry.get("label", "")) or "").strip(),
            "source_type": source_type,
            "provider": provider,
            "source": source_value,
            "table": table_value,
            "operator_name_field": str(
                entry.get("operator_name_field", entry.get("operator_name_column", ""))
                or ""
            ).strip(),
            "contact_name_field": str(
                entry.get("contact_name_field", entry.get("contact_column", ""))
                or ""
            ).strip(),
            "phone_field": str(entry.get("phone_field", entry.get("phone_column", "")) or "").strip(),
            "email_field": str(entry.get("email_field", entry.get("email_column", "")) or "").strip(),
            "fault_number_field": str(
                entry.get("fault_number_field", entry.get("fault_number_column", ""))
                or ""
            ).strip(),
            "folder_path_field": str(
                entry.get("folder_path_field", entry.get("folder_path_column", ""))
                or ""
            ).strip(),
        }

    return {
        "enabled": True,
        "name": "",
        "source_type": "file",
        "provider": "ogr",
        "source": str(entry or "").strip(),
        "table": "",
        "operator_name_field": "",
        "contact_name_field": "",
        "phone_field": "",
        "email_field": "",
        "fault_number_field": "",
        "folder_path_field": "",
    }


def _parse_operators(value) -> list[dict]:
    if value is None:
        return []

    parsed = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = [text]

    if not isinstance(parsed, list):
        return []

    result = []
    for entry in parsed:
        normalized = _normalize_operator_entry(entry)
        if any(
            [
                normalized["operator_name"],
                normalized["validity"],
                normalized["stand"],
                normalized["contact_name"],
                normalized["phone"],
                normalized["email"],
                normalized["fault_number"],
                normalized["folder_path"],
                normalized["nextcloud_link"],
            ]
        ):
            result.append(normalized)
    return result


def _parse_data_sources(value) -> list[dict]:
    if value is None:
        return []

    parsed = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = [text]

    if not isinstance(parsed, list):
        return []

    result = []
    for entry in parsed:
        normalized = _normalize_data_source_entry(entry)
        if any(
            [
                normalized["name"],
                normalized["source"],
                normalized["table"],
                normalized["operator_name_field"],
                normalized["contact_name_field"],
                normalized["phone_field"],
                normalized["email_field"],
                normalized["fault_number_field"],
                normalized["folder_path_field"],
            ]
        ):
            result.append(normalized)
    return result


def _layer_config(layer) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    profile_cfg = load_layer_profile_config(layer)
    if isinstance(profile_cfg, dict):
        cfg.update(profile_cfg)
    for key, default in DEFAULT_CONFIG.items():
        raw = layer.customProperty(_property_key(key), default)
        if key in ("overwrite_existing_values", "fill_on_form_open"):
            cfg[key] = _to_bool(raw, bool(default))
        elif key == "local_nextcloud_roots":
            cfg[key] = _parse_roots(raw)
        elif key == "operators":
            cfg[key] = _parse_operators(raw)
        elif key == "external_data_sources":
            cfg[key] = _parse_data_sources(raw)
        else:
            cfg[key] = str(raw or "").strip()
    user_cfg = _load_user_config()
    for key in USER_CONFIG_KEYS:
        if key in user_cfg:
            cfg[key] = user_cfg[key]
    return expand_config_from_storage(cfg)


def _normalize_path(path: str) -> str:
    path = urllib.parse.unquote(str(path or "").strip())
    if path.startswith("file://"):
        parsed = urllib.parse.urlparse(path)
        path = urllib.parse.unquote(parsed.path or "")
    path = path.replace("\\", "/")
    return re.sub(r"/{2,}", "/", path)


def _join_root_and_relative(root: str, relative_nc_path: str) -> str:
    return root.rstrip("/") + "/" + relative_nc_path.lstrip("/")


def _project_base_dirs() -> list[str]:
    dirs = []
    try:
        project = QgsProject.instance()
    except Exception:
        project = None

    if project is not None:
        for candidate in (
            str(project.homePath() or "").strip(),
            os.path.dirname(str(project.fileName() or "").strip()),
        ):
            text = _normalize_path(candidate).rstrip("/")
            if text and text not in dirs:
                dirs.append(text)
    return dirs


def _resolve_relative_local_path(path: str, roots: list[str]) -> str | None:
    relative = str(path or "").strip()
    if not relative or os.path.isabs(relative):
        return None

    bases = []
    for base in list(roots or []) + _project_base_dirs() + [_normalize_path(os.getcwd()).rstrip("/")]:
        token = _normalize_path(base).rstrip("/")
        if token and token not in bases:
            bases.append(token)

    for base in bases:
        candidate = _normalize_path(os.path.normpath(os.path.join(base, relative)))
        if os.path.exists(candidate):
            return candidate
    return None


def _to_nextcloud_and_local_path(raw_path: str, config: dict) -> tuple[str | None, str | None]:
    if not raw_path:
        return None, None

    path = _normalize_path(raw_path)
    if not path:
        return None, None

    roots = [_normalize_path(p).rstrip("/") for p in config["local_nextcloud_roots"] if p]
    if not os.path.isabs(path):
        resolved_relative = _resolve_relative_local_path(path, roots)
        if resolved_relative:
            path = resolved_relative

    lower_path = path.lower()

    for root in roots:
        lower_root = root.lower()
        idx = lower_path.find(lower_root)
        if idx < 0:
            continue
        tail = path[idx + len(root) :]
        if not tail.startswith("/"):
            tail = "/" + tail
        return tail, _join_root_and_relative(root, tail)

    for root in roots:
        root_name = os.path.basename(root)
        if not root_name:
            continue
        idx = lower_path.find(root_name.lower())
        if idx < 0:
            continue
        tail = path[idx + len(root_name) :]
        if not tail.startswith("/"):
            tail = "/" + tail
        abs_path = _join_root_and_relative(root, tail)
        return tail, abs_path

    marker = str(config.get("nextcloud_folder_marker", "Nextcloud")).strip("/")
    if marker:
        token = "/" + marker.lower() + "/"
        marker_pos = lower_path.find(token)
        if marker_pos >= 0:
            tail = path[marker_pos + len(token) :]
            tail = "/" + tail.lstrip("/")
            base = roots[0] if roots else ""
            abs_path = _join_root_and_relative(base, tail) if base else tail
            return tail, abs_path

    # Wenn ein lokaler Absolutpfad nicht auf einen konfigurierten Sync-Root zeigt,
    # ist kein sicheres Mapping auf einen Nextcloud-Serverpfad moeglich.
    if os.path.isabs(path):
        unix_style = path.startswith("/")
        if unix_style and (
            path.startswith("/Users/")
            or path.startswith("/Volumes/")
            or path.startswith("/private/")
            or path.startswith("/Applications/")
        ):
            return None, None
        return path if path.startswith("/") else "/" + path, path

    relative = path.lstrip("/")
    if not relative:
        return None, None

    if roots:
        candidate_abs = _join_root_and_relative(roots[0], relative)
        if os.path.exists(candidate_abs):
            return "/" + relative, candidate_abs
        return None, None

    return "/" + relative, "/" + relative


def _ocs_request(
    config: dict,
    method: str,
    endpoint_url: str,
    params: dict | None = None,
    data: dict | None = None,
) -> dict:
    all_params = {"format": "json"}
    if params:
        all_params.update(params)
    query = urllib.parse.urlencode(all_params, doseq=True)
    url = f"{endpoint_url}?{query}"

    user = config["nextcloud_user"]
    app_password = config["nextcloud_app_password"]
    encoded_auth = base64.b64encode(f"{user}:{app_password}".encode("utf-8")).decode(
        "ascii"
    )

    headers = {
        "Authorization": f"Basic {encoded_auth}",
        "OCS-APIRequest": "true",
        "Accept": "application/json",
    }

    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(url=url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        if exc.code == 429:
            retry_after = _retry_after_seconds(getattr(exc, "headers", None))
            raise NextcloudRateLimitError(
                f"Nextcloud HTTP 429: {body_text}",
                retry_after=retry_after,
            ) from exc
        raise RuntimeError(f"Nextcloud HTTP {exc.code}: {body_text}") from exc
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


def _retry_after_seconds(headers) -> int | None:
    if headers is None:
        return None
    raw = str(headers.get("Retry-After", "") or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return max(1, int(raw))
    try:
        parsed = parsedate_to_datetime(raw)
    except Exception:
        parsed = None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    seconds = int((parsed - datetime.now(timezone.utc)).total_seconds())
    return max(1, seconds)


def _rate_limit_wait_seconds(exc: Exception) -> int:
    retry_after = getattr(exc, "retry_after", None)
    if isinstance(retry_after, int) and retry_after > 0:
        return retry_after
    return _DEFAULT_RATE_LIMIT_SECONDS


def _set_share_backoff(cache_key: tuple[str, str, str], wait_seconds: int):
    _SHARE_BACKOFF_UNTIL[cache_key] = time.time() + max(5, int(wait_seconds))


def _remaining_share_backoff(cache_key: tuple[str, str, str]) -> int:
    until = float(_SHARE_BACKOFF_UNTIL.get(cache_key, 0) or 0)
    if until <= 0:
        return 0
    remaining = int(until - time.time())
    return max(0, remaining)


def _canonical_nextcloud_path(nc_path: str) -> str:
    normalized = _normalize_path(nc_path)
    if not normalized:
        return ""
    canonical = "/" + normalized.lstrip("/")
    if canonical != "/":
        canonical = canonical.rstrip("/")
    return canonical


def _nextcloud_path_variants(nc_path: str) -> list[str]:
    canonical = _canonical_nextcloud_path(nc_path)
    if not canonical:
        return []

    variants = [canonical]
    if canonical != "/":
        no_leading = canonical.lstrip("/")
        if no_leading and no_leading != canonical:
            variants.append(no_leading)

    unique = []
    seen = set()
    for value in variants:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def _share_path_bases(canonical_path: str, config: dict) -> list[str]:
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
    remainder = path_body[len(first_segment) :] if first_segment else ""

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
    for item in candidates:
        canonical = _canonical_nextcloud_path(item)
        if not canonical or canonical == "/" or canonical in seen:
            continue
        seen.add(canonical)
        unique.append(canonical)
    return unique


def _share_request_paths(canonical_path: str, config: dict) -> list[str]:
    request_paths = []
    for base_path in _share_path_bases(canonical_path, config):
        request_paths.extend(_nextcloud_path_variants(base_path))

    unique = []
    seen = set()
    for path in request_paths:
        token = str(path or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        unique.append(token)
    return unique


def _extract_public_share_url(ocs_payload: dict, accepted_paths: set[str] | None = None) -> str:
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


def get_or_create_public_link(config: dict, nc_path: str) -> str:
    canonical_path = _canonical_nextcloud_path(nc_path)
    if not canonical_path:
        raise RuntimeError("Leerer Nextcloud-Pfad fuer Share-Link.")
    if canonical_path == "/":
        raise RuntimeError("Root-Pfad kann nicht als oeffentlicher Nextcloud-Link geteilt werden.")

    cache_key = (
        str(config["nextcloud_base_url"]).rstrip("/"),
        str(config["nextcloud_user"]),
        canonical_path,
    )
    if cache_key in _SHARE_CACHE:
        return _SHARE_CACHE[cache_key]
    remaining_backoff = _remaining_share_backoff(cache_key)
    if remaining_backoff > 0:
        raise RuntimeError(
            f"Nextcloud Rate-Limit aktiv, bitte in ca. {remaining_backoff}s erneut versuchen."
        )

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
    create_paths = request_paths[:]

    errors = []

    for endpoint in endpoints:
        for candidate_path in request_paths:
            existing_query_variants = (
                {"path": candidate_path, "reshares": "true", "subfiles": "false"},
                {"path": candidate_path},
            )

            for query_params in existing_query_variants:
                try:
                    existing = _ocs_request(
                        config=config,
                        method="GET",
                        endpoint_url=endpoint,
                        params=query_params,
                    )
                    link = _extract_public_share_url(
                        existing, accepted_paths={_canonical_nextcloud_path(candidate_path)}
                    )
                    if link:
                        _SHARE_CACHE[cache_key] = link
                        return link
                    break
                except NextcloudRateLimitError as exc:
                    wait_seconds = _rate_limit_wait_seconds(exc)
                    _set_share_backoff(cache_key, wait_seconds)
                    raise RuntimeError(
                        f"Nextcloud Rate-Limit (HTTP 429), bitte in ca. {wait_seconds}s erneut versuchen."
                    ) from exc
                except Exception as exc:
                    errors.append(f"GET {endpoint} path='{candidate_path}' -> {exc}")

        # Manche Server liefern mit path-Filter 500 (statuscode 996), ohne Filter aber gueltige Daten.
        try:
            existing_all = _ocs_request(
                config=config,
                method="GET",
                endpoint_url=endpoint,
                params={"reshares": "true"},
            )
            link = _extract_public_share_url(existing_all, accepted_paths=accepted_paths)
            if link:
                _SHARE_CACHE[cache_key] = link
                return link
        except NextcloudRateLimitError as exc:
            wait_seconds = _rate_limit_wait_seconds(exc)
            _set_share_backoff(cache_key, wait_seconds)
            raise RuntimeError(
                f"Nextcloud Rate-Limit (HTTP 429), bitte in ca. {wait_seconds}s erneut versuchen."
            ) from exc
        except Exception as exc:
            errors.append(f"GET {endpoint} all(reshares=true) -> {exc}")

        for candidate_path in create_paths:
            try:
                created = _ocs_request(
                    config=config,
                    method="POST",
                    endpoint_url=endpoint,
                    data={"path": candidate_path, "shareType": "3", "permissions": "1"},
                )
                link = str((created.get("ocs", {}).get("data") or {}).get("url") or "").strip()
                if link:
                    _SHARE_CACHE[cache_key] = link
                    return link
            except NextcloudRateLimitError as exc:
                wait_seconds = _rate_limit_wait_seconds(exc)
                _set_share_backoff(cache_key, wait_seconds)
                raise RuntimeError(
                    f"Nextcloud Rate-Limit (HTTP 429), bitte in ca. {wait_seconds}s erneut versuchen."
                ) from exc
            except Exception as exc:
                errors.append(f"POST {endpoint} path='{candidate_path}' -> {exc}")

    details = errors[-1] if errors else "Unbekannter Fehler"
    raise RuntimeError(
        f"Kein Share-Link erzeugt fuer '{canonical_path}'. Letzter Fehler: {details}"
    )


def _configured_fields(config: dict) -> list[str]:
    names = [
        config.get("path_field_name"),
        config.get("file_link_field_name"),
        config.get("folder_link_field_name"),
        config.get("name_field_name"),
        config.get("stand_field_name"),
        config.get("operator_name_field_name"),
        config.get("operator_contact_field_name"),
        config.get("operator_phone_field_name"),
        config.get("operator_email_field_name"),
        config.get("operator_fault_field_name"),
        config.get("operator_validity_field_name"),
        config.get("operator_stand_field_name"),
    ]
    return [str(name).strip() for name in names if str(name or "").strip()]


def _missing_fields(layer, config: dict) -> list[str]:
    return [name for name in _configured_fields(config) if layer.fields().indexOf(name) < 0]


def _is_empty_value(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def _needs_update(feature, field_name: str, overwrite_existing_values: bool) -> bool:
    if not str(field_name or "").strip():
        return False
    if overwrite_existing_values:
        return True
    try:
        current = feature[field_name]
    except Exception:
        return True
    return _is_empty_value(current)


def _set_if_allowed(
    dialog,
    feature,
    field_name: str,
    value,
    overwrite_existing_values: bool,
):
    if not str(field_name or "").strip() or value is None:
        return
    if not overwrite_existing_values:
        try:
            current = feature[field_name]
            if not _is_empty_value(current):
                return
        except Exception:
            pass
    dialog.changeAttribute(field_name, value)


def _stand_date(abs_file_path: str | None) -> str | None:
    if not abs_file_path or not os.path.exists(abs_file_path):
        return None
    ts = os.path.getmtime(abs_file_path)
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _normalized_operator_name(value) -> str:
    return str(value or "").strip().lower()


def _resolve_field_name(layer: QgsVectorLayer, configured_name: str, aliases: list[str]) -> str:
    field_names = [field.name() for field in layer.fields()]
    lowered = {name.lower(): name for name in field_names}
    normalized = {_normalize_field_token(name): name for name in field_names}

    token = str(configured_name or "").strip()
    if token:
        if token in field_names:
            return token
        if token.lower() in lowered:
            return lowered[token.lower()]
        norm_token = _normalize_field_token(token)
        if norm_token in normalized:
            return normalized[norm_token]
        for field_name in field_names:
            norm_field = _normalize_field_token(field_name)
            if norm_token and (norm_token in norm_field or norm_field in norm_token):
                return field_name

    for alias in aliases:
        alias_token = str(alias or "").strip().lower()
        if alias_token and alias_token in lowered:
            return lowered[alias_token]
        norm_alias = _normalize_field_token(alias)
        if norm_alias and norm_alias in normalized:
            return normalized[norm_alias]
        for field_name in field_names:
            norm_field = _normalize_field_token(field_name)
            if norm_alias and (norm_alias in norm_field or norm_field in norm_alias):
                return field_name

    return ""


def _normalize_field_token(value: str) -> str:
    token = str(value or "").strip().lower()
    token = (
        token.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    return "".join(ch for ch in token if ch.isalnum())


def _is_generic_field_name(value: str) -> bool:
    return bool(re.fullmatch(r"field\d+", str(value or "").strip().lower()))


def _layer_uses_generic_fields(layer: QgsVectorLayer) -> bool:
    names = [field.name() for field in layer.fields()]
    return bool(names) and all(_is_generic_field_name(name) for name in names)


def _header_tokens_from_first_feature(layer: QgsVectorLayer) -> list[str]:
    for feature in layer.getFeatures():
        return [str(value or "").strip() for value in feature.attributes()]
    return []


def _resolve_column_index(header_tokens: list[str], configured_name: str, aliases: list[str]) -> int:
    normalized = {}
    lowered = {}
    for idx, token in enumerate(header_tokens):
        text = str(token or "").strip()
        if not text:
            continue
        lowered[text.lower()] = idx
        norm_token = _normalize_field_token(text)
        if norm_token and norm_token not in normalized:
            normalized[norm_token] = idx

    value = str(configured_name or "").strip()
    if value:
        if value.lower() in lowered:
            return lowered[value.lower()]
        norm_value = _normalize_field_token(value)
        if norm_value in normalized:
            return normalized[norm_value]
        for idx, token in enumerate(header_tokens):
            norm_token = _normalize_field_token(token)
            if norm_value and (norm_value in norm_token or norm_token in norm_value):
                return idx

    for alias in aliases:
        alias_text = str(alias or "").strip()
        if not alias_text:
            continue
        if alias_text.lower() in lowered:
            return lowered[alias_text.lower()]
        norm_alias = _normalize_field_token(alias_text)
        if norm_alias in normalized:
            return normalized[norm_alias]
        for idx, token in enumerate(header_tokens):
            norm_token = _normalize_field_token(token)
            if norm_alias and (norm_alias in norm_token or norm_token in norm_alias):
                return idx
    return -1


def _safe_attribute_by_index(feature, idx: int):
    if idx < 0:
        return ""
    attrs = feature.attributes()
    if idx >= len(attrs):
        return ""
    return attrs[idx]


def _expand_local_root_placeholder(value: str, roots: list[str]) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not LOCAL_ROOT_PLACEHOLDER_PATTERN.search(text):
        return text

    root = ""
    for candidate in roots or []:
        token = str(candidate or "").strip()
        if token:
            root = token.rstrip("/\\")
            break
    # Use callable replacement so Windows backslashes are treated literally.
    return LOCAL_ROOT_PLACEHOLDER_PATTERN.sub(lambda _match: root, text)


def _resolved_source_value(source: dict, config: dict) -> str:
    source_value = str(source.get("source", "") or "").strip()
    roots = [
        str(path or "").strip()
        for path in config.get("local_nextcloud_roots", [])
        if str(path or "").strip()
    ]
    if not roots:
        roots = [
            str(path or "").strip()
            for path in DEFAULT_CONFIG.get("local_nextcloud_roots", [])
            if str(path or "").strip()
        ]
    return _expand_local_root_placeholder(source_value, roots)


def _source_uri_and_provider(source: dict, config: dict) -> tuple[str, str]:
    source_type = str(source.get("source_type", "file") or "file").strip().lower()
    provider = str(source.get("provider", "ogr") or "ogr").strip() or "ogr"
    source_value = _resolved_source_value(source, config)
    table_value = str(source.get("table", "") or "").strip()

    if source_type == "file":
        uri = source_value
        if uri.startswith("file://"):
            parsed = urllib.parse.urlparse(uri)
            uri = urllib.parse.unquote(parsed.path or "")
        if table_value and provider == "ogr" and "|layername=" not in uri.lower():
            uri = f"{uri}|layername={table_value}"
        return uri, provider

    if table_value and provider == "ogr" and "|layername=" not in source_value.lower():
        return f"{source_value}|layername={table_value}", provider
    return source_value, provider


def _source_display_name(source: dict) -> str:
    normalized = _normalize_data_source_entry(source)
    name = str(normalized.get("name", "") or "").strip()
    if name:
        return name

    source_value = str(normalized.get("source", "") or "").strip()
    if source_value.startswith("file://"):
        parsed = urllib.parse.urlparse(source_value)
        source_value = urllib.parse.unquote(parsed.path or "")
    source_value = source_value.split("|", 1)[0].strip().rstrip("/\\")
    label = os.path.basename(source_value) if source_value else ""
    return label or "Quelle"


def _normalized_source_name(value: str) -> str:
    return str(value or "").strip().casefold()


def _best_local_overlay(local_entries: list[dict], operator_name: str, source_name: str = "", validity: str = "") -> dict | None:
    operator_token = _normalized_operator_name(operator_name)
    if not operator_token:
        return None

    source_token = _normalized_source_name(source_name)
    validity_token = str(validity or "").strip().casefold()
    matches = []
    for entry in local_entries or []:
        normalized = _normalize_operator_entry(entry)
        if _normalized_operator_name(normalized.get("operator_name")) != operator_token:
            continue

        entry_source_token = _normalized_source_name(normalized.get("source_name", ""))
        if source_token and entry_source_token and entry_source_token != source_token:
            continue

        source_score = 2 if source_token and entry_source_token == source_token else 1 if not entry_source_token else 0
        entry_validity_token = str(normalized.get("validity", "") or "").strip().casefold()
        validity_score = 1 if validity_token and entry_validity_token == validity_token else 0
        fill_score = sum(
            1
            for key in ("stand", "folder_path", "nextcloud_link")
            if str(normalized.get(key, "") or "").strip()
        )
        matches.append((source_score, validity_score, fill_score, normalized))

    if not matches:
        return None

    matches.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return matches[0][3]


def _read_operator_entries_from_external_source(source: dict, config: dict) -> list[dict]:
    if not _to_bool(source.get("enabled", True), True):
        return []
    source_value = _resolved_source_value(source, config)
    if not source_value:
        return []

    uri, provider = _source_uri_and_provider(source, config)
    ext_layer = QgsVectorLayer(uri, "attributionbutler_data_source", provider)
    if not ext_layer.isValid():
        if (
            str(source.get("source_type", "file")).lower() == "file"
            and str(source.get("table", "")).strip()
            and provider == "ogr"
        ):
            ext_layer = QgsVectorLayer(source_value, "attributionbutler_data_source", provider)
        if not ext_layer.isValid():
            return []

    fallback_name = (
        str(source.get("operator_name_field", "") or "").strip()
        or str(config.get("operator_name_field_name", "") or "").strip()
        or str(DEFAULT_CONFIG.get("operator_name_field_name", "") or "")
    )
    fallback_contact = (
        str(source.get("contact_name_field", "") or "").strip()
        or str(config.get("operator_contact_field_name", "") or "").strip()
        or str(DEFAULT_CONFIG.get("operator_contact_field_name", "") or "")
    )
    fallback_phone = (
        str(source.get("phone_field", "") or "").strip()
        or str(config.get("operator_phone_field_name", "") or "").strip()
        or str(DEFAULT_CONFIG.get("operator_phone_field_name", "") or "")
    )
    fallback_email = (
        str(source.get("email_field", "") or "").strip()
        or str(config.get("operator_email_field_name", "") or "").strip()
        or str(DEFAULT_CONFIG.get("operator_email_field_name", "") or "")
    )
    fallback_fault = (
        str(source.get("fault_number_field", "") or "").strip()
        or str(config.get("operator_fault_field_name", "") or "").strip()
        or str(DEFAULT_CONFIG.get("operator_fault_field_name", "") or "")
    )
    fallback_validity = (
        str(config.get("operator_validity_field_name", "") or "").strip()
        or str(DEFAULT_CONFIG.get("operator_validity_field_name", "") or "")
    )
    fallback_stand = (
        str(config.get("operator_stand_field_name", "") or "").strip()
        or str(DEFAULT_CONFIG.get("operator_stand_field_name", "") or "")
    )

    generic_fields = _layer_uses_generic_fields(ext_layer)
    header_tokens = _header_tokens_from_first_feature(ext_layer) if generic_fields else []

    if generic_fields and header_tokens:
        name_col = _resolve_column_index(
            header_tokens,
            fallback_name,
            ["operator_name", "betreibername", "betreiber", "name"],
        )
        if name_col < 0 and header_tokens:
            name_col = 0
        if name_col < 0:
            return []

        contact_col = _resolve_column_index(
            header_tokens,
            fallback_contact,
            ["contact_name", "ansprechpartner", "kontakt", "kontaktperson", "betr_anspr"],
        )
        phone_col = _resolve_column_index(
            header_tokens,
            fallback_phone,
            ["phone", "telefon", "telefonnummer", "betr_tel", "tel"],
        )
        email_col = _resolve_column_index(
            header_tokens,
            fallback_email,
            ["email", "mail", "e-mail", "e_mail", "betr_email"],
        )
        fault_col = _resolve_column_index(
            header_tokens,
            fallback_fault,
            ["fault_number", "stoernummer", "stoernr", "stornummer", "betr_stoer", "stoer_nr"],
        )
        validity_col = _resolve_column_index(
            header_tokens,
            fallback_validity,
            ["validity", "gueltigkeit", "gültigkeit", "gueltigk", "gültigk"],
        )
        stand_col = _resolve_column_index(
            header_tokens,
            fallback_stand,
            ["stand", "stand_datum", "statusdatum"],
        )
    else:
        name_field = _resolve_field_name(
            ext_layer,
            fallback_name,
            ["operator_name", "betreibername", "betreiber", "name"],
        )
        if not name_field and ext_layer.fields():
            name_field = ext_layer.fields()[0].name()
        if not name_field:
            return []

        contact_field = _resolve_field_name(
            ext_layer,
            fallback_contact,
            ["contact_name", "ansprechpartner", "kontakt", "kontaktperson", "betr_anspr"],
        )
        phone_field = _resolve_field_name(
            ext_layer,
            fallback_phone,
            ["phone", "telefon", "telefonnummer", "betr_tel", "tel"],
        )
        email_field = _resolve_field_name(
            ext_layer,
            fallback_email,
            ["email", "mail", "e-mail", "e_mail", "betr_email"],
        )
        fault_field = _resolve_field_name(
            ext_layer,
            fallback_fault,
            ["fault_number", "stoernummer", "stoernr", "stornummer", "betr_stoer", "stoer_nr"],
        )
        validity_field = _resolve_field_name(
            ext_layer,
            fallback_validity,
            ["validity", "gueltigkeit", "gültigkeit", "gueltigk", "gültigk"],
        )
        stand_field = _resolve_field_name(
            ext_layer,
            fallback_stand,
            ["stand", "stand_datum", "statusdatum"],
        )
    entries = []
    source_name = _source_display_name(source)
    for idx, feature in enumerate(ext_layer.getFeatures()):
        if idx >= 50000:
            break

        if generic_fields and idx == 0:
            continue

        entry = _normalize_operator_entry(
            {
                "operator_name": _safe_attribute_by_index(feature, name_col)
                if generic_fields
                else (feature[name_field] if name_field else ""),
                "contact_name": _safe_attribute_by_index(feature, contact_col)
                if generic_fields
                else (feature[contact_field] if contact_field else ""),
                "phone": _safe_attribute_by_index(feature, phone_col)
                if generic_fields
                else (feature[phone_field] if phone_field else ""),
                "email": _safe_attribute_by_index(feature, email_col)
                if generic_fields
                else (feature[email_field] if email_field else ""),
                "fault_number": _safe_attribute_by_index(feature, fault_col)
                if generic_fields
                else (feature[fault_field] if fault_field else ""),
                "validity": _safe_attribute_by_index(feature, validity_col)
                if generic_fields
                else (feature[validity_field] if validity_field else ""),
                "stand": _safe_attribute_by_index(feature, stand_col)
                if generic_fields
                else (feature[stand_field] if stand_field else ""),
                "folder_path": "",
            }
        )
        if entry["operator_name"]:
            entry["source_name"] = source_name
            entries.append(entry)
    return entries


def _all_operator_entries(config: dict) -> list[dict]:
    local_entries = []
    for entry in config.get("operators", []):
        normalized = _normalize_operator_entry(entry)
        if normalized["operator_name"]:
            local_entries.append(normalized)

    external_entries = []
    matched_local_keys = set()
    for source in config.get("external_data_sources", []):
        normalized_source = _normalize_data_source_entry(source)
        for entry in _read_operator_entries_from_external_source(normalized_source, config):
            overlay = _best_local_overlay(
                local_entries,
                entry.get("operator_name", ""),
                entry.get("source_name", ""),
                entry.get("validity", ""),
            )
            merged = dict(entry)
            if overlay:
                if str(overlay.get("stand", "") or "").strip():
                    merged["stand"] = str(overlay.get("stand", "") or "").strip()
                if str(overlay.get("folder_path", "") or "").strip():
                    merged["folder_path"] = str(overlay.get("folder_path", "") or "").strip()
                if str(overlay.get("nextcloud_link", "") or "").strip():
                    merged["nextcloud_link"] = str(overlay.get("nextcloud_link", "") or "").strip()
                matched_local_keys.add(
                    (
                        _normalized_source_name(overlay.get("source_name", "")),
                        _normalized_operator_name(overlay.get("operator_name", "")),
                        str(overlay.get("validity", "") or "").strip().casefold(),
                    )
                )
            external_entries.append(merged)

    result = list(external_entries)
    for entry in local_entries:
        key = (
            _normalized_source_name(entry.get("source_name", "")),
            _normalized_operator_name(entry.get("operator_name", "")),
            str(entry.get("validity", "") or "").strip().casefold(),
        )
        if key in matched_local_keys:
            continue
        result.append(entry)
    return result


def _matching_operator_entries(operator_entries: list[dict], operator_name_value) -> list[dict]:
    needle = _normalized_operator_name(operator_name_value)
    if not needle:
        return []

    matches = []
    for entry in operator_entries:
        if _normalized_operator_name(entry.get("operator_name")) == needle:
            matches.append(entry)
    return matches


def _operator_entry_score(entry: dict) -> int:
    values = [
        str(entry.get("validity", "") or "").strip(),
        str(entry.get("stand", "") or "").strip(),
        str(entry.get("contact_name", "") or "").strip(),
        str(entry.get("phone", "") or "").strip(),
        str(entry.get("email", "") or "").strip(),
        str(entry.get("fault_number", "") or "").strip(),
        str(entry.get("folder_path", "") or "").strip(),
        str(entry.get("nextcloud_link", "") or "").strip(),
    ]
    return sum(1 for value in values if value)


def _unique_operator_entry(operator_entries: list[dict], operator_name_value) -> dict | None:
    matches = _matching_operator_entries(operator_entries, operator_name_value)
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    def _sig(entry: dict):
        return (
            str(entry.get("validity", "") or "").strip().lower(),
            str(entry.get("stand", "") or "").strip().lower(),
            str(entry.get("contact_name", "") or "").strip().lower(),
            str(entry.get("phone", "") or "").strip().lower(),
            str(entry.get("email", "") or "").strip().lower(),
            str(entry.get("fault_number", "") or "").strip().lower(),
            str(entry.get("folder_path", "") or "").strip().lower(),
            str(entry.get("nextcloud_link", "") or "").strip().lower(),
        )

    signatures = {_sig(entry) for entry in matches}
    if len(signatures) == 1:
        return matches[0]

    best = max(_operator_entry_score(entry) for entry in matches)
    best_entries = [entry for entry in matches if _operator_entry_score(entry) == best]
    if len(best_entries) == 1 and best > 0:
        return best_entries[0]
    return None


def _apply_operator_lookup(
    dialog,
    feature,
    config: dict,
    operator_entries: list[dict],
    operator_name_value,
):
    matches = _matching_operator_entries(operator_entries, operator_name_value)
    if not matches:
        return False

    entry = _unique_operator_entry(matches, operator_name_value)
    if not entry:
        # Fallback fuer Mehrfachtreffer: nicht abbrechen, sondern bestmoeglichen Treffer verwenden.
        entry = max(matches, key=_operator_entry_score)

    # Betreiber-Lookup soll abhängige Felder synchron halten und daher immer überschreiben.
    overwrite = True
    targets = [
        (config.get("operator_contact_field_name", ""), entry.get("contact_name")),
        (config.get("operator_phone_field_name", ""), entry.get("phone")),
        (config.get("operator_email_field_name", ""), entry.get("email")),
        (config.get("operator_fault_field_name", ""), entry.get("fault_number")),
        (config.get("operator_validity_field_name", ""), entry.get("validity")),
        (config.get("operator_stand_field_name", ""), entry.get("stand")),
    ]
    for field_name, field_value in targets:
        if field_value in (None, ""):
            continue
        _set_if_allowed(dialog, feature, field_name, field_value, overwrite)

    folder_field = str(config.get("folder_link_field_name", "") or "").strip()
    if not folder_field:
        return True
    folder_link = str(entry.get("nextcloud_link", "") or "").strip()
    if folder_link:
        _set_if_allowed(dialog, feature, folder_field, folder_link, overwrite)
        return True
    try:
        dialog.changeAttribute(folder_field, None)
    except Exception:
        pass
    return True


def _clear_operator_lookup_fields(dialog, config: dict):
    fields = [
        str(config.get("operator_contact_field_name", "") or "").strip(),
        str(config.get("operator_phone_field_name", "") or "").strip(),
        str(config.get("operator_email_field_name", "") or "").strip(),
        str(config.get("operator_fault_field_name", "") or "").strip(),
        str(config.get("operator_validity_field_name", "") or "").strip(),
        str(config.get("operator_stand_field_name", "") or "").strip(),
        str(config.get("folder_link_field_name", "") or "").strip(),
    ]
    for field_name in fields:
        if not field_name:
            continue
        try:
            dialog.changeAttribute(field_name, None)
        except Exception:
            pass


def _unique_texts(values) -> list[str]:
    result = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _operator_name_suggestions(config: dict, layer, field_name: str, operator_entries: list[dict]) -> list[str]:
    configured = []
    for entry in operator_entries:
        configured.append(str(_normalize_operator_entry(entry).get("operator_name", "") or "").strip())

    unique_values = []
    field_index = layer.fields().indexOf(field_name)
    if field_index >= 0 and hasattr(layer, "uniqueValues"):
        try:
            unique_values = list(layer.uniqueValues(field_index, 5000))
        except Exception:
            try:
                unique_values = list(layer.uniqueValues(field_index))
            except Exception:
                unique_values = []

    # Betreiberliste zuerst, dann bereits vorhandene Layer-Werte.
    return _unique_texts(configured + unique_values)


def _editor_widget_for_field(dialog, layer, field_name: str):
    hosts = [dialog]
    attr_form = None
    try:
        attr_form = dialog.attributeForm()
    except Exception:
        attr_form = None
    if attr_form is not None:
        hosts.append(attr_form)

    for host in hosts:
        wrapper_fn = getattr(host, "widgetWrapper", None)
        if callable(wrapper_fn):
            try:
                wrapper = wrapper_fn(field_name)
                if wrapper is not None and hasattr(wrapper, "widget"):
                    widget = wrapper.widget()
                    if isinstance(widget, QWidget):
                        return widget
            except Exception:
                pass

    field_index = layer.fields().indexOf(field_name)
    if attr_form is not None and field_index >= 0:
        wrapper_fn = getattr(attr_form, "widgetWrapper", None)
        if callable(wrapper_fn):
            try:
                wrapper = wrapper_fn(field_index)
                if wrapper is not None and hasattr(wrapper, "widget"):
                    widget = wrapper.widget()
                    if isinstance(widget, QWidget):
                        return widget
            except Exception:
                pass

    for host in hosts:
        try:
            widget = host.findChild(QWidget, field_name)
            if isinstance(widget, QWidget):
                return widget
        except Exception:
            pass

    return None


def _line_edit_from_widget(widget):
    if isinstance(widget, QLineEdit):
        return widget
    if isinstance(widget, QComboBox) and widget.isEditable():
        return widget.lineEdit()
    if isinstance(widget, QWidget):
        return widget.findChild(QLineEdit)
    return None


def _install_operator_name_completer(
    dialog,
    layer,
    config: dict,
    operator_name_field: str,
    operator_entries: list[dict],
):
    suggestions = _operator_name_suggestions(config, layer, operator_name_field, operator_entries)
    if not suggestions:
        return

    editor_widget = _editor_widget_for_field(dialog, layer, operator_name_field)
    if editor_widget is None:
        return

    if isinstance(editor_widget, QComboBox):
        existing = {editor_widget.itemText(i).strip().casefold() for i in range(editor_widget.count())}
        for value in suggestions:
            token = str(value or "").strip()
            if token and token.casefold() not in existing:
                editor_widget.addItem(token)
                existing.add(token.casefold())

    line_edit = _line_edit_from_widget(editor_widget)
    if line_edit is None:
        return

    model = QStringListModel(suggestions, line_edit)
    completer = QCompleter(model, line_edit)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setCompletionMode(QCompleter.PopupCompletion)
    if hasattr(completer, "setFilterMode") and hasattr(Qt, "MatchContains"):
        completer.setFilterMode(Qt.MatchContains)
    line_edit.setCompleter(completer)


def _is_missing_path_error(message: str) -> bool:
    text = str(message or "").lower()
    markers = [
        "statuscode\":404",
        "statuscode':404",
        "nextcloud http 404",
        "api-fehler 404",
        "wrong path, file/folder does not exist",
        "file\\/folder does not exist",
    ]
    return any(marker in text for marker in markers)


def _is_rate_limit_error(message: str) -> bool:
    text = str(message or "").lower()
    markers = [
        "nextcloud http 429",
        "rate-limit",
        "rate limit",
        "too many requests",
        "statuscode\":429",
        "statuscode':429",
    ]
    return any(marker in text for marker in markers)


def form_open(dialog, layer, feature):
    config = _layer_config(layer)
    path_field = str(config.get("path_field_name", "")).strip()
    operator_name_field = str(config.get("operator_name_field_name", "")).strip()
    operator_entries = _all_operator_entries(config)
    if not path_field:
        QMessageBox.warning(dialog, "Form-Setup Fehler", "Pfadfeld ist leer.")
        return

    missing = _missing_fields(layer, config)
    if missing:
        QMessageBox.warning(
            dialog,
            "Form-Setup Fehler",
            "Folgende Felder fehlen im Layer:\n- " + "\n- ".join(missing),
        )
        return

    if not config["nextcloud_base_url"] or not config["nextcloud_user"] or not config["nextcloud_app_password"]:
        QMessageBox.warning(
            dialog,
            "Form-Setup Fehler",
            "Nextcloud URL, Benutzer und App-Passwort sind nicht vollstaendig konfiguriert. "
            "Bitte in Trassify Master Tools > Einstellungen > Nextcloud setzen.",
        )
        return

    if operator_name_field:
        try:
            _install_operator_name_completer(
                dialog,
                layer,
                config,
                operator_name_field,
                operator_entries,
            )
        except Exception:
            pass

    def handle_change(attribute, value, attributeChanged):
        if not attributeChanged:
            return
        changed_field = str(attribute or "").strip()

        if operator_name_field and changed_field == operator_name_field:
            raw_operator_name = str(value or "").strip()
            try:
                if not raw_operator_name:
                    _clear_operator_lookup_fields(dialog, config)
                    return

                current_feature = dialog.currentFormFeature()
                matched = _apply_operator_lookup(
                    dialog,
                    current_feature,
                    config,
                    operator_entries,
                    raw_operator_name,
                )
                if not matched:
                    _clear_operator_lookup_fields(dialog, config)
            except Exception as exc:
                message = str(exc)
                if _is_rate_limit_error(message):
                    return
                QMessageBox.warning(dialog, "Betreiber-Fehler", message)
            return

        if changed_field != path_field:
            return

        raw_path = str(value or "").strip()
        if not raw_path or raw_path.lower() in ("null", "none") or raw_path in ("/", "\\"):
            return

        overwrite = bool(config["overwrite_existing_values"])

        try:
            current_feature = dialog.currentFormFeature()
            file_field = config.get("file_link_field_name", "")
            name_field = config.get("name_field_name", "")
            stand_field = config.get("stand_field_name", "")

            need_file = _needs_update(current_feature, file_field, overwrite)
            need_name = _needs_update(current_feature, name_field, overwrite)
            need_stand = _needs_update(current_feature, stand_field, overwrite)

            if not any((need_file, need_name, need_stand)):
                return

            nc_file_path, abs_file_path = _to_nextcloud_and_local_path(raw_path, config)
            if not nc_file_path:
                _log_nextcloud_warning(
                    "Kein Nextcloud-Mapping fuer Dateipfad: "
                    f"'{raw_path}'. Pruefe Trassify Master Tools > Einstellungen > Lokale Sync-Roots."
                )
                return

            file_link = None
            dataname = None
            stand = None

            if need_file:
                file_link = get_or_create_public_link(config, nc_file_path)
            if need_name:
                dataname = os.path.basename(abs_file_path) if abs_file_path else None
            if need_stand:
                stand = _stand_date(abs_file_path)

            _set_if_allowed(dialog, current_feature, file_field, file_link, overwrite)
            _set_if_allowed(dialog, current_feature, name_field, dataname, overwrite)
            _set_if_allowed(dialog, current_feature, stand_field, stand, overwrite)
        except Exception as exc:
            message = str(exc)
            if _is_missing_path_error(message) or _is_rate_limit_error(message):
                _log_nextcloud_warning(
                    f"Datei-Link konnte nicht erzeugt werden ({message}); Eingabepfad: {raw_path}"
                )
                return
            QMessageBox.warning(dialog, "Nextcloud-Fehler", message)

    dialog.widgetValueChanged.connect(handle_change)

    if bool(config["fill_on_form_open"]):
        try:
            current = dialog.currentFormFeature()
            initial = current[path_field]
            if initial:
                handle_change(path_field, initial, True)
            if operator_name_field:
                initial_operator_name = current[operator_name_field]
                if initial_operator_name:
                    handle_change(operator_name_field, initial_operator_name, True)
        except Exception:
            pass
