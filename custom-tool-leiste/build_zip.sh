#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR_NAME="custom_tool_leiste"
DIST_DIR="$SCRIPT_DIR/dist"
STAGE_DIR="$DIST_DIR/.stage"
ZIP_PATH="$DIST_DIR/${PLUGIN_DIR_NAME}.zip"

mkdir -p "$DIST_DIR"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR/$PLUGIN_DIR_NAME"

FILES=(
  "__init__.py"
  "custom_toolbar_manager.py"
  "toolbar_manager_dock.py"
  "metadata.txt"
  "icon.svg"
  "logo.svg"
  "README.md"
)

for file in "${FILES[@]}"; do
  cp "$SCRIPT_DIR/$file" "$STAGE_DIR/$PLUGIN_DIR_NAME/"
done

rm -f "$ZIP_PATH"
(
  cd "$STAGE_DIR"
  zip -qr "$ZIP_PATH" "$PLUGIN_DIR_NAME"
)

rm -rf "$STAGE_DIR"
echo "ZIP erstellt: $ZIP_PATH"
