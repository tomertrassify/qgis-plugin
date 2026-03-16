#!/usr/bin/env python3
from __future__ import annotations

import argparse
import runpy
import shutil
from pathlib import Path


IGNORE_PATTERNS = (
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    "dist",
    "*.zip",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assemble bundled QGIS plugin packages from plugin_sources."
    )
    parser.add_argument("--root-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def load_manifest(root_dir: Path):
    manifest_path = root_dir / "trassify_master_tools" / "manifest.py"
    manifest_globals = runpy.run_path(str(manifest_path))
    return manifest_globals["BUNDLED_PLUGINS"]


def copy_plugin(source_dir: Path, destination_dir: Path) -> None:
    shutil.copytree(
        source_dir,
        destination_dir,
        ignore=shutil.ignore_patterns(*IGNORE_PATTERNS),
    )


def main() -> int:
    args = parse_args()
    root_dir = Path(args.root_dir).resolve()
    source_root = root_dir / "plugin_sources"
    output_dir = Path(args.output_dir).resolve()

    bundled_plugins = load_manifest(root_dir)

    if not source_root.is_dir():
        raise SystemExit(f"plugin_sources nicht gefunden: {source_root}")

    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    for spec in bundled_plugins:
        source_path = source_root / spec["source_path"]
        destination_path = output_dir / spec["package"]

        if not source_path.is_dir():
            raise SystemExit(f"Quellpfad fehlt fuer {spec['label']}: {source_path}")

        copy_plugin(source_path, destination_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
