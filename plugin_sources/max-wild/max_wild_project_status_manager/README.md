# Max Wild Projekt Status

Dieses Plugin liest alle Projektordner unter
`/Users/tomermaith/Documents/repo-webmap/max-wild/_projekte`
ein, sofern dort eine `status.json` liegt.

Funktionen:

- Startet auf dem Tab `Aktive Projekte` und blendet dort alle `Fertig`-Projekte aus
- Zeigt auf dem Tab `Alle` die komplette Projektliste
- Bearbeitet `statusUrl`, `status`, `downloadToken` und `baubeginn`
- `status` wird ueber farbige Dropdowns gepflegt
- `baubeginn` kann per Kalender oder als Text im Format `dd.MM.yyyy` gesetzt werden
- Ein Nextcloud-Button pro Zeile erzeugt einen oeffentlichen Ordner-Link und uebernimmt den `downloadToken`
- ClickUp-Tasks koennen pro Projekt verknuepft werden; Status lassen sich aus ClickUp laden und beim Speichern zurueckschreiben
- Fehlende ClickUp-Verknuepfungen werden automatisch ueber einen eindeutigen gleichen Projektnamen erkannt
- Speichert Aenderungen direkt in die jeweilige `status.json`
