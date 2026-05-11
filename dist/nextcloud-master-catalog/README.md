# Nextcloud Master Catalog

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
