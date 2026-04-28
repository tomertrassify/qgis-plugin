# Projektstatus Butler

Dieses Plugin liest alle Projektordner unter
`/Users/tomermaith/Documents/repo-webmap/max-wild/_projekte`
ein, sofern dort eine `status.json` liegt.

Funktionen:

- Listet jeden Projektordner in einer Tabelle auf
- Bearbeitet `statusUrl`, `status`, `downloadToken` und `baubeginn`
- `status` wird ueber ein Dropdown gepflegt
- `baubeginn` kann per Kalender oder als Text im Format `dd.MM.yyyy` gesetzt werden
- Speichert Aenderungen direkt in die jeweilige `status.json`
