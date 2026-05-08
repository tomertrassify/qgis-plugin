# Trassify Master Tools

Ein einzelnes QGIS-Plugin, das als Katalog und Installer fuer die Trassify-Tools dient.

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
- Projektstatus Butler
- Quickrule
- Export Pro

Hinweise:
- Das Master-Plugin enthaelt nur Katalog-Metadaten und Vorschaubilder, aber keinen eingebetteten Plugin-Code mehr.
- In QGIS erscheint das Master-Plugin mit eigenem Icon in der Toolbar. Ein Klick oeffnet eine Uebersicht aller bekannten Module mit Status, Installier-, Aktivier- und Entfernen-Aktionen.
- Nicht installierte Tools bleiben komplett ausserhalb des lokalen QGIS-Pluginordners.
- Favoriten dienen nur noch als Merkliste im Katalog; sie fuehren kein automatisches Laden mehr aus.
- Fuer Updates und Installationen liest das Master-Plugin denselben `plugins.xml`-Index, der auch fuer das QGIS-Repository bereitgestellt wird.
- Hintergrundtools bleiben im Katalog sichtbar, werden aber ebenfalls erst bei Bedarf installiert und aktiviert.

Build:
- `./build_zip.sh`
- Ausgabe: `dist/trassify_master_tools-<version>.zip`
