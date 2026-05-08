#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from plugin_repository_tools import (
    build_catalog_entries,
    build_master_entry,
    resolve_repo_raw_base_url,
    write_catalog_snapshot,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Erzeugt den Master-Katalog-Snapshot aus den Einzelplugin-Metadaten."
    )
    parser.add_argument("--root-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root_dir = Path(args.root_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    master_entry = build_master_entry(root_dir, raw_base_url="")
    raw_base_url = resolve_repo_raw_base_url(
        root_dir,
        fallback_repository_url=master_entry["metadata"].get("repository", ""),
    )
    entries = build_catalog_entries(root_dir, raw_base_url)

    write_catalog_snapshot(entries, output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
