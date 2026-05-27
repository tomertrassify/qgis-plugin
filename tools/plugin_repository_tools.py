from __future__ import annotations

import configparser
import json
import runpy
import subprocess
import zipfile
from datetime import date
from pathlib import Path
from typing import Iterable
from urllib.parse import quote


MASTER_PLUGIN_DIR = "trassify_master_tools"
MASTER_PLUGIN_ZIP_NAME = f"{MASTER_PLUGIN_DIR}.zip"
LOCAL_PLUGIN_SOURCE_BACKUP_DIR = Path("dist") / "local-plugin-source-backup" / "plugin_sources"
IGNORE_DIR_NAMES = {"__pycache__", "dist"}
IGNORE_FILE_SUFFIXES = {".pyc", ".pyo", ".zip"}
IGNORE_FILE_NAMES = {".DS_Store"}


def load_manifest(root_dir: Path) -> tuple[dict, ...]:
    manifest_path = root_dir / MASTER_PLUGIN_DIR / "manifest.py"
    manifest_globals = runpy.run_path(str(manifest_path))
    return tuple(manifest_globals["BUNDLED_PLUGINS"])


def read_metadata(metadata_path: Path) -> dict[str, str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str

    for encoding in ("utf-8", "latin-1"):
        try:
            with metadata_path.open(encoding=encoding) as handle:
                parser.read_file(handle)
            break
        except UnicodeDecodeError:
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str
            continue

    if not parser.has_section("general"):
        return {}

    return {
        key: value.strip()
        for key, value in parser.items("general")
    }


def resolve_repo_raw_base_url(root_dir: Path, fallback_repository_url: str = "") -> str:
    repository_url = ""

    try:
        result = subprocess.run(
            ["git", "-C", str(root_dir), "remote", "get-url", "origin"],
            check=True,
            capture_output=True,
            text=True,
        )
        repository_url = result.stdout.strip()
    except Exception:
        repository_url = ""

    if not repository_url:
        repository_url = str(fallback_repository_url or "").strip()

    slug = github_repo_slug(repository_url)
    if not slug:
        raise SystemExit(
            "GitHub-Repository konnte nicht aufgeloest werden. "
            "Bitte origin-Remote oder repository-Metadatum pruefen."
        )

    return f"https://raw.githubusercontent.com/{slug}/main"


def github_repo_slug(repository_url: str) -> str:
    text = str(repository_url or "").strip()
    if not text:
        return ""

    text = text.removesuffix(".git")
    prefixes = (
        "https://github.com/",
        "http://github.com/",
        "git@github.com:",
        "ssh://git@github.com/",
    )
    for prefix in prefixes:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break

    return text.strip("/")


def build_plugins_xml_url(raw_base_url: str) -> str:
    return f"{raw_base_url}/plugins.xml"


def source_dir_for_spec(root_dir: Path, spec: dict) -> Path | None:
    source_path_text = str(spec.get("source_path") or "").strip()
    if not source_path_text:
        return None

    source_path = Path(source_path_text)
    backup_dir = root_dir / LOCAL_PLUGIN_SOURCE_BACKUP_DIR / source_path
    if backup_dir.is_dir():
        return backup_dir
    return root_dir / "plugin_sources" / source_path


def stable_zip_name(package_name: str) -> str:
    return f"{package_name}.zip"


def versioned_zip_path(dist_dir: Path, package_name: str, version: str) -> Path:
    return dist_dir / f"{package_name}-{version}.zip"


def build_catalog_entries(root_dir: Path, raw_base_url: str) -> list[dict]:
    plugins_xml_url = build_plugins_xml_url(raw_base_url)
    entries: list[dict] = []

    for spec in load_manifest(root_dir):
        source_dir = source_dir_for_spec(root_dir, spec)
        has_local_source = source_dir is not None and source_dir.is_dir()
        metadata = dict(spec.get("metadata") or {})
        metadata_path = None
        if has_local_source:
            metadata_path = source_dir / "metadata.txt"
            source_metadata = read_metadata(metadata_path)
            if source_metadata:
                metadata = {**metadata, **source_metadata}

        icon_source_path = None
        if has_local_source:
            icon_source_path = resolve_icon_source_path(source_dir, metadata.get("icon", ""))

        icon_relative_path = str(spec.get("icon_relative_path") or "").strip()
        if not icon_relative_path and icon_source_path is not None:
            icon_relative_path = f"icons/{spec['package']}{icon_source_path.suffix.lower() or '.svg'}"

        download_url = str(spec.get("download_url") or "").strip()
        if not download_url and has_local_source:
            download_url = f"{raw_base_url}/{stable_zip_name(spec['package'])}"

        icon_url = str(spec.get("icon_url") or "").strip()
        if not icon_url:
            icon_url = build_icon_url(raw_base_url, icon_source_path, root_dir)

        entry = {
            "key": spec["key"],
            "label": spec["label"],
            "package": spec["package"],
            "source_path": str(spec.get("source_path") or "").strip(),
            "tool_type": spec["tool_type"],
            "zip_name": stable_zip_name(spec["package"]),
            "download_url": download_url,
            "plugins_xml_url": plugins_xml_url,
            "icon_relative_path": icon_relative_path,
            "icon_url": icon_url,
            "metadata": metadata,
            "source_dir": str(source_dir) if has_local_source else "",
            "metadata_path": str(metadata_path) if metadata_path else "",
            "icon_source_path": str(icon_source_path) if icon_source_path else "",
            "has_local_source": has_local_source,
        }
        entries.append(entry)

    return entries


def build_master_entry(root_dir: Path, raw_base_url: str) -> dict:
    metadata_path = root_dir / MASTER_PLUGIN_DIR / "metadata.txt"
    metadata = read_metadata(metadata_path)
    icon_path = root_dir / MASTER_PLUGIN_DIR / (metadata.get("icon") or "icon.svg")

    return {
        "package": MASTER_PLUGIN_DIR,
        "zip_name": MASTER_PLUGIN_ZIP_NAME,
        "download_url": f"{raw_base_url}/{MASTER_PLUGIN_ZIP_NAME}",
        "icon_url": build_icon_url(raw_base_url, icon_path, root_dir),
        "metadata": metadata,
    }


def resolve_icon_source_path(source_dir: Path, icon_name: str) -> Path | None:
    explicit_icon = source_dir / str(icon_name or "").strip()
    if icon_name and explicit_icon.is_file():
        return explicit_icon

    for fallback_name in ("icon.svg", "icon.png", "icon.ico"):
        candidate = source_dir / fallback_name
        if candidate.is_file():
            return candidate

    return None


def build_icon_url(raw_base_url: str, icon_path: Path | None, root_dir: Path) -> str:
    if icon_path is None:
        return ""

    try:
        relative = icon_path.resolve().relative_to(root_dir.resolve())
    except Exception:
        return ""

    return f"{raw_base_url}/{quote(relative.as_posix(), safe='/')}"


def write_catalog_snapshot(entries: Iterable[dict], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    icons_dir = output_dir / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)

    serialized_entries = []
    for entry in entries:
        icon_source_path = Path(entry["icon_source_path"]) if entry.get("icon_source_path") else None
        icon_relative_path = str(entry.get("icon_relative_path") or "").strip()
        if icon_source_path is not None and icon_relative_path:
            destination = output_dir / icon_relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(icon_source_path.read_bytes())

        serialized_entries.append(
            {
                "key": entry["key"],
                "label": entry["label"],
                "package": entry["package"],
                "source_path": entry["source_path"],
                "tool_type": entry["tool_type"],
                "zip_name": entry["zip_name"],
                "download_url": entry["download_url"],
                "plugins_xml_url": entry["plugins_xml_url"],
                "icon_relative_path": icon_relative_path,
                "icon_url": entry["icon_url"],
                "metadata": entry["metadata"],
            }
        )

    snapshot = {
        "generated_on": date.today().isoformat(),
        "plugins_xml_url": serialized_entries[0]["plugins_xml_url"] if serialized_entries else "",
        "modules": serialized_entries,
    }
    (output_dir / "plugins.json").write_text(
        json.dumps(snapshot, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def build_plugin_zip(source_dir: Path, package_name: str, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in iter_plugin_files(source_dir):
            relative = file_path.relative_to(source_dir)
            archive_name = Path(package_name) / relative
            archive.write(file_path, archive_name.as_posix())


def iter_plugin_files(source_dir: Path) -> Iterable[Path]:
    for path in sorted(source_dir.rglob("*")):
        if path.is_dir():
            continue
        relative_parts = path.relative_to(source_dir).parts
        if should_ignore_path(relative_parts):
            continue
        yield path


def should_ignore_path(relative_parts: tuple[str, ...]) -> bool:
    if any(part in IGNORE_DIR_NAMES for part in relative_parts[:-1]):
        return True

    file_name = relative_parts[-1]
    if file_name in IGNORE_FILE_NAMES:
        return True

    file_path = Path(file_name)
    if file_path.suffix.lower() in IGNORE_FILE_SUFFIXES:
        return True

    return False


def write_plugins_xml(entries: Iterable[dict], output_path: Path) -> None:
    today = date.today().isoformat()
    plugin_entries = list(entries)
    lines = ["<?xml version='1.0' encoding='UTF-8'?>", "<plugins>"]

    for entry in plugin_entries:
        metadata = entry["metadata"]
        lines.extend(
            [
                f"  <pyqgis_plugin name=\"{xml_escape(metadata.get('name') or entry.get('package', ''))}\" version=\"{xml_escape(metadata.get('version', ''))}\">",
                f"    <description><![CDATA[{xml_cdata(metadata.get('description', ''))}]]></description>",
                f"    <about><![CDATA[{xml_cdata(metadata.get('about', ''))}]]></about>",
                f"    <version>{xml_escape(metadata.get('version', ''))}</version>",
                f"    <qgis_minimum_version>{xml_escape(metadata.get('qgisMinimumVersion', ''))}</qgis_minimum_version>",
                f"    <qgis_maximum_version>{xml_escape(metadata.get('qgisMaximumVersion', ''))}</qgis_maximum_version>",
                f"    <homepage><![CDATA[{xml_cdata(metadata.get('homepage', ''))}]]></homepage>",
                f"    <file_name>{xml_escape(entry['zip_name'])}</file_name>",
                f"    <icon><![CDATA[{xml_cdata(entry.get('icon_url', ''))}]]></icon>",
                f"    <author_name><![CDATA[{xml_cdata(metadata.get('author', ''))}]]></author_name>",
                f"    <download_url><![CDATA[{xml_cdata(entry.get('download_url', ''))}]]></download_url>",
                f"    <uploaded_by><![CDATA[{xml_cdata(metadata.get('author', ''))}]]></uploaded_by>",
                f"    <create_date>{today}</create_date>",
                f"    <update_date>{today}</update_date>",
                f"    <experimental>{xml_escape(str(metadata.get('experimental', 'False')).lower())}</experimental>",
                f"    <deprecated>{xml_escape(str(metadata.get('deprecated', 'False')).lower())}</deprecated>",
                f"    <tracker><![CDATA[{xml_cdata(metadata.get('tracker', ''))}]]></tracker>",
                f"    <repository><![CDATA[{xml_cdata(metadata.get('repository', ''))}]]></repository>",
                f"    <tags><![CDATA[{xml_cdata(metadata.get('tags', ''))}]]></tags>",
                "    <server>False</server>",
                "  </pyqgis_plugin>",
            ]
        )

    lines.append("</plugins>")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def xml_escape(value: str) -> str:
    text = str(value or "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\"", "&quot;")
    )


def xml_cdata(value: str) -> str:
    return str(value or "").replace("]]>", "]]]]><![CDATA[>")
