#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 "${ROOT_DIR}/tools/build_plugin_repository.py" \
  --root-dir "${ROOT_DIR}"

echo "Repository-Dateien aktualisiert:"
echo "- ${ROOT_DIR}/plugins.xml"
echo "- ${ROOT_DIR}/trassify_master_tools.zip"
echo "- ${ROOT_DIR}/*.zip (Einzelplugins)"
