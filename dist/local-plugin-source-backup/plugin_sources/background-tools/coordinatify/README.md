# Coordinatify (QGIS Plugin)

Dieses Plugin erweitert das Rechtsklick-Menü der QGIS-Karte um:

- In Google Maps öffnen (eingebettet im QGIS-Fenster)
- In Street View öffnen (eingebettet im QGIS-Fenster)
- Adresse kopieren
- Bundesland: <Name> (nur Anzeige)
- Flurstücke und Gebäude (lädt dynamisch aus GeoBasis_Loader für das erkannte Bundesland)
- Satellitenbild (lädt dynamisch aus GeoBasis_Loader für das erkannte Bundesland)
- OSM Standard (lädt bevorzugt über QuickMapServices, sonst direkt als XYZ-Layer)

Die Position basiert auf dem Rechtsklick-Punkt und wird intern nach WGS84 (EPSG:4326) transformiert.

Hinweis: Falls `QtWebEngine` in der QGIS-Installation nicht verfügbar ist, wird automatisch der externe Browser verwendet.

Hinweis: Für die beiden GeoBasis-Aktionen muss das Plugin `GeoBasis_Loader` aktiviert sein und ein Katalog geladen sein.

Hinweis: Für `OSM Standard` nutzt Coordinatify nach Möglichkeit die QuickMapServices-Datasource `osm_mapnik`, damit dieselbe URL-, Attribution- und Einfüge-Logik verwendet wird. Falls QuickMapServices nicht verfügbar ist, wird automatisch ein direkter OSM-XYZ-Layer geladen.

Konfiguration:
- Datei: `coordinatify/geobasis_actions.conf.json`
- Enthält pro Katalog und Bundesland die Pfad-Auswahl für `Flurstücke und Gebäude` und `Satellitenbild`
- Reihenfolge: zuerst `options` in der angegebenen Reihenfolge, danach `preferred_path` als Fallback
- Für `parcel_building` wird standardmäßig Typ `ogc_wfs` vor `ogc_wms` bevorzugt (optional per `prefer_types` steuerbar)
- Wenn bei `parcel_building` getrennte Einträge für Flurstücke und Gebäude vorhanden sind, werden beide geladen und in die Gruppe `ALKIS (Gebäude & Flurstücke)` einsortiert
- Bei diesem Multi-Load wird das Koordinatensystem nur einmal abgefragt und für beide Ladevorgänge wiederverwendet
- In die Gruppe `ALKIS (Gebäude & Flurstücke)` werden nur die neu geladenen Elemente verschoben; bestehende Layer bleiben unverändert
- Existiert kein passender Eintrag, nutzt das Plugin automatisch den dynamischen Fallback
