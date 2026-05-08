#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from plugin_repository_tools import (
    MASTER_PLUGIN_DIR,
    MASTER_PLUGIN_ZIP_NAME,
    build_catalog_entries,
    build_master_entry,
    build_plugin_zip,
    resolve_repo_raw_base_url,
    stable_zip_name,
    versioned_zip_path,
    write_plugins_xml,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Erzeugt alle QGIS-Repository-Artefakte: Master-ZIP, Einzelplugin-ZIPs "
            "und plugins.xml."
        )
    )
    parser.add_argument("--root-dir", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root_dir = Path(args.root_dir).resolve()
    dist_dir = root_dir / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    master_entry = build_master_entry(root_dir, raw_base_url="")
    raw_base_url = resolve_repo_raw_base_url(
        root_dir,
        fallback_repository_url=master_entry["metadata"].get("repository", ""),
    )
    master_entry = build_master_entry(root_dir, raw_base_url=raw_base_url)
    catalog_entries = build_catalog_entries(root_dir, raw_base_url)

    build_master_zip(root_dir)
    copy_master_zip_to_root(root_dir, dist_dir, master_entry["metadata"]["version"])

    for entry in catalog_entries:
        source_dir = root_dir / "plugin_sources" / entry["source_path"]
        version = entry["metadata"].get("version", "").strip() or "dev"
        versioned_zip = versioned_zip_path(dist_dir, entry["package"], version)
        stable_zip = root_dir / stable_zip_name(entry["package"])

        build_plugin_zip(source_dir, entry["package"], versioned_zip)
        shutil.copyfile(versioned_zip, stable_zip)

    write_plugins_xml(
        [master_entry, *catalog_entries],
        root_dir / "plugins.xml",
    )
    return 0


def build_master_zip(root_dir: Path) -> None:
    subprocess.run(
        [str(root_dir / MASTER_PLUGIN_DIR / "build_zip.sh")],
        cwd=root_dir,
        check=True,
    )


def copy_master_zip_to_root(root_dir: Path, dist_dir: Path, version: str) -> None:
    versioned_zip = dist_dir / f"{MASTER_PLUGIN_DIR}-{version}.zip"
    stable_zip = root_dir / MASTER_PLUGIN_ZIP_NAME
    shutil.copyfile(versioned_zip, stable_zip)


if __name__ == "__main__":
    raise SystemExit(main())
