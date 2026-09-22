#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/common.sh"
[[ "$(uname -s)" == Linux ]] || { echo 'Linux is required for production bootstrap' >&2; exit 1; }
[[ "$(uname -m)" == x86_64 ]] || { echo 'This environment specification is validated for Linux x86_64 only' >&2; exit 1; }
glibc_version=$(getconf GNU_LIBC_VERSION 2>/dev/null | awk '{print $2}')
if [[ ! "$glibc_version" =~ ^([0-9]+)\.([0-9]+) ]]; then
  echo 'Cannot determine glibc version. This binary-wheel installation requires glibc >= 2.27.' >&2
  exit 1
fi
if (( BASH_REMATCH[1] < 2 || (BASH_REMATCH[1] == 2 && BASH_REMATCH[2] < 27) )); then
  echo "glibc $glibc_version is too old for the JAX >= 0.8 Linux wheels required by pinned MARADONER." >&2
  echo 'Use a suitable newer Linux node or an approved Apptainer/Singularity container. Upgrading GCC alone does not fix this.' >&2
  exit 1
fi
for cmd in curl tar git; do command -v "$cmd" >/dev/null || { echo "Missing $cmd" >&2; exit 1; }; done
# Stop before environment downloads on clearly insufficient hosts; analysis budgets
# are checked again by check_environment.sh after the core Python is available.
disk_kb=$(df -Pk "$PROJECT_ROOT" | awk 'NR==2 {print $4}')
mem_kb=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)
[[ "${disk_kb:-0}" -ge 20971520 ]] || { echo 'At least 20 GiB free is required before installing environments' >&2; exit 1; }
[[ "${mem_kb:-0}" -ge 2097152 ]] || { echo 'At least 2 GiB available RAM is required for environment setup' >&2; exit 1; }
mkdir -p "$PROJECT_ROOT/.runtime/bin" "$PROJECT_ROOT/.tools" "$PROJECT_ROOT/results/environment"
printf 'channels:\n  - conda-forge\n  - bioconda\nchannel_priority: flexible\n' > "$CONDARC"
MM="$PROJECT_ROOT/.runtime/bin/micromamba"
if [[ ! -x "$MM" ]]; then
  curl --fail --location --retry 3 'https://micro.mamba.pm/api/micromamba/linux-64/2.0.5' -o "$PROJECT_ROOT/.runtime/micromamba.tar.bz2"
  tar -xjf "$PROJECT_ROOT/.runtime/micromamba.tar.bz2" -C "$PROJECT_ROOT/.runtime" bin/micromamba
fi
for env in core maradoner r scan sce2g; do
  if [[ ! -d "$PROJECT_ROOT/.runtime/envs/$env/conda-meta" ]]; then
    "$MM" create -y -p "$PROJECT_ROOT/.runtime/envs/$env" -f "$PROJECT_ROOT/envs/$env.yaml"
  fi
done
# Prefer the project-local Git installed in the core environment over old system Git.
export PATH="$PROJECT_ROOT/.runtime/envs/core/bin:$PATH"
"$CORE_PY" -m pip install --no-deps -e "$PROJECT_ROOT"
fetch_repo() {
  local repo="$1" name="$2" sha="$3"
  if [[ ! -d "$PROJECT_ROOT/.tools/$name/.git" ]]; then
    local cloned=0
    for attempt in 1 2 3; do
      if git -c http.version=HTTP/1.1 clone "$repo" "$PROJECT_ROOT/.tools/$name"; then cloned=1; break; fi
      echo "Git clone failed ($attempt/3): $repo" >&2
      if [[ -e "$PROJECT_ROOT/.tools/$name" ]]; then
        mv -- "$PROJECT_ROOT/.tools/$name" "$PROJECT_ROOT/.tools/$name.incomplete.$(date +%s).$attempt"
      fi
      sleep 2
    done
    [[ "$cloned" == 1 ]] || { echo "Cannot fetch $name. This repository requires Git submodules; an ordinary source ZIP is not a complete replacement." >&2; return 1; }
  fi
  (
    cd -- "$PROJECT_ROOT/.tools/$name"
    if ! git cat-file -e "$sha^{commit}" 2>/dev/null; then
      git -c http.version=HTTP/1.1 fetch origin "$sha"
    fi
    git checkout --detach "$sha"
    git submodule update --init --recursive
  )
}
# Official commit archives avoid the Git smart-HTTP endpoint that some clusters block.
archive_args=()
if [[ -n "${MARADONER_ARCHIVE:-}" ]]; then archive_args=(--archive "$MARADONER_ARCHIVE"); fi
"$CORE_PY" "$PROJECT_ROOT/scripts/fetch_maradoner.py" --destination "$PROJECT_ROOT/.tools/MARADONER" "${archive_args[@]}"
fetch_repo https://github.com/EngreitzLab/scE2G.git scE2G 7cb2af750fb96006f5d2b7c5475dcff30ea0e6c9
"$PROJECT_ROOT/.runtime/envs/maradoner/bin/python" -m pip install --only-binary=:all: -c "$PROJECT_ROOT/envs/maradoner-constraints.txt" "click==8.1.8" "$PROJECT_ROOT/.tools/MARADONER"
for env in core maradoner r scan sce2g; do
  "$MM" list -p "$PROJECT_ROOT/.runtime/envs/$env" --explicit > "$PROJECT_ROOT/results/environment/$env.explicit.txt"
done
"$PROJECT_ROOT/.runtime/envs/maradoner/bin/python" -m pip freeze > "$PROJECT_ROOT/results/environment/maradoner.pip.txt"
"$CORE_PY" -m pip freeze > "$PROJECT_ROOT/results/environment/core.pip.txt"
(cd -- "$PROJECT_ROOT/.tools/scE2G" && git submodule status --recursive) > "$PROJECT_ROOT/results/environment/scE2G.submodules.txt"
echo 'Installation complete. Next: bash scripts/run_smoke_test.sh --real-tools'
