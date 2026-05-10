from __future__ import annotations

import argparse
import configparser
import importlib.util
import json
import shutil
from pathlib import Path

LOCAL_ZIP_BACKUP_DIR = Path("dist") / "local-plugin-zip-backup"


def load_manifest(repo_root: Path):
    manifest_path = repo_root / "trassify_master_tools" / "manifest.py"
    spec = importlib.util.spec_from_file_location("trassify_manifest", manifest_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return tuple(module.BUNDLED_PLUGINS)


def read_metadata(metadata_path: Path) -> dict:
    if not metadata_path.is_file():
        return {}

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


def write_readme(output_dir: Path) -> None:
    content = """# Nextcloud Master Catalog

Diese Struktur ist fuer den geschuetzten Katalog von `trassify_master_tools` gedacht.

Inhalt:
- `catalog/plugins.json`: beschreibt die installierbaren Plugins
- `packages/*.zip`: die eigentlichen Plugin-Pakete

Upload:
1. Diesen kompletten Ordner in den in den Master-Einstellungen gesetzten Nextcloud-Ordner hochladen.
2. Beispiel: Wenn im Master `Trassify Allgemein/Plug-In/nextcloud-master-catalog` steht, dann muessen `catalog/` und `packages/`
   direkt darunter liegen.
3. Passe in `catalog/plugins.json` optional pro Plugin die `groups` an.

Lokale ZIP-Quelle:
- Fuer den Build sucht dieses Skript zuerst unter `dist/local-plugin-zip-backup/` und danach im Repo-Root.

Gruppen:
- `[]` oder fehlend: fuer alle authentifizierten Nutzer sichtbar
- `["gruppe-a", "gruppe-b"]`: nur fuer Nutzer, die in mindestens einer dieser Nextcloud-Gruppen sind
- `["*"]`: explizit fuer alle authentifizierten Nutzer

Wichtig:
- Die eigentlichen Zugriffsrechte auf die ZIPs solltest du zusaetzlich ueber Nextcloud-Freigaben/Ordnerrechte absichern.
- Nach einer Installation liegt Python-Code lokal beim berechtigten Nutzer vor.
"""
    (output_dir / "README.md").write_text(content, encoding="utf-8")


def build_catalog(repo_root: Path, output_dir: Path) -> tuple[int, list[str]]:
    manifest = load_manifest(repo_root)
    packages_dir = output_dir / "packages"
    catalog_dir = output_dir / "catalog"
    packages_dir.mkdir(parents=True, exist_ok=True)
    catalog_dir.mkdir(parents=True, exist_ok=True)

    modules = []
    warnings = []

    for plugin_spec in manifest:
        package_name = str(plugin_spec["package"]).strip()
        zip_source = resolve_zip_source(repo_root, package_name)
        metadata = read_metadata(
            repo_root / "plugin_sources" / plugin_spec["source_path"] / "metadata.txt"
        )

        if zip_source is None or not zip_source.is_file():
            warnings.append(f"Fehlendes ZIP uebersprungen: {package_name}.zip")
            continue

        target_zip = packages_dir / zip_source.name
        shutil.copy2(zip_source, target_zip)
        modules.append(
            {
                "key": plugin_spec["key"],
                "label": plugin_spec["label"],
                "package": package_name,
                "version": str(metadata.get("version") or "").strip(),
                "archive_path": f"packages/{zip_source.name}",
                "groups": [],
            }
        )

    payload = {
        "modules": modules,
    }
    (catalog_dir / "plugins.json").write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    write_readme(output_dir)
    return len(modules), warnings


def resolve_zip_source(repo_root: Path, package_name: str) -> Path | None:
    zip_name = f"{package_name}.zip"
    candidates = (
        repo_root / LOCAL_ZIP_BACKUP_DIR / zip_name,
        repo_root / zip_name,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Erzeugt eine uploadbare Nextcloud-Katalogstruktur fuer Trassify Master Tools."
    )
    parser.add_argument(
        "--output",
        default="dist/nextcloud-master-catalog",
        help="Zielordner relativ zum Repo oder als absoluter Pfad",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    output_dir = Path(args.output)
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir

    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    count, warnings = build_catalog(repo_root, output_dir)
    print(f"Katalog erzeugt: {output_dir}")
    print(f"Module kopiert: {count}")
    for warning in warnings:
        print(f"WARNUNG: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
