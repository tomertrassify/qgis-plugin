# Plugin Sources

Dieser Ordner enthaelt die Einzelquellen der urspruenglichen Plugins.

Wichtig:

- `plugin_sources/` ist nur die Quellablage und kein direkt installierbares QGIS-Plugin.
- Das installierbare Master-Plugin liegt unter `trassify_master_tools/`.
- Aus `plugin_sources/` werden die separaten Plugin-ZIPs und der Katalog-Snapshot fuer das Master-Plugin erzeugt. Hier liegt die einzige gepflegte Plugin-Kopie im Repo.
- Hintergrundtools koennen unter `plugin_sources/background-tools/` separat abgelegt werden.
- Nicht mehr verwendete Tool-Kopien und alte ZIP-Artefakte werden aus diesem Ordner entfernt, damit nur noch die aktiv gepflegten Quellen uebrig bleiben.
- Die Ausnahme ist `max-wild/funktionen-temp/quick_map_services/`: dieser Pfad ist trotz Namen weiterhin die aktive Quelle fuer das Repository.
