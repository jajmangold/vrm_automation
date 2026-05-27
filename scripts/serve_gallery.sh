#!/bin/sh
set -eu

PORT="${PORT:-8765}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "${WEBAPP_ROOT:-$SCRIPT_DIR}"

echo "Serving Person Factory webapp on port ${PORT}"
exec python3 scripts/person_factory_webapp.py
