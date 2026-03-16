#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="FreehandGeoreferencer"
ZIP_PATH="${ROOT_DIR}/${PLUGIN_DIR}.zip"

if [[ ! -d "${ROOT_DIR}/${PLUGIN_DIR}" ]]; then
  echo "Plugin directory not found: ${ROOT_DIR}/${PLUGIN_DIR}" >&2
  exit 1
fi

cd "${ROOT_DIR}"
rm -f "${ZIP_PATH}"
zip -r "${ZIP_PATH}" "${PLUGIN_DIR}" \
  -x "${PLUGIN_DIR}/__pycache__/*" \
  -x "${PLUGIN_DIR}/*.pyc" \
  -x "${PLUGIN_DIR}/.DS_Store"

echo "Created: ${ZIP_PATH}"
