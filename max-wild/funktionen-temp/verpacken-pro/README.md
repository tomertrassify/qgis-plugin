# Verpacken Pro (QGIS Plugin)

Rechtsklick in der Layerliste auf einen oder mehrere ausgewaehlte Layer und dann **"Verpacken in GeoPackage..."**.

Das Plugin verwendet den QGIS-Algorithmus `native:package` und speichert dabei (wenn von deiner QGIS-Version unterstuetzt):
- Layer in ein GeoPackage
- Layer-Stile im GeoPackage
- Layer-Metadaten im GeoPackage

## Build ZIP

```bash
./build_zip.sh
```

Das ZIP liegt danach in `dist/` und kann in QGIS ueber den Plugin-Manager installiert werden.
