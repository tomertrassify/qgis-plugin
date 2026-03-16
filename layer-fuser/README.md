# Layer Fuser

QGIS-Plugin zum Uebernehmen von Geometrien und Attributen aus einer Shapefile oder einem GeoPackage-Layer in einen vorhandenen Ziellayer.

## Funktionen

- Kontextmenue-Eintrag `Layer Fuser` fuer Vektorlayer in der Layerliste
- Auswahl einer Shapefile oder eines GeoPackages
- Bei GeoPackage-Auswahl: Auswahl des Feature-Layers innerhalb der Datei
- Vergleich gleicher und abweichender Attributfelder
- Manuelle Feldzuordnung oder Ignorieren einzelner Quellfelder
- Uebernahme der Quell-Features in den rechtsgeklickten Ziellayer

## ZIP bauen

```bash
./build_zip.sh
```

Danach liegt die installierbare Datei unter `layer_fuser.zip`.
