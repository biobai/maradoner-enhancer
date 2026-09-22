#!/usr/bin/env bash
set -euo pipefail
echo 'Runtime bootstrap is disabled. Build all software with: bash scripts/build_podman.sh' >&2
echo 'Then convert the exported archive with container.sh convert and run container.sh check/smoke/run.' >&2
exit 2
