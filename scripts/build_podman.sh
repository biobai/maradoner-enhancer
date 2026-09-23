#!/usr/bin/env bash
# Run on a build machine with Podman. Conversion to SIF may happen on another host.
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$PROJECT_ROOT/container/image.env"
command -v podman >/dev/null || { echo 'Podman is required on the build machine.' >&2; exit 1; }
out="$PROJECT_ROOT/.container/images"
mkdir -p "$out"
mkdir "$out/build.lock" 2>/dev/null || { echo "Build lock exists: $out/build.lock" >&2; exit 1; }
trap 'rmdir -- "$out/build.lock"' EXIT
# Merge new layers so permission changes do not duplicate the installed software.
podman build --squash --platform linux/amd64 --format docker \
  --build-arg "BASE_IMAGE=$ME_BASE_IMAGE" \
  --iidfile "$out/podman-image.id" \
  --tag "$ME_IMAGE_TAG" --file "$PROJECT_ROOT/container/Containerfile" "$PROJECT_ROOT"
image_id=$(cat "$out/podman-image.id")
podman image inspect "$image_id" > "$out/podman-image.inspect.json"
podman --version > "$out/podman-version.txt"
temporary="$out/maradoner-enhancer-software.$$.tar"
podman save --format docker-archive --output "$temporary" "$image_id"
mv -- "$temporary" "$out/maradoner-enhancer-software.tar"
(cd -- "$out" && sha256sum maradoner-enhancer-software.tar > maradoner-enhancer-software.tar.sha256)
printf '%s\n' "$ME_BASE_IMAGE" > "$out/base-image.txt"
echo "Podman build/export complete: $out/maradoner-enhancer-software.tar"
echo 'On the build machine, run: bash scripts/container.sh convert'
echo 'Then upload only the SIF and its .sif.sha256 file to the cluster .container/images directory.'
