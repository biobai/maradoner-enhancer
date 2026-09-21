#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/common.sh"
[[ "$(uname -s)" == Linux ]] || { echo 'Linux is required for production bootstrap' >&2; exit 1; }
[[ "$(uname -m)" == x86_64 ]] || { echo 'This environment specification is validated for Linux x86_64 only' >&2; exit 1; }
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
"$CORE_PY" -m pip install --no-deps -e "$PROJECT_ROOT"
fetch_repo() {
  local repo="$1" name="$2" sha="$3"
  if [[ ! -d "$PROJECT_ROOT/.tools/$name/.git" ]]; then
    git clone "$repo" "$PROJECT_ROOT/.tools/$name"
  fi
  git -C "$PROJECT_ROOT/.tools/$name" fetch origin "$sha"
  git -C "$PROJECT_ROOT/.tools/$name" checkout --detach "$sha"
  git -C "$PROJECT_ROOT/.tools/$name" submodule update --init --recursive
}
fetch_repo https://github.com/autosome-ru/MARADONER.git MARADONER d01f9140bfee69d91e8e1fd3eac1e923e308d9a5
fetch_repo https://github.com/EngreitzLab/scE2G.git scE2G 7cb2af750fb96006f5d2b7c5475dcff30ea0e6c9
"$PROJECT_ROOT/.runtime/envs/maradoner/bin/python" -m pip install -c "$PROJECT_ROOT/envs/maradoner-constraints.txt" "click==8.1.8" "$PROJECT_ROOT/.tools/MARADONER"
for env in core maradoner r scan sce2g; do
  "$MM" list -p "$PROJECT_ROOT/.runtime/envs/$env" --explicit > "$PROJECT_ROOT/results/environment/$env.explicit.txt"
done
"$PROJECT_ROOT/.runtime/envs/maradoner/bin/python" -m pip freeze > "$PROJECT_ROOT/results/environment/maradoner.pip.txt"
"$CORE_PY" -m pip freeze > "$PROJECT_ROOT/results/environment/core.pip.txt"
git -C "$PROJECT_ROOT/.tools/scE2G" submodule status --recursive > "$PROJECT_ROOT/results/environment/scE2G.submodules.txt"
echo 'Installation complete. Next: bash scripts/run_smoke_test.sh --real-tools'
