# Projektstatus Butler

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
- Speichert Aenderungen direkt in die jeweilige `status.json`
