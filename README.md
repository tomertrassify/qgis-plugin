# QGIS Plugins Repository

Repository-Struktur:

- `trassify_master_tools/`
  Das installierbare Master-Plugin. Diese Struktur steht bewusst direkt auf Repo-Ebene im Vordergrund.
- `plugin_sources/`
  Die einzige Quellablage fuer die Einzelplugins. Das ist die Quelle der Wahrheit, nicht das installierbare Master-Plugin.
  Hintergrundtools koennen dort separat unter `plugin_sources/background-tools/` liegen.
- `dist/`
  Gebaute ZIP-Artefakte.
- `plugins.xml`
  Die QGIS-Repository-Datei fuer die direkte Einbindung per URL.
- `trassify_master_tools.zip`
  Das Root-ZIP fuer das einfache GitHub-Repo-Schema `plugins.xml + plugin.zip`.

Wichtig:

- Wenn du nur ein Plugin in QGIS installieren willst, nutze das Bundle aus `trassify_master_tools/`.
- Die eingebetteten Modulkopien fuer das Bundle werden beim Build aus `plugin_sources/` erzeugt und liegen nicht mehr doppelt im Git-Repo.
- Die Originalquellen bleiben unter `plugin_sources/`, damit jede Plugin-Datei nur noch einmal im Repository gepflegt wird.
- Nicht mehr verwendete Tool-Kopien und alte Plugin-ZIPs werden aus `plugin_sources/` entfernt, damit der Source-Baum dem aktiven Bundle entspricht.
- In QGIS oeffnet das Master-Plugin ueber sein Toolbar-Icon eine Uebersicht aller enthaltenen Module.
- Das Master-Plugin unterscheidet jetzt zwischen normalen Tools und Hintergrundtools.
- Normale Tools koennen ueber die Master-Uebersicht geladen werden; als Favorit markierte Tools werden beim Start automatisch mitgeladen.
- Hintergrundtools werden beim Start automatisch aktiviert und sind fuer Kontextmenues oder unauffaellige Hilfsfunktionen gedacht.
- Fuer das GitHub-Setup kannst du `./prepare_plugin_repository.sh` ausfuehren. Das aktualisiert `plugins.xml` und `trassify_master_tools.zip`.
