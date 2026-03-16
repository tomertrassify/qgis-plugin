# Trassify Master Tools

Ein einzelnes QGIS-Plugin, das mehrere vorhandene Tools als eingebettete Module gemeinsam ausliefert.

Enthaltene Module:
- AttributionButler
- Custom Tool Leiste
- Schutzrohr
- Freehand raster georeferencer
- GeoBasis Loader
- Coordinatify
- QuickMapServices
- Grid Quick GeoJSON Export
- Layer Fuser
- Map Search Pro
- Projektstarter
- Quickrule
- Export Pro

Hinweise:
- Die eingebetteten Modulpakete liegen gesammelt unter `trassify_master_tools/bundled_plugins/`.
- Fuer `Coordinatify` ist die erweiterte Variante aus `plugin_sources/geobasis-pro/coordinatify` gebuendelt.
- Doppelte Temp-Kopien aus `plugin_sources/googlemaps/` und `plugin_sources/max-wild/funktionen-temp/` wurden bewusst nicht mehrfach eingebunden.
- Das Master-Plugin laedt beim Aktivieren keine eingebetteten Module automatisch mehr. Jedes Modul wird gezielt ueber das Master-Menue geladen.
- Wenn ein gleichnamiges Einzelplugin bereits separat in QGIS aktiv ist, blockiert das Master-Plugin das Nachladen bewusst, damit keine doppelten Menueeintraege oder Paketkonflikte entstehen.

Build:
- `./build_zip.sh`
- Ausgabe: `dist/trassify_master_tools-<version>.zip`
