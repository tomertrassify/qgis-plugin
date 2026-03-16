#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_ZIP="$SCRIPT_DIR/layer_fuser.zip"

rm -f "$OUTPUT_ZIP"
/usr/bin/zip -qr "$OUTPUT_ZIP" layer_fuser

printf 'ZIP erstellt: %s\n' "$OUTPUT_ZIP"
