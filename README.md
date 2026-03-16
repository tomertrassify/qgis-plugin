# QGIS Plugins Repository

Repository-Struktur:

- `trassify_master_tools/`
  Das installierbare Master-Plugin. Diese Struktur steht bewusst direkt auf Repo-Ebene im Vordergrund.
- `plugin_sources/`
  Die Einzelplugin-Quellen und Modulvorlagen. Das ist die Quellablage, nicht das installierbare Master-Plugin.
- `dist/`
  Gebaute ZIP-Artefakte.
- `plugins.xml`
  Die QGIS-Repository-Datei fuer die direkte Einbindung per URL.
- `trassify_master_tools.zip`
  Das Root-ZIP fuer das einfache GitHub-Repo-Schema `plugins.xml + plugin.zip`.

Wichtig:

- Wenn du nur ein Plugin in QGIS installieren willst, nutze das Bundle aus `trassify_master_tools/`.
- Die eingebetteten Modulkopien fuer das Bundle liegen in `trassify_master_tools/bundled_plugins/`.
- Die Originalquellen bleiben separat unter `plugin_sources/`, damit sie weiter einzeln gepflegt werden koennen.
- Das Master-Plugin laedt beim Aktivieren keine eingebetteten Tools mehr automatisch, sondern nur noch gezielt ueber das Plugin-Menue. Das reduziert Konflikte und Abstuerze in QGIS.
- Fuer das GitHub-Setup kannst du `./prepare_plugin_repository.sh` ausfuehren. Das aktualisiert `plugins.xml` und `trassify_master_tools.zip`.
