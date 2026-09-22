"""Fixed Snakemake 7.32.4 environment cache, built once inside the image."""
import hashlib
import json
from pathlib import Path

STAGE_FILES = (
    'ENCODE_rE2G/ABC/workflow/envs/abcenv.yml',
    'ENCODE_rE2G/workflow/envs/encode_re2g.yml',
    'workflow/envs/sc_e2g.yml',
)


def stage_hash(specification, prefix):
    # Audited against snakemake 7.32.4 deployment/conda.py Env.hash.
    # No nested container is used. Snakemake checks an existing full-hash directory.
    spec = Path(specification)
    digest = hashlib.md5(str(Path(prefix).resolve()).encode())
    deploy = spec.with_suffix('.post-deploy.sh')
    if deploy.exists():
        digest.update(deploy.read_bytes())
    digest.update(spec.read_bytes())
    return digest.hexdigest()


def verify_stage_environments(repository, prefix):
    repo, prefix = Path(repository), Path(prefix)
    manifest = json.loads((prefix / 'manifest.json').read_text())
    if manifest['snakemake'] != '7.32.4':
        raise ValueError('Unsupported prebuilt Snakemake environment contract')
    for name in STAGE_FILES:
        expected = stage_hash(repo / name, prefix)
        if manifest['environments'].get(name, {}).get('hash') != expected:
            raise ValueError(f'Environment specification changed; rebuild image: {name}')
        if not (prefix / expected / 'conda-meta/history').exists():
            raise ValueError(f'Prebuilt environment absent; rebuild image: {name}')
    return manifest
