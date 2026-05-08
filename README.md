# QGIS Plugins Repository

Repository-Struktur:

- `trassify_master_tools/`
  Das installierbare Master-Plugin. Es zeigt den Trassify-Katalog an und installiert Einzelplugins bei Bedarf.
- `plugin_sources/`
  Die einzige Quellablage fuer die Einzelplugins. Das ist die Quelle der Wahrheit, nicht das installierbare Master-Plugin.
  Hintergrundtools koennen dort separat unter `plugin_sources/background-tools/` liegen.
- `dist/`
  Gebaute ZIP-Artefakte mit versionsbezogenen Dateinamen.
- `plugins.xml`
  Die QGIS-Repository-Datei fuer die direkte Einbindung per URL. Sie enthaelt den Master-Katalog und alle separat installierbaren Plugins.
- `*.zip` im Repo-Root
  Die stabilen Download-Dateien fuer das GitHub-Repo-Schema `plugins.xml + plugin.zip`.

Wichtig:

- Die Originalquellen bleiben unter `plugin_sources/`, damit jede Plugin-Datei nur noch einmal im Repository gepflegt wird.
- In QGIS oeffnet das Master-Plugin ueber sein Toolbar-Icon eine Uebersicht aller bekannten Module.
- Plugins werden aus dem Master heraus erst bei Bedarf heruntergeladen, separat installiert und anschliessend aktiviert.
- Hintergrundtools sind ebenfalls optional und werden nicht mehr ungefragt mit dem Master mitgeliefert.
- Fuer das GitHub-Setup kannst du `./prepare_plugin_repository.sh` ausfuehren. Das aktualisiert `plugins.xml`, `trassify_master_tools.zip` und alle root-level Plugin-ZIPs.
- Fuer Projektstarter-Butler-Aenderungen gibt es zusaetzlich `python3 tools/release_projektstarter_butler.py`. Das synchronisiert die Version von `plugin_sources/projektstarter_attribution_buttler/metadata.txt` und `trassify_master_tools/metadata.txt` und baut anschliessend die GitHub-QGIS-Artefakte neu.
- Nach dem Push auf `main` uebernimmt `.github/workflows/release-projektstarter-butler.yml` denselben Ablauf automatisch und committed die aktualisierten Release-Dateien zurueck ins Repository. Damit reicht kuenftig ein Push, damit QGIS ein neues Update angeboten bekommt.
