# QGIS Plugins Repository

Repository-Struktur:

- `trassify_master_tools/`
  Das installierbare Master-Plugin. Diese Struktur steht bewusst direkt auf Repo-Ebene im Vordergrund.
- `modules/`
  Die Einzelplugin-Quellen und Modulvorlagen, aus denen das Bundle zusammengesetzt wurde.
- `dist/`
  Gebaute ZIP-Artefakte.

Wichtig:

- Wenn du nur ein Plugin in QGIS installieren willst, nutze das Bundle aus `trassify_master_tools/`.
- Die eingebetteten Modulkopien fuer das Bundle liegen in `trassify_master_tools/modules/`.
- Die Originalquellen bleiben separat unter `modules/`, damit sie weiter einzeln gepflegt werden koennen.
