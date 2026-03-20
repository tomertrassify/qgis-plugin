# Trassify Master Tools

Ein einzelnes QGIS-Plugin, das mehrere vorhandene Tools als eingebettete Module gemeinsam ausliefert.

Enthaltene Module:
- AttributionButler
- Schutzrohr
- Freehand raster georeferencer
- GeoBasis Loader
- Coordinatify
- QuickMapServices
- Grid Quick GeoJSON Export
- Layer Fuser
- Projektstarter
- Quickrule
- Export Pro

Hinweise:
- Das Git-Repo enthaelt nur die Master-Struktur. Die eingebetteten Modulpakete werden erst beim Build in das ZIP unter `bundled_plugins/` erzeugt.
- Normale Tools landen im Bundle unter `bundled_plugins/interactive/`, Hintergrundtools unter `bundled_plugins/background/`.
- Fuer `Coordinatify` ist die erweiterte Variante aus `plugin_sources/background-tools/coordinatify` gebuendelt.
- Doppelte Temp-Kopien aus `plugin_sources/googlemaps/` und `plugin_sources/max-wild/funktionen-temp/` wurden bewusst nicht mehrfach eingebunden.
- In QGIS erscheint das Master-Plugin mit eigenem Icon in der Toolbar. Ein Klick oeffnet eine Uebersicht aller enthaltenen Module mit Status und Ladefunktion.
- Das Master-Plugin unterscheidet zwischen normalen Tools und Hintergrundtools.
- Normale Tools koennen ueber die Master-Uebersicht geladen werden; als Favorit markierte Tools werden beim Start automatisch mitgeladen.
- Hintergrundtools werden beim Start automatisch aktiviert, damit Kontextmenues und unauffaellige Hilfsfunktionen sofort verfuegbar sind.
- Wenn ein gleichnamiges Einzelplugin bereits separat in QGIS aktiv ist, blockiert das Master-Plugin das Nachladen bewusst, damit keine doppelten Menueeintraege oder Paketkonflikte entstehen.

Build:
- `./build_zip.sh`
- Ausgabe: `dist/trassify_master_tools-<version>.zip`
