#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_DIR="trassify_master_tools"
DIST_DIR="${ROOT_DIR}/dist"
BUILD_ROOT="${DIST_DIR}/.build"
STAGING_PLUGIN_DIR="${BUILD_ROOT}/${PLUGIN_DIR}"
CATALOG_BUILDER="${ROOT_DIR}/tools/build_master_catalog.py"

if [[ ! -d "${ROOT_DIR}/${PLUGIN_DIR}" ]]; then
  echo "Plugin-Ordner ${PLUGIN_DIR} nicht gefunden." >&2
  exit 1
fi

if [[ ! -f "${CATALOG_BUILDER}" ]]; then
  echo "Katalog-Skript ${CATALOG_BUILDER} nicht gefunden." >&2
  exit 1
fi

VERSION="$(awk -F= '/^version=/{print $2}' "${ROOT_DIR}/${PLUGIN_DIR}/metadata.txt" | tr -d '[:space:]')"
if [[ -z "${VERSION}" ]]; then
  VERSION="dev"
fi

mkdir -p "${DIST_DIR}"
ZIP_PATH="${DIST_DIR}/${PLUGIN_DIR}-${VERSION}.zip"
rm -f "${ZIP_PATH}"
rm -rf "${BUILD_ROOT}"
mkdir -p "${STAGING_PLUGIN_DIR}"

trap 'rm -rf "${BUILD_ROOT}"' EXIT

rsync -a \
  --exclude "catalog" \
  --exclude "__pycache__" \
  --exclude "*.pyc" \
  --exclude "*.pyo" \
  --exclude ".DS_Store" \
  "${ROOT_DIR}/${PLUGIN_DIR}/" "${STAGING_PLUGIN_DIR}/"

python3 "${CATALOG_BUILDER}" \
  --root-dir "${ROOT_DIR}" \
  --output-dir "${STAGING_PLUGIN_DIR}/catalog"

(
  cd "${BUILD_ROOT}"
  zip -r "${ZIP_PATH}" "${PLUGIN_DIR}" \
    -x "*/__pycache__/*" "*.pyc" "*.pyo" "*.DS_Store" "*.zip" "*/dist/*" "*/dist/"
)

echo "ZIP erstellt: ${ZIP_PATH}"
