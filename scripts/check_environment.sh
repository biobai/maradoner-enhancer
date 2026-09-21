#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/common.sh"
cd "$PROJECT_ROOT"
exec "$CORE_PY" -m me.cli check --config config/project.yaml "$@"

