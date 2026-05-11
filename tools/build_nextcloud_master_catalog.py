from __future__ import annotations

import argparse
import configparser
import importlib.util
import json
import shutil
from pathlib import Path

from plugin_repository_tools import build_plugin_zip, source_dir_for_spec


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
2. Beispiel: Wenn im Master `Trassify Allgemein/Qgis Plugins/nextcloud-master-catalog` steht, dann muessen `catalog/` und `packages/`
   direkt darunter liegen.
3. Passe in `catalog/plugins.json` optional pro Plugin die `groups` an.

Lokale Quellbasis:
- Fuer den Build werden die privaten Plugin-Quellen unter `dist/local-plugin-source-backup/plugin_sources/` verwendet.

Gruppen:
- `[]` oder fehlend: fuer alle authentifizierten Nutzer sichtbar
- `["gruppe-a", "gruppe-b"]`: nur fuer Nutzer, die in mindestens einer dieser Nextcloud-Gruppen sind
- `["*"]`: explizit fuer alle authentifizierten Nutzer

Wichtig:
- Die eigentlichen Zugriffsrechte auf die ZIPs solltest du zusaetzlich ueber Nextcloud-Freigaben/Ordnerrechte absichern.
- Nach einer Installation liegt Python-Code lokal beim berechtigten Nutzer vor.
- Fuer KI-/Editor-Kontext liegt zusaetzlich `AI_CONTEXT.md` in diesem Ordner.
"""
    (output_dir / "README.md").write_text(content, encoding="utf-8")


def write_ai_context(output_dir: Path) -> None:
    content = """# AI Context For Trassify Master Tools Plugins

Diese Datei ist fuer KI-Assistenten, Editoren und vibecoding-Workflows gedacht.
Sie beschreibt, wie QGIS-Plugins aufgebaut und gepflegt werden sollen, damit sie im
`trassify_master_tools` Katalog sauber erscheinen und konsistent ueber Nextcloud
verteilt werden koennen.

## Ziel

Jedes Plugin soll:
- als eigenstaendiges QGIS-Plugin funktionieren
- im Trassify Master Tool sauber dargestellt werden
- deutsche und englische Metadaten haben
- ueber den geschuetzten Nextcloud-Katalog installierbar sein
- konsistente Labels, Tags, Beschreibungen und Links mitbringen

## Wichtigster Architekturpunkt

Der geschuetzte Nextcloud-Katalog (`catalog/plugins.json`) steuert aktuell vor allem:
- Sichtbarkeit
- `archive_path`
- `version`
- `groups`

Die reichhaltigen Texte fuer die Mastertool-Liste kommen nicht primaer aus dem
Nextcloud-Katalog, sondern aus der Plugin-Quelle und deren `metadata.txt`.

Wenn du also Label, Beschreibung, About-Text, Tags oder Kategorie verbessern willst,
musst du die Plugin-Quelle anpassen und danach:
1. das Plugin-ZIP neu bauen
2. den Nextcloud-Katalog neu erzeugen bzw. hochladen
3. bei Aenderungen an Metadaten fuer die Master-Liste auch das Mastertool-Snapshot neu bauen

## Pflichtregeln fuer stabile Plugins

- `key` bleibt stabil und ist `snake_case`
- `package` bleibt stabil und entspricht exakt dem QGIS-Plugin-Ordnernamen
- `source_path` wird nicht leichtfertig geaendert
- ZIP-Struktur muss `<package>/...` enthalten
- keine Versionsnummern, Jahreszahlen oder Marketing-Praefixe im Label
- keine Emojis im Namen, in Beschreibungen oder Tags
- keine privaten URLs oder internen Zugangsdaten in Metadaten

## Benennung und Sortierung

Der Master sortiert Plugins im Wesentlichen nach dem sichtbaren Label.
Deshalb gelten diese Regeln:

- Das Label soll kurz und klar sein
- Idealerweise 1 bis 3 Woerter
- Keine Praefixe wie `Tool -`, `Trassify -`, `Plugin -`
- Externe Marken nicht umbenennen
- Gute Beispiele:
  - `GeoBasis Loader`
  - `Layer Fuser`
  - `QuickMapServices`
- Schlechte Beispiele:
  - `Trassify GeoBasis Loader Tool`
  - `Plugin fuer GeoBasis Daten`
  - `QuickMapServices 2026`

## Zweisprachige Metadaten

QGIS selbst liest Standardfelder wie `name`, `description`, `about`, `author`.
Das Trassify Master Tool kann zusaetzlich englische Custom-Felder lesen.

Fuer gute DE/EN-Darstellung bitte nach Moeglichkeit diese Felder pflegen:

- `name`
- `name_en`
- `description`
- `description_en`
- `about`
- `about_en`
- `category`
- `category_en`
- `tags`
- `tags_en`

Wichtig:
- Deutsch ist der Default
- Englisch ist ein zusaetzlicher Layer fuer den Master
- Wenn `*_en` fehlt, faellt das Mastertool auf Deutsch zurueck

## Stilregeln fuer Texte

### `name`
- sehr kurz
- Produkt-/Toolname
- keine Erklaersaetze

### `description`
- genau ein kurzer Nutzwertsatz
- beschreibt, was das Plugin tut
- keine Marketingfloskeln

Beispiel DE:
`Laedt GeoBasis-Daten und Hintergrundlayer schnell in das aktuelle QGIS-Projekt.`

Beispiel EN:
`Loads GeoBasis data and background layers quickly into the current QGIS project.`

### `about`
- 2 bis 4 kurze Saetze
- beschreibt Kontext, typische Nutzung und Besonderheiten
- darf etwas detailreicher als `description` sein

