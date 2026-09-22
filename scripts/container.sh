#!/usr/bin/env bash
# Run on the host. Do not source common.sh: its runtime is selected inside the container.
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$PROJECT_ROOT/container/image.env"
action="${1:-help}"
if [[ $# -gt 0 ]]; then shift; fi
if [[ "$action" == help || "$action" == --help ]]; then
  echo 'Usage: bash scripts/container.sh {convert|check|smoke|run|exec} [arguments]'
  echo 'Examples: container.sh smoke --with-sce2g; container.sh run --config config/project.yaml --cores 8'
  exit 0
fi
if [[ "$action" == pull || "$action" == bootstrap ]]; then
  echo 'Runtime installation and direct registry pulls are disabled. All software is installed by scripts/build_podman.sh before SIF conversion.' >&2
  exit 2
fi
case "$action" in convert|check|smoke|run|exec) ;; *) echo "Unknown action: $action" >&2; exit 2;; esac
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
mkdir -p "$state/images" "$state/cache" "$state/tmp" "$state/home"
export APPTAINER_CACHEDIR="$state/cache"
export SINGULARITY_CACHEDIR="$state/cache"
export APPTAINER_TMPDIR="$state/tmp"
export SINGULARITY_TMPDIR="$state/tmp"
sif="$state/images/maradoner-enhancer-software.sif"
if [[ "$action" == convert ]]; then
  archive="$state/images/maradoner-enhancer-software.tar"
  [[ -f "$archive" && -f "$archive.sha256" ]] || { echo 'Missing Podman image archive/checksum. Run build_podman.sh on the build machine and transfer .container/images.' >&2; exit 1; }
  (cd -- "$state/images" && sha256sum -c maradoner-enhancer-software.tar.sha256)
  archive_hash=$(sha256sum "$archive" | awk '{print $1}')
  if [[ -f "$sif" ]]; then
    [[ -f "$sif.source-sha256" && "$(cat "$sif.source-sha256")" == "$archive_hash" ]] || { echo 'Existing SIF comes from another archive. Preserve/move that SIF and its receipts before converting the new build.' >&2; exit 1; }
  fi
  pull_locked=0
  if [[ ! -f "$sif" ]]; then
    mkdir "$state/pull.lock" 2>/dev/null || { echo "Pull lock exists: $state/pull.lock; check for another active pull." >&2; exit 1; }
    pull_locked=1
    trap 'rmdir -- "$state/pull.lock"' EXIT
    # A unique output avoids mistaking an interrupted partial pull for a valid image.
    temporary="$state/images/pull.$$.sif"
    "$engine" build "$temporary" "docker-archive:$archive"
    mv -- "$temporary" "$sif"
    printf '%s\n' "$archive_hash" > "$sif.source-sha256"
  fi
  if [[ ! -f "$sif.sha256" ]]; then
    (cd -- "$state/images" && sha256sum maradoner-enhancer-software.sif > maradoner-enhancer-software.sif.sha256)
  fi
  "$engine" --version > "$state/engine_version.txt"
  if [[ "$pull_locked" == 1 ]]; then
    rmdir -- "$state/pull.lock"
    trap - EXIT
  fi
  action=check
fi
[[ -f "$sif" && -f "$sif.sha256" && -f "$sif.source-sha256" ]] || { echo 'Container image or provenance is missing. Run: bash scripts/container.sh convert' >&2; exit 1; }
(cd -- "$state/images" && sha256sum -c maradoner-enhancer-software.sif.sha256)
image_hash=$(awk '{print $1}' "$sif.sha256")
# Bind the project at its physical host path, preserving absolute paths in Conda scripts.
# All software comes from the image at /opt/maradoner-enhancer; no host environment is mounted.
options=(exec --cleanenv --contain --home "$state/home:/home/me"
         --bind "$PROJECT_ROOT:$PROJECT_ROOT"
         --pwd "$PROJECT_ROOT")
if [[ -n "${ME_CONTAINER_BIND:-}" ]]; then options+=(--bind "$ME_CONTAINER_BIND"); fi
environment=(env "ME_PROJECT_ROOT=$PROJECT_ROOT" "ME_SOFTWARE_ROOT=/opt/maradoner-enhancer" "ME_PREBUILT_CONDA=/opt/me-stage-envs" "ME_CONTAINER_IMAGE_SHA256=$image_hash" "PYTHONNOUSERSITE=1" "JAX_PLATFORMS=cpu" "MPLBACKEND=Agg" "PIP_NO_INDEX=1" "CONDA_OFFLINE=true")
case "$action" in
  check)
    command=(/opt/maradoner-enhancer/.runtime/envs/core/bin/python /opt/maradoner-enhancer/container/check_image.py) ;;
  smoke) command=(bash /opt/maradoner-enhancer/scripts/run_smoke_test.sh "$@") ;;
  run) command=(bash /opt/maradoner-enhancer/scripts/run_pipeline.sh "$@") ;;
  exec)
    [[ $# -gt 0 ]] || { echo 'exec requires a command' >&2; exit 2; }
    command=("$@") ;;
esac
exec "$engine" "${options[@]}" "$sif" "${environment[@]}" "${command[@]}"
