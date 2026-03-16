#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="trassify_master_tools"
METADATA_PATH="${ROOT_DIR}/${PLUGIN_DIR}/metadata.txt"
DIST_DIR="${ROOT_DIR}/dist"
ROOT_ZIP_NAME="${PLUGIN_DIR}.zip"
ROOT_ZIP_PATH="${ROOT_DIR}/${ROOT_ZIP_NAME}"
PLUGINS_XML_PATH="${ROOT_DIR}/plugins.xml"

metadata_value() {
  local key="$1"
  awk -F= -v key="$key" '$1 == key { sub(/^[[:space:]]+/, "", $2); print $2; exit }' "${METADATA_PATH}"
}

repo_slug() {
  local remote_url
  remote_url="$(git -C "${ROOT_DIR}" remote get-url origin)"

  remote_url="${remote_url%.git}"
  remote_url="${remote_url#https://github.com/}"
  remote_url="${remote_url#http://github.com/}"

  if [[ "${remote_url}" == git@github.com:* ]]; then
    remote_url="${remote_url#git@github.com:}"
  fi

  printf '%s\n' "${remote_url}"
}

plugin_name="$(metadata_value "name")"
plugin_version="$(metadata_value "version")"
plugin_description="$(metadata_value "description")"
plugin_about="$(metadata_value "about")"
plugin_author="$(metadata_value "author")"
plugin_homepage="$(metadata_value "homepage")"
plugin_tracker="$(metadata_value "tracker")"
plugin_repository="$(metadata_value "repository")"
plugin_tags="$(metadata_value "tags")"
plugin_min_qgis="$(metadata_value "qgisMinimumVersion")"
plugin_max_qgis="$(metadata_value "qgisMaximumVersion")"
plugin_experimental="$(metadata_value "experimental" | tr '[:upper:]' '[:lower:]')"
plugin_deprecated="$(metadata_value "deprecated" | tr '[:upper:]' '[:lower:]')"
repo_path="$(repo_slug)"
raw_base_url="https://raw.githubusercontent.com/${repo_path}/main"
download_url="${raw_base_url}/${ROOT_ZIP_NAME}"
icon_url="${raw_base_url}/${PLUGIN_DIR}/icon.svg"
today="$(date +%F)"

"${ROOT_DIR}/${PLUGIN_DIR}/build_zip.sh"

cp -f "${DIST_DIR}/${PLUGIN_DIR}-${plugin_version}.zip" "${ROOT_ZIP_PATH}"

cat > "${PLUGINS_XML_PATH}" <<EOF
<?xml version='1.0' encoding='UTF-8'?>
<plugins>
  <pyqgis_plugin name="${plugin_name}" version="${plugin_version}">
    <description><![CDATA[${plugin_description}]]></description>
    <about><![CDATA[${plugin_about}]]></about>
    <version>${plugin_version}</version>
    <qgis_minimum_version>${plugin_min_qgis}</qgis_minimum_version>
    <qgis_maximum_version>${plugin_max_qgis}</qgis_maximum_version>
    <homepage><![CDATA[${plugin_homepage}]]></homepage>
    <file_name>${ROOT_ZIP_NAME}</file_name>
    <icon><![CDATA[${icon_url}]]></icon>
    <author_name><![CDATA[${plugin_author}]]></author_name>
    <download_url><![CDATA[${download_url}]]></download_url>
    <uploaded_by><![CDATA[${plugin_author}]]></uploaded_by>
    <create_date>${today}</create_date>
    <update_date>${today}</update_date>
    <experimental>${plugin_experimental}</experimental>
    <deprecated>${plugin_deprecated}</deprecated>
    <tracker><![CDATA[${plugin_tracker}]]></tracker>
    <repository><![CDATA[${plugin_repository}]]></repository>
    <tags><![CDATA[${plugin_tags}]]></tags>
    <server>False</server>
  </pyqgis_plugin>
</plugins>
EOF

echo "Repository-Dateien aktualisiert:"
echo "- ${ROOT_ZIP_PATH}"
echo "- ${PLUGINS_XML_PATH}"
