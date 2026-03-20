#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PLUGIN_DIR="max_wild_project_starter"
SOURCE_DIR="${ROOT_DIR}/${PLUGIN_DIR}"
TARGET_ROOT="${QGIS_PLUGIN_DIR:-$HOME/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins}"
TARGET_DIR="${TARGET_ROOT}/${PLUGIN_DIR}"

if [[ ! -d "${SOURCE_DIR}" ]]; then
  echo "Fehler: Plugin-Ordner nicht gefunden: ${SOURCE_DIR}" >&2
  exit 1
fi

if [[ ! -f "${SOURCE_DIR}/metadata.txt" ]]; then
  echo "Fehler: metadata.txt fehlt in ${SOURCE_DIR}" >&2
  exit 1
fi

mkdir -p "${TARGET_DIR}"
rsync -a --delete "${SOURCE_DIR}/" "${TARGET_DIR}/"

echo "Projektstarter deployed:"
echo "  Quelle: ${SOURCE_DIR}"
echo "  Ziel:   ${TARGET_DIR}"
echo
echo "QGIS danach komplett neu starten oder Plugin deaktivieren/aktivieren."
