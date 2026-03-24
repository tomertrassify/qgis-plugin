from __future__ import annotations

import copy
import json
from pathlib import Path

from qgis.core import QgsProject


PROFILE_FILENAME = "projektstarter-butler.json"
PROJECT_ROOT_PLACEHOLDER = "{{PROJECT_ROOT}}"
PROJECT_INFO_DIRNAME = "001_Projektinfos"
PROFILE_VERSION = 1


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


def detect_project_root() -> Path | None:
    project = QgsProject.instance()

    preset_home = str(project.presetHomePath() or "").strip()
    if preset_home:
        try:
            return Path(preset_home).expanduser()
        except TypeError:
            return None

    project_file = current_project_file()
    if project_file is None:
        return None

    if project_file.parent.name == PROJECT_INFO_DIRNAME:
        return project_file.parent.parent
    return project_file.parent


def profile_path(project_root: Path | None = None) -> Path | None:
    root = project_root or detect_project_root()
    if root is None:
        return None
    return root / PROFILE_FILENAME


def current_profile_path_string() -> str:
    path = profile_path()
    return str(path) if path is not None else ""


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
    path = profile_path(project_root)
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
    path = profile_path(project_root)
    if path is None:
        return None

    serializable = _default_profile()
    if isinstance(profile, dict):
        serializable["version"] = int(profile.get("version", PROFILE_VERSION) or PROFILE_VERSION)
        if isinstance(profile.get("shared_settings"), dict):
            serializable["shared_settings"] = profile["shared_settings"]
        if isinstance(profile.get("layers"), list):
            serializable["layers"] = [entry for entry in profile["layers"] if isinstance(entry, dict)]

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(serializable, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


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
        "local_nextcloud_roots": list(config.get("local_nextcloud_roots", []) or []),
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
