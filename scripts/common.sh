#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="${ME_PROJECT_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)}"
SOFTWARE_ROOT="${ME_SOFTWARE_ROOT:-$PROJECT_ROOT}"
export MAMBA_ROOT_PREFIX="$SOFTWARE_ROOT/.runtime"
export CONDA_PKGS_DIRS="$PROJECT_ROOT/tmp/conda-cache"
export CONDARC="$SOFTWARE_ROOT/.runtime/condarc"
export PYTHONNOUSERSITE=1
export JAX_PLATFORMS=cpu
export MPLBACKEND=Agg
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}"
export TMPDIR="$PROJECT_ROOT/tmp"
mkdir -p "$TMPDIR"
CORE_PY="$SOFTWARE_ROOT/.runtime/envs/core/bin/python"
