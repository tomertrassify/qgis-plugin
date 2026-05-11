#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="${ROOT_DIR}/quickrule"
OUTPUT_ZIP="${1:-${ROOT_DIR}/quickrule.zip}"

if [[ ! -d "${PLUGIN_DIR}" ]]; then
  echo "Plugin directory not found: ${PLUGIN_DIR}" >&2
  exit 1
fi

rm -f "${OUTPUT_ZIP}"
(
  cd "${ROOT_DIR}"
  zip -r "${OUTPUT_ZIP}" "quickrule" \
    -x "*/__pycache__/*" "*.pyc" "*.DS_Store" >/dev/null
)

echo "ZIP created: ${OUTPUT_ZIP}"
