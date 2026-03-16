# AttributionButler (QGIS Plugin)

Dieses Plugin bindet eine `form_open`-Funktion an einen Vektor-Layer, damit bei Aenderung eines Pfadfelds automatisch Nextcloud-Sharelinks und Metadaten geschrieben werden.

## Installation

1. Plugin-Ordner nach QGIS kopieren:
   - macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/nextcloud_form_plugin`
2. QGIS neu starten.
3. Plugin in `Plugins > Manage and Install Plugins...` aktivieren.

## Nutzung

1. Gewuenschten Vektor-Layer aktivieren.
2. Menu `AttributionButler > Layer mit AttributionButler verbinden`.
3. Dialog ausfuellen (URL, User, App-Passwort, Feldnamen).
4. Plugin setzt die Layer-Form-Initfunktion automatisch auf `form_open`.

Danach reicht normale Formularnutzung: Sobald das konfigurierte Pfadfeld geaendert wird, werden die Ziel-Felder aktualisiert.

## Hinweise

- Nextcloud-Zugangsdaten, URL und lokale Sync-Roots werden pro Benutzer im QGIS-Profil gespeichert (lokal pro Rechner/OS).
- Feld-Mapping, Betreiberliste und Data-Quellen bleiben als Layer-Custom-Properties im QGIS-Projekt.
- Der Dialog hat links eine QGIS-aehnliche Seitennavigation mit `Betreiberliste`, `Data` und `Konfiguration` und startet direkt auf `Betreiberliste`.
- In `Konfiguration` kannst du Betreiber-Felder mappen (z. B. `Betreiber`, `betr_anspr`, `betr_tel`, `betr_email`, `Stör-Nr.`).
- In `Betreiberliste` kannst du eine kleine Tabelle pflegen: Betreibername, Ansprechpartner, Telefonnummer, E-Mail, Stoernummer, Ordnerpfad.
- In `Betreiberliste` gibt es `Aus Data uebernehmen...`, um Betreiber aus verbundenen Data-Quellen in die projektspezifische Liste zu kopieren.
- In `Data` sind Dateiquellen und DB/URI-Quellen getrennt dargestellt.
- Pro Bereich gibt es einen Button `Verbindung herstellen...`, der nur die passenden Felder fuer diesen Quelltyp abfragt.
- Bei Dateiquellen wird `Name` automatisch aus dem Dateinamen gesetzt.
- `Spalte Ordnerpfad` wird in den Data-Verbindungsdialogen nicht abgefragt.
- Die Spaltennamen im Data-Dialog sind standardmaessig mit den Werten aus dem Betreiber-Feld-Mapping vorbelegt.
- Beim Verbindungsdialog wird die Betreiber-Spalte direkt gegen die Quelle validiert; ausserdem ist das Spalten-Matching tolerant (z. B. bei gekuerzten/abweichenden Excel-Spaltennamen).
- Wenn eine Excel-Quelle nur mit `Field1..FieldN` erkannt wird, nutzt das Plugin automatisch die erste Datenzeile als Header-Mapping.
- In `Data` kannst du externe Datenquellen hinterlegen, z. B. Excel/CSV-Dateien oder QGIS-URI-Quellen (SQL/DB), inklusive Spalten-Mapping.
- Fuer jede Quelle gibt es `Daten anzeigen...` zur direkten Vorschau der geladenen Zeilen (bis zu 1000).
- In der Betreiberliste gibt es `Upload` (Import) und `Download` (Export) fuer CSV/JSON.
- Pro Betreiber kann ein Ordnerpfad hinterlegt werden (Button `Ordner...` direkt in der jeweiligen Tabellenzeile). Daraus wird der allgemeine Ordner-Sharelink erzeugt.
- Die Betreiberliste nutzt breite, manuell anpassbare Spalten; bei wenig Platz erscheint horizontales Scrollen statt abgeschnittener Ueberschriften.
- Wenn im Formular ein Betreibername eingetragen wird und dieser in der Liste genau einmal vorkommt, werden die restlichen Betreiber-Felder sowie der Ordner-Link automatisch gefuellt.
- Wenn kein eindeutiger Betreiber gefunden wird, werden die automatisch gepflegten Betreiber-Zielfelder auf `NULL` gesetzt.
- Beim Betreiber-Lookup werden Telefon/E-Mail/etc. aus dem Treffer immer aktualisiert, damit keine alten Werte stehen bleiben.
- Im Betreiber-Feld werden beim Tippen Vorschlaege aus Betreiberliste, externen `Data`-Quellen und vorhandenen Layer-Werten zusammen angezeigt.
- Beim direkten Verlinken eines Plans ueber das Pfadfeld wird der Datei-Link gesetzt, der bestehende Ordner-Link aber nicht ueberschrieben.
- Optionale Zielfelder koennen leer gelassen werden; sie werden dann ignoriert.
- Das Trennen ist bewusst versteckt und per Shortcut verfuegbar: `Ctrl+Alt+Shift+U`.
