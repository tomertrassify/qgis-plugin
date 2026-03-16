# QGIS Plugins Repository

Repository-Struktur:

- `trassify_master_tools/`
  Das installierbare Master-Plugin. Diese Struktur steht bewusst direkt auf Repo-Ebene im Vordergrund.
- `plugin_sources/`
  Die einzige Quellablage fuer die Einzelplugins. Das ist die Quelle der Wahrheit, nicht das installierbare Master-Plugin.
- `dist/`
  Gebaute ZIP-Artefakte.
- `plugins.xml`
  Die QGIS-Repository-Datei fuer die direkte Einbindung per URL.
- `trassify_master_tools.zip`
  Das Root-ZIP fuer das einfache GitHub-Repo-Schema `plugins.xml + plugin.zip`.
- `preview/master-plugin-overlay-preview.html`
  Interaktive HTML-Vorschau fuer Toolbar, Overlay und Modulstatus des Master-Plugins.

Wichtig:

- Wenn du nur ein Plugin in QGIS installieren willst, nutze das Bundle aus `trassify_master_tools/`.
- Die eingebetteten Modulkopien fuer das Bundle werden beim Build aus `plugin_sources/` erzeugt und liegen nicht mehr doppelt im Git-Repo.
- Die Originalquellen bleiben unter `plugin_sources/`, damit jede Plugin-Datei nur noch einmal im Repository gepflegt wird.
- In QGIS oeffnet das Master-Plugin ueber sein Toolbar-Icon eine Uebersicht aller enthaltenen Module.
- Das Master-Plugin laedt beim Aktivieren keine eingebetteten Tools mehr automatisch, sondern nur noch gezielt ueber das Plugin-Menue. Das reduziert Konflikte und Abstuerze in QGIS.
- Fuer das GitHub-Setup kannst du `./prepare_plugin_repository.sh` ausfuehren. Das aktualisiert `plugins.xml` und `trassify_master_tools.zip`.
- Fuer schnelle UI/UX-Runden kannst du `preview/master-plugin-overlay-preview.html` direkt im Browser oeffnen.
