from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from qgis.PyQt.QtCore import QSettings
from qgis.core import QgsProject


PROFILE_FILENAME = "projektstarter-butler.json"
PROJECT_ROOT_PLACEHOLDER = "{{PROJECT_ROOT}}"
LOCAL_ROOTS_SETTINGS_KEY = "TrassifyMasterTools/shared_settings/local_nextcloud_roots"
LOCAL_ROOT_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*lokale\s*sync-roots\s*\}\}", flags=re.IGNORECASE)
PROJECT_INFO_DIRNAME = "001_Projektinfos"
PROFILE_VERSION = 1
PROJECT_PROFILE_SCOPE = "projektstarter_butler_profile"
PROJECT_PROFILE_ENTRY_KEY = "profile_json"


def _default_profile() -> dict:
    return {
        "version": PROFILE_VERSION,
        "shared_settings": {},
        "layers": [],
    }


def current_project_file() -> Path | None:
    file_name = str(QgsProject.instance().fileName() or "").strip()
    if not file_name:
        return None
    try:
        return Path(file_name).expanduser()
    except TypeError:
        return None


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


def _local_nextcloud_roots() -> list[str]:
    settings = QSettings()
    return _parse_string_list(settings.value(LOCAL_ROOTS_SETTINGS_KEY, None))


def _expand_local_root_placeholder(value: str) -> Path | None:
    text = str(value or "").strip()
    if not text or not LOCAL_ROOT_PLACEHOLDER_PATTERN.search(text):
        return None

    for root in _local_nextcloud_roots():
        root_text = str(root or "").strip().rstrip("/\\")
        if not root_text:
            continue
        expanded = LOCAL_ROOT_PLACEHOLDER_PATTERN.sub(lambda _match: root_text, text)
        try:
            candidate = Path(expanded).expanduser()
        except TypeError:
            continue
        if candidate.is_absolute():
            return candidate

    return None


def _resolve_path_reference(value: str, project_file: Path | None = None) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None

    local_root_path = _expand_local_root_placeholder(text)
    if local_root_path is not None:
        return local_root_path

    try:
        candidate = Path(text).expanduser()
    except TypeError:
        return None

    if candidate.is_absolute():
        return candidate

    target_project_file = project_file or current_project_file()
    if target_project_file is None:
        return None

    try:
        return (target_project_file.parent / candidate).resolve()
    except OSError:
        return target_project_file.parent / candidate


def detect_project_root() -> Path | None:
    project = QgsProject.instance()
    project_file = current_project_file()

    preset_home = str(project.presetHomePath() or "").strip()
    if preset_home:
        resolved_preset_home = _resolve_path_reference(preset_home, project_file)
        if resolved_preset_home is not None:
            return resolved_preset_home

    if project_file is None:
        return None

    if project_file.parent.name == PROJECT_INFO_DIRNAME:
        return project_file.parent.parent
    return project_file.parent


def _preferred_profile_path(project_root: Path) -> Path:
    return project_root / PROJECT_INFO_DIRNAME / PROFILE_FILENAME


def _legacy_profile_path(project_root: Path) -> Path:
    return project_root / PROFILE_FILENAME


def profile_path(project_root: Path | None = None) -> Path | None:
    del project_root
    return current_project_file()


def _existing_profile_path(project_root: Path | None = None) -> Path | None:
    root = project_root or detect_project_root()
    if root is None:
        return None

    preferred = _preferred_profile_path(root)
    if preferred.is_file():
        return preferred

    legacy = _legacy_profile_path(root)
    if legacy.is_file():
        return legacy

    return preferred


def current_profile_path_string() -> str:
    return "Im QGIS-Projekt (.qgz) gespeichert"


def _normalize_single_path(value: str, project_root: Path | None) -> str:
    text = str(value or "").strip()
    if not text or project_root is None or PROJECT_ROOT_PLACEHOLDER in text:
        return text

    try:
        candidate = Path(text).expanduser()
    except TypeError:
        return text

    if not candidate.is_absolute():
        return text

    try:
        relative = candidate.resolve().relative_to(project_root.resolve())
    except Exception:
        return text

    relative_posix = relative.as_posix()
    if not relative_posix or relative_posix == ".":
        return PROJECT_ROOT_PLACEHOLDER
    return f"{PROJECT_ROOT_PLACEHOLDER}/{relative_posix}"


