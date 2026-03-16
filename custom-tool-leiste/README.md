# Custom Tool Leiste (QGIS Plugin)

Dieses Plugin organisiert vorhandene QGIS-Werkzeugleisten in einem eigenen Side-Panel.

## Funktionen
- Kategorien fuer Werkzeuge direkt in der Gesamtuebersicht pflegen.
- Favoriten markieren und als schnellen Block anzeigen.
- Vollstaendige Werkzeug-Uebersicht standardmaessig versteckt ein-/ausblenden.
- Logo oben rechts im Panel fuer ein gebrandetes "Custom QGIS"-Gefuehl.

## Logo austauschen
Ersetze die Datei `logo.svg` im Plugin-Ordner durch euer eigenes Logo (gleicher Dateiname empfohlen).

## Installation (lokal)
1. Plugin-Ordner in das QGIS Plugin-Verzeichnis kopieren.
2. QGIS neu starten.
3. Plugin in `Erweiterungen -> Erweiterungen verwalten und installieren...` aktivieren.
4. Das Panel ueber `Custom Tool-Leiste oeffnen/schliessen` anzeigen.

## ZIP bauen (fuer Plugin-Installation)
1. Im Plugin-Ordner ausfuehren: `./build_zip.sh`
2. Die fertige ZIP liegt dann hier: `dist/custom_tool_leiste.zip`
