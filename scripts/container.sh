#!/usr/bin/env bash
# Run on the host. Do not source common.sh: its runtime is selected inside the container.
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$PROJECT_ROOT/container/image.env"
action="${1:-help}"
if [[ $# -gt 0 ]]; then shift; fi
if [[ "$action" == help || "$action" == --help ]]; then
  echo 'Usage: bash scripts/container.sh {pull|check|bootstrap|smoke|run|exec} [arguments]'
  echo 'Examples: container.sh smoke --with-sce2g; container.sh run --config config/project.yaml --cores 8'
  exit 0
fi
case "$action" in pull|check|bootstrap|smoke|run|exec) ;; *) echo "Unknown action: $action" >&2; exit 2;; esac
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || { echo 'Container execution requires a Linux x86_64 host.' >&2; exit 1; }
if command -v apptainer >/dev/null 2>&1; then
  engine=$(command -v apptainer)
elif command -v singularity >/dev/null 2>&1; then
  engine=$(command -v singularity)
else
  echo 'No Apptainer/Singularity found. Load the cluster container module first (module avail), or request a supported runtime from the administrator.' >&2
  exit 1
fi
case "$PROJECT_ROOT" in *:*|*,*) echo 'Project paths containing colon or comma cannot be used as bind paths.' >&2; exit 1;; esac
state="$PROJECT_ROOT/.container"
mkdir -p "$state/images" "$state/cache" "$state/tmp" "$state/home" "$state/runtime" "$PROJECT_ROOT/.runtime"
export APPTAINER_CACHEDIR="$state/cache"
export SINGULARITY_CACHEDIR="$state/cache"
export APPTAINER_TMPDIR="$state/tmp"
export SINGULARITY_TMPDIR="$state/tmp"
sif="$state/images/python311-bookworm.sif"
if [[ "$action" == pull ]]; then
  pull_locked=0
  if [[ ! -f "$sif" ]]; then
    mkdir "$state/pull.lock" 2>/dev/null || { echo "Pull lock exists: $state/pull.lock; check for another active pull." >&2; exit 1; }
    pull_locked=1
    trap 'rmdir -- "$state/pull.lock"' EXIT
    # A unique output avoids mistaking an interrupted partial pull for a valid image.
    temporary="$state/images/pull.$$.sif"
    "$engine" pull "$temporary" "$ME_IMAGE_URI"
    mv -- "$temporary" "$sif"
  fi
  if [[ ! -f "$sif.sha256" ]]; then
    (cd -- "$state/images" && sha256sum python311-bookworm.sif > python311-bookworm.sif.sha256)
    printf '%s\n' "$ME_IMAGE_URI" > "$state/images/source_uri.txt"
  fi
  "$engine" --version > "$state/engine_version.txt"
  if [[ "$pull_locked" == 1 ]]; then
    rmdir -- "$state/pull.lock"
    trap - EXIT
  fi
  action=check
fi
[[ -f "$sif" && -f "$sif.sha256" ]] || { echo 'Container image or checksum is missing. Run: bash scripts/container.sh pull' >&2; exit 1; }
(cd -- "$state/images" && sha256sum -c python311-bookworm.sif.sha256)
# Bind the project at its physical host path, preserving absolute paths in Conda scripts.
# The nested mount hides the host .runtime and selects an independent container runtime.
options=(exec --cleanenv --contain --home "$state/home:/home/me"
         --bind "$PROJECT_ROOT:$PROJECT_ROOT"
         --bind "$state/runtime:$PROJECT_ROOT/.runtime"
         --pwd "$PROJECT_ROOT")
if [[ -n "${ME_CONTAINER_BIND:-}" ]]; then options+=(--bind "$ME_CONTAINER_BIND"); fi
environment=(env "PYTHONNOUSERSITE=1" "JAX_PLATFORMS=cpu" "MPLBACKEND=Agg")
if [[ -n "${ME_PIP_INDEX_URL:-}" ]]; then environment+=("PIP_INDEX_URL=$ME_PIP_INDEX_URL"); fi
case "$action" in
  check)
    command=(bash -c 'set -e; echo "Container OS:"; cat /etc/os-release; getconf GNU_LIBC_VERSION; for tool in bash curl tar git; do command -v "$tool"; done; git --version; python3 --version; test -w .runtime; echo "Container startup and project write access: OK"') ;;
  bootstrap) command=(bash scripts/bootstrap.sh "$@") ;;
  smoke) command=(bash scripts/run_smoke_test.sh "$@") ;;
  run) command=(bash scripts/run_pipeline.sh "$@") ;;
  exec)
    [[ $# -gt 0 ]] || { echo 'exec requires a command' >&2; exit 2; }
    command=("$@") ;;
esac
exec "$engine" "${options[@]}" "$sif" "${environment[@]}" "${command[@]}"
