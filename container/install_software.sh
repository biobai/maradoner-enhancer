#!/usr/bin/env bash
# Build-time only. Never called by a runtime entry point.
set -euo pipefail
installed=/opt/maradoner-enhancer
export MAMBA_ROOT_PREFIX="$installed/.runtime"
export CONDA_PKGS_DIRS="$installed/.runtime/pkgs"
export CONDARC="$installed/.runtime/condarc"
export PATH="$installed/.runtime/envs/sce2g/bin:$installed/.runtime/envs/core/bin:$PATH"
mkdir -p "$installed/.runtime/bin" "$installed/.tools" "$installed/build-evidence"
case "${1:?Expected environments, sources, or stages}" in
environments)
  printf 'channels:\n  - conda-forge\n  - bioconda\nchannel_priority: flexible\n' > "$CONDARC"
  curl --fail --location --retry 3 https://micro.mamba.pm/api/micromamba/linux-64/2.0.5 -o /tmp/micromamba.tar.bz2
  tar -xjf /tmp/micromamba.tar.bz2 -C "$installed/.runtime" bin/micromamba
  for name in core maradoner r scan sce2g; do
    "$installed/.runtime/bin/micromamba" create -y -p "$installed/.runtime/envs/$name" -f "$installed/envs/$name.yaml"
    "$installed/.runtime/bin/micromamba" env export -p "$installed/.runtime/envs/$name" --explicit > "$installed/build-evidence/$name.explicit.txt"
  done
  ;;
sources)
  "$installed/.runtime/envs/core/bin/python" "$installed/scripts/fetch_maradoner.py" --destination "$installed/.tools/MARADONER"
  git init "$installed/.tools/scE2G"
  (
    cd "$installed/.tools/scE2G"
    git remote add origin https://github.com/EngreitzLab/scE2G.git
    git -c http.version=HTTP/1.1 fetch --depth 1 origin 7cb2af750fb96006f5d2b7c5475dcff30ea0e6c9
    git checkout --detach FETCH_HEAD
    git -c http.version=HTTP/1.1 submodule update --init --recursive --depth 1 --jobs 1
    git submodule status --recursive > "$installed/build-evidence/submodules.txt"
  )
  "$installed/.runtime/envs/maradoner/bin/python" -m pip install --only-binary=:all: -c "$installed/envs/maradoner-constraints.txt" click==8.1.8 "$installed/.tools/MARADONER"
  "$installed/.runtime/envs/maradoner/bin/python" -m pip check
  "$installed/.runtime/envs/maradoner/bin/python" -m pip freeze > "$installed/build-evidence/maradoner.pip.txt"
  ;;
stages)
  # Core module is pure Python here; no editable installation or runtime pip is needed.
  export PYTHONPATH="$installed/src"
  "$installed/.runtime/envs/sce2g/bin/python" "$installed/container/prebuild_sce2g.py"
  ;;
*) echo 'Unknown build stage' >&2; exit 2 ;;
esac
