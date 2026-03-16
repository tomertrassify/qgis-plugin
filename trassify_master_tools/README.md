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
- Die eingebetteten Modulpakete liegen gesammelt unter `trassify_master_tools/modules/`.
- Fuer `Coordinatify` ist die erweiterte Variante aus `modules/geobasis-pro/coordinatify` gebuendelt.
- Doppelte Temp-Kopien aus `modules/googlemaps/` und `modules/max-wild/funktionen-temp/` wurden bewusst nicht mehrfach eingebunden.
- Das Master-Plugin laedt die Module gesammelt. In QGIS sollte die Einzelinstallation derselben Plugins deaktiviert bleiben, damit keine doppelten Menueeintraege entstehen.

Build:
- `./build_zip.sh`
- Ausgabe: `dist/trassify_master_tools-<version>.zip`