### `tags`
- kommasepariert
- klein geschrieben
- 4 bis 8 Tags sind ideal
- nur echte Suchbegriffe

Beispiel:
`geobasis,wms,wfs,basemap,data,background`

## Kategorien

Die Kategorie ist kein Muss, hilft aber in Details und Suche.
Bitte moeglichst mit einem kleinen, stabilen Vokabular arbeiten:

- `Data`
- `Background`
- `Planning`
- `Export`
- `Web`
- `Quality`
- `Utility`
- `Experimental`

Nicht bei jedem Plugin neue Fantasiekategorien einfuehren.

## Tool-Typen

Im Manifest gibt es aktuell zwei Typen:

- `INTERACTIVE_TOOL`
- `BACKGROUND_TOOL`

Nutze `BACKGROUND_TOOL` nur dann, wenn das Plugin eher still im Hintergrund arbeitet
oder Kontext-/Hilfsfunktionen bereitstellt.

## Externe Plugins

Wenn ein Plugin nicht von Trassify stammt, sondern auf einem fremden Repo basiert:

- Originalnamen beibehalten
- Originalautor nicht ueberschreiben
- Upstream-Repo hinterlegen
- Herkunft im Manifest markieren

Empfohlenes Manifest-Beispiel:

```python
{
    "key": "quick_map_services",
    "label": "QuickMapServices",
    "package": "quick_map_services",
    "source_path": "max-wild/funktionen-temp/quick_map_services",
    "tool_type": INTERACTIVE_TOOL,
    "origin": "external",
    "upstream_repository": "https://github.com/nextgis/quickmapservices",
}
```

Das erlaubt dem Mastertool z. B. den Filter `Other Plugins`.

## Beispiel fuer eine gute `metadata.txt`

```ini
[general]
name=GeoBasis Loader
name_en=GeoBasis Loader
description=Laedt GeoBasis-Daten und Hintergrundlayer schnell in das aktuelle QGIS-Projekt.
description_en=Loads GeoBasis data and background layers quickly into the current QGIS project.
about=Unterstuetzt das schnelle Laden typischer GeoBasis-Quellen in Trassify-Projekten. Das Plugin reduziert manuelle Einrichtungsarbeit und bringt haeufig genutzte Datenquellen in einen konsistenten Workflow.
about_en=Supports fast loading of common GeoBasis sources in Trassify projects. The plugin reduces manual setup work and brings frequently used data sources into a consistent workflow.
category=Data
category_en=Data
tags=geobasis,wms,wfs,basemap,data
tags_en=geobasis,wms,wfs,basemap,data
author=GeoObserver
homepage=https://github.com/geoObserver/geobasis_loader/
tracker=https://github.com/geoObserver/geobasis_loader/issues
repository=https://github.com/geoObserver/geobasis_loader/
experimental=False
```

## Checkliste vor dem Verpacken

- `metadata.txt` ist vorhanden
- `name`, `description`, `about` sind gepflegt
- `name_en`, `description_en`, `about_en` sind gepflegt
- `tags` und `tags_en` sind sinnvoll
- `experimental` ist korrekt gesetzt
- Icon ist vorhanden und lesbar
- `homepage`, `tracker`, `repository` stimmen
- `package` entspricht dem Plugin-Ordner
- ZIP enthaelt genau den richtigen Plugin-Root

## Checkliste vor dem Upload nach Nextcloud

- Plugin-ZIP neu gebaut
- Dateiname ist `packages/<package>.zip`
- `catalog/plugins.json` aktualisiert
- falls noetig `groups` gesetzt
- alte ZIP nicht versehentlich liegen gelassen

## Prompt fuer KI-Assistenten

Diesen Prompt kannst du als Startpunkt fuer KI-Editoren verwenden:

```text
You are editing a QGIS plugin that is distributed through the Trassify Master Tools ecosystem.

Your goals are:
- keep the plugin functional as a standalone QGIS plugin
- improve its metadata quality for the master catalog
- maintain German as the default language
- add or improve English metadata for the master catalog
- preserve stable package names, keys and archive structure

Important rules:
- do not rename package, key or source_path unless explicitly requested
- keep labels short, clean and sortable
- keep external plugin brand names unchanged
- update both German and English metadata when changing descriptions
- prefer concise, benefit-focused descriptions
- use clean lowercase tags
- preserve homepage, tracker and repository links
- if the plugin is external, keep upstream attribution intact
- do not add private URLs, credentials or internal-only text

When editing metadata, prefer these fields:
- name / name_en
- description / description_en
- about / about_en
- category / category_en
- tags / tags_en

Output should be production-ready and consistent with Trassify Master Tools.
```

## Kurzfassung fuer Menschen

Wenn du nur drei Dinge beachtest, dann diese:

1. Metadaten immer in Deutsch und Englisch pflegen
2. Labels kurz halten und Tags sauber setzen
3. Fuer sichtbare Mastertool-Texte nicht nur Nextcloud-JSON aendern, sondern die Plugin-Quelle
"""
    (output_dir / "AI_CONTEXT.md").write_text(content, encoding="utf-8")


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
        source_dir = source_dir_for_spec(repo_root, plugin_spec)
        metadata = read_metadata(source_dir / "metadata.txt")

        if not source_dir.is_dir():
            warnings.append(f"Fehlende Plugin-Quelle uebersprungen: {package_name}")
            continue

        target_zip = packages_dir / f"{package_name}.zip"
        build_plugin_zip(source_dir, package_name, target_zip)
        modules.append(
            {
                "key": plugin_spec["key"],
                "label": plugin_spec["label"],
                "package": package_name,
                "version": str(metadata.get("version") or "").strip(),
                "archive_path": f"packages/{target_zip.name}",
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
    write_ai_context(output_dir)
    return len(modules), warnings


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
