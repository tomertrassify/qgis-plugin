# Map Search Pro (QGIS Plugin)

Finder-style quick search overlay for QGIS with OSM/Nominatim suggestions.

## Features

- `Ctrl+F` (Windows/Linux) or `Cmd+F` (macOS) opens a quick-search overlay.
- Live suggestions while typing.
- Searches places and POIs (for example: school, cafe, museum).
- Press `Enter` or click a suggestion to zoom to the result.
- Uses map extent as ranking hint for nearby suggestions.

## Install

1. In QGIS: `Plugins` -> `Manage and Install Plugins` -> `Install from ZIP`.
2. Choose the generated ZIP file (`map_search_pro.zip`).

## Usage

1. Press `Ctrl+F` / `Cmd+F`.
2. Type at least 2 characters.
3. Use `Up/Down` and `Enter` to jump to a result.

## Notes

- Search backend: OpenStreetMap Nominatim.
- Internet connection is required.
