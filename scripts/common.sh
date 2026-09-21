#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export MAMBA_ROOT_PREFIX="$PROJECT_ROOT/.runtime"
export CONDA_PKGS_DIRS="$PROJECT_ROOT/.runtime/pkgs"
export CONDARC="$PROJECT_ROOT/.runtime/condarc"
export PYTHONNOUSERSITE=1
export JAX_PLATFORMS=cpu
export MPLBACKEND=Agg
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}"
export TMPDIR="$PROJECT_ROOT/tmp"
mkdir -p "$TMPDIR"
CORE_PY="$PROJECT_ROOT/.runtime/envs/core/bin/python"

