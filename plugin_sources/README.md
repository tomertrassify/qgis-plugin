# Plugin Sources

Dieser Ordner enthaelt die Einzelquellen der urspruenglichen Plugins.

Wichtig:

- `plugin_sources/` ist nur die Quellablage und kein direkt installierbares QGIS-Plugin.
- Das installierbare Bundle liegt unter `trassify_master_tools/`.
- Aus `plugin_sources/` wird das Master-Bundle beim Build zusammengesetzt. Hier liegt die einzige gepflegte Plugin-Kopie im Repo.
- Hintergrundtools koennen unter `plugin_sources/background-tools/` separat abgelegt werden.
- Historische oder temporaere Varianten bleiben hier bewusst als Quelle erhalten, werden aber nicht automatisch in das Master-Plugin geladen.