def _expand_single_path(value: str, project_root: Path | None) -> str:
    text = str(value or "").strip()
    if not text or project_root is None or PROJECT_ROOT_PLACEHOLDER not in text:
        return text

    if text == PROJECT_ROOT_PLACEHOLDER:
        return str(project_root)

    prefix = f"{PROJECT_ROOT_PLACEHOLDER}/"
    if not text.startswith(prefix):
        return text

    suffix = text[len(prefix):].strip().replace("\\", "/")
    if not suffix:
        return str(project_root)
    return str((project_root / Path(suffix)).resolve())


def _normalize_layer_source(source: str, project_root: Path | None) -> str:
    text = str(source or "").strip()
    if not text or project_root is None or text.startswith("PG:"):
        return text

    if "|" not in text:
        return _normalize_single_path(text, project_root)

    head, tail = text.split("|", 1)
    return f"{_normalize_single_path(head, project_root)}|{tail}"


def _normalize_config_paths(config: dict, project_root: Path | None) -> dict:
    result = copy.deepcopy(config or {})

    roots = result.get("local_nextcloud_roots", [])
    if isinstance(roots, list):
        result["local_nextcloud_roots"] = [
            _normalize_single_path(path, project_root) for path in roots
        ]

    operators = result.get("operators", [])
    if isinstance(operators, list):
        for entry in operators:
            if isinstance(entry, dict):
                entry["folder_path"] = _normalize_single_path(entry.get("folder_path", ""), project_root)

    data_sources = result.get("external_data_sources", [])
    if isinstance(data_sources, list):
        for entry in data_sources:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("source_type", "file") or "file").strip().lower() == "file":
                entry["source"] = _normalize_single_path(entry.get("source", ""), project_root)

    result["nextcloud_app_password"] = ""
    return result


def _expand_config_paths(config: dict, project_root: Path | None) -> dict:
    result = copy.deepcopy(config or {})

    roots = result.get("local_nextcloud_roots", [])
    if isinstance(roots, list):
        result["local_nextcloud_roots"] = [
            _expand_single_path(path, project_root) for path in roots
        ]

    operators = result.get("operators", [])
    if isinstance(operators, list):
        for entry in operators:
            if isinstance(entry, dict):
                entry["folder_path"] = _expand_single_path(entry.get("folder_path", ""), project_root)

    data_sources = result.get("external_data_sources", [])
    if isinstance(data_sources, list):
        for entry in data_sources:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("source_type", "file") or "file").strip().lower() == "file":
                entry["source"] = _expand_single_path(entry.get("source", ""), project_root)

    return result


def normalize_config_for_storage(config: dict, project_root: Path | None = None) -> dict:
    return _normalize_config_paths(config, project_root or detect_project_root())


def expand_config_from_storage(config: dict, project_root: Path | None = None) -> dict:
    return _expand_config_paths(config, project_root or detect_project_root())


def _layer_signature(layer, project_root: Path | None = None) -> dict:
    return {
        "name": str(layer.name() or "").strip(),
        "provider": str(layer.providerType() or "").strip(),
        "source": _normalize_layer_source(str(layer.source() or "").strip(), project_root),
    }


def _find_layer_index(profile: dict, layer, project_root: Path | None = None) -> int:
    signature = _layer_signature(layer, project_root)
    layers = profile.get("layers", [])
    if not isinstance(layers, list):
        return -1

    for index, entry in enumerate(layers):
        if not isinstance(entry, dict):
            continue
        if (
            str(entry.get("name", "")).strip() == signature["name"]
            and str(entry.get("provider", "")).strip() == signature["provider"]
            and str(entry.get("source", "")).strip() == signature["source"]
        ):
            return index

    for index, entry in enumerate(layers):
        if not isinstance(entry, dict):
            continue
        if (
            str(entry.get("name", "")).strip() == signature["name"]
            and str(entry.get("provider", "")).strip() == signature["provider"]
        ):
            return index

    return -1


