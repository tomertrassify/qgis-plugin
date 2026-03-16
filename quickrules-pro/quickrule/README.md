# Quickrule

QGIS plugin that adds a `Quickrule` entry to the layer right-click menu.

## Features

1. Right-click a vector layer in the layer list.
2. Click `Quickrule`.
3. In the overlay dialog:
   - choose a preset (`Betreiber`, `Sparte`) or manual field selection
   - choose mode (`Regelbasierung`, `Layer-Filter`, `Regeln + Layer-Filter`)
   - select which unique values are included
4. Apply:
   - one rule per selected value in a different color
   - optional layer filter with automatic save + exit edit mode

## Preset aliases via config

The plugin reads aliases from:

- `quickrule/quickrule_config.json`

You can add/update presets and alias lists so the plugin maps to your column names.

Example:

```json
{
  "presets": {
    "betreiber": {
      "label": "Preset: Betreiber",
      "aliases": ["betreiber", "netzbetreiber", "operator"]
    },
    "sparte": {
      "label": "Preset: Sparte",
      "aliases": ["sparte", "segment", "category"]
    }
  }
}
```

## Install from ZIP

1. Build ZIP with `./build_zip.sh`
2. In QGIS: Plugins -> Manage and Install Plugins -> Install from ZIP
3. Select `quickrule.zip`
