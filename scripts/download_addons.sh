#!/bin/sh
set -eu

mkdir -p addons

download() {
  url="$1"
  dest="$2"
  if [ -s "$dest" ]; then
    echo "exists $dest"
    return 0
  fi
  echo "download $url -> $dest"
  curl -fL "$url" -o "$dest"
}

download "${VRM_ADDON_URL}" "addons/vrm-addon.zip"
download "${MMD_TOOLS_URL}" "addons/mmd-tools.zip"
if [ "${INSTALL_MATERIAL_COMBINER:-0}" = "1" ]; then
  download "${MATERIAL_COMBINER_URL}" "addons/material-combiner.zip"
else
  echo "skip Material Combiner download (set INSTALL_MATERIAL_COMBINER=1 to enable)"
fi

ls -lh addons
