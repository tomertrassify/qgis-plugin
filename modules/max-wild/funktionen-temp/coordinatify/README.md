# Coordinatify (QGIS Plugin)

Dieses Plugin erweitert das Rechtsklick-Menü der QGIS-Karte um:

- In Google Maps öffnen (eingebettet im QGIS-Fenster)
- In Street View öffnen (eingebettet im QGIS-Fenster)
- Adresse kopieren
- Bundesland: <Name> (nur Anzeige)

Die Position basiert auf dem Rechtsklick-Punkt und wird intern nach WGS84 (EPSG:4326) transformiert.

Hinweis: Falls `QtWebEngine` in der QGIS-Installation nicht verfügbar ist, wird automatisch der externe Browser verwendet.
