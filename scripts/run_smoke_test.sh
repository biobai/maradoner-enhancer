#!/usr/bin/env bash
# Server acceptance only; no local unit-test suite is included in this distribution.
set -euo pipefail
source "$(dirname -- "$0")/common.sh"
cd "$PROJECT_ROOT"
# Accept the older documented spelling while keeping server-only behavior.
if [[ "${1:-}" == --real-tools ]]; then shift; fi
exec "$CORE_PY" "$SOFTWARE_ROOT/scripts/real_tool_smoke.py" "$@"