def load_project_profile(project_root: Path | None = None) -> dict:
    project = QgsProject.instance()
    serialized, ok = project.readEntry(PROJECT_PROFILE_SCOPE, PROJECT_PROFILE_ENTRY_KEY, "")
    if ok and str(serialized or "").strip():
        try:
            loaded = json.loads(serialized)
        except Exception:
            loaded = None
        if isinstance(loaded, dict):
            profile = _default_profile()
            profile["version"] = int(loaded.get("version", PROFILE_VERSION) or PROFILE_VERSION)

            shared_settings = loaded.get("shared_settings", {})
            if isinstance(shared_settings, dict):
                profile["shared_settings"] = shared_settings

            layers = loaded.get("layers", [])
            if isinstance(layers, list):
                profile["layers"] = [entry for entry in layers if isinstance(entry, dict)]
            return profile

    path = _existing_profile_path(project_root)
    if path is None or not path.is_file():
        return _default_profile()

    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
    except Exception:
        return _default_profile()

    if not isinstance(loaded, dict):
        return _default_profile()

    profile = _default_profile()
    profile["version"] = int(loaded.get("version", PROFILE_VERSION) or PROFILE_VERSION)

    shared_settings = loaded.get("shared_settings", {})
    if isinstance(shared_settings, dict):
        profile["shared_settings"] = shared_settings

    layers = loaded.get("layers", [])
    if isinstance(layers, list):
        profile["layers"] = [entry for entry in layers if isinstance(entry, dict)]

    return profile


def save_project_profile(profile: dict, project_root: Path | None = None) -> Path | None:
    serializable = _default_profile()
    if isinstance(profile, dict):
        serializable["version"] = int(profile.get("version", PROFILE_VERSION) or PROFILE_VERSION)
        if isinstance(profile.get("shared_settings"), dict):
            serializable["shared_settings"] = profile["shared_settings"]
        if isinstance(profile.get("layers"), list):
            serializable["layers"] = [entry for entry in profile["layers"] if isinstance(entry, dict)]

    QgsProject.instance().writeEntry(
        PROJECT_PROFILE_SCOPE,
        PROJECT_PROFILE_ENTRY_KEY,
        json.dumps(serializable, ensure_ascii=False, indent=2),
    )
    del project_root
    return current_project_file()


def load_shared_settings(project_root: Path | None = None) -> dict:
    root = project_root or detect_project_root()
    profile = load_project_profile(root)
    shared_settings = profile.get("shared_settings", {})
    if not isinstance(shared_settings, dict):
        return {}
    return _expand_config_paths(shared_settings, root)


def save_shared_settings_from_config(config: dict, project_root: Path | None = None) -> Path | None:
    root = project_root or detect_project_root()
    if root is None:
        return None

    profile = load_project_profile(root)
    shared_settings = {
        "nextcloud_base_url": str(config.get("nextcloud_base_url", "") or "").strip(),
        "nextcloud_user": str(config.get("nextcloud_user", "") or "").strip(),
        "nextcloud_folder_marker": str(config.get("nextcloud_folder_marker", "") or "").strip(),
    }
    profile["shared_settings"] = _normalize_config_paths(shared_settings, root)
    return save_project_profile(profile, root)


def load_layer_profile_config(layer, project_root: Path | None = None) -> dict:
    root = project_root or detect_project_root()
    profile = load_project_profile(root)
    index = _find_layer_index(profile, layer, root)
    if index < 0:
        return {}

    entry = profile["layers"][index]
    config = entry.get("config", {})
    if not isinstance(config, dict):
        return {}
    return _expand_config_paths(config, root)


def save_layer_profile_config(layer, config: dict, project_root: Path | None = None) -> Path | None:
    root = project_root or detect_project_root()
    if root is None:
        return None

    profile = load_project_profile(root)
    layer_entry = _layer_signature(layer, root)
    layer_entry["config"] = _normalize_config_paths(config, root)

    index = _find_layer_index(profile, layer, root)
    if index < 0:
        profile.setdefault("layers", []).append(layer_entry)
    else:
        profile["layers"][index] = layer_entry

    return save_project_profile(profile, root)
