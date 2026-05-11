#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="verpacken_pro"
DIST_DIR="${ROOT_DIR}/dist"

if [[ ! -d "${ROOT_DIR}/${PLUGIN_DIR}" ]]; then
  echo "Plugin-Ordner ${PLUGIN_DIR} nicht gefunden." >&2
  exit 1
fi

VERSION="$(awk -F= '/^version=/{print $2}' "${ROOT_DIR}/${PLUGIN_DIR}/metadata.txt" | tr -d '[:space:]')"
if [[ -z "${VERSION}" ]]; then
  VERSION="dev"
fi

mkdir -p "${DIST_DIR}"
ZIP_PATH="${DIST_DIR}/${PLUGIN_DIR}-${VERSION}.zip"
rm -f "${ZIP_PATH}"

(
  cd "${ROOT_DIR}"
  zip -r "${ZIP_PATH}" "${PLUGIN_DIR}" \
    -x "*/__pycache__/*" "*.pyc" "*.pyo" "*.DS_Store"
)

echo "ZIP erstellt: ${ZIP_PATH}"
