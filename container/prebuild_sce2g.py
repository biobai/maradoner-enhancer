"""Build all three scE2G stage environments during podman build only."""
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from snakemake.deployment.conda import Env
from snakemake.sourcecache import SourceCache
from me.prebuilt import STAGE_FILES, stage_hash, verify_stage_environments

installed = Path('/opt/maradoner-enhancer')
repo = installed / '.tools/scE2G'
prefix = Path('/opt/me-stage-envs')
prefix.mkdir(parents=True, exist_ok=True)
assert importlib.metadata.version('snakemake') == '7.32.4'
manifest = {'snakemake': '7.32.4', 'environments': {}}
mm = installed / '.runtime/bin/micromamba'
workflow = SimpleNamespace(conda_frontend='mamba', singularity_args='', sourcecache=SourceCache())
for name in STAGE_FILES:
    spec = repo / name
    key = stage_hash(spec, prefix)
    upstream = Env(workflow, env_file=str(spec), env_dir=str(prefix))
    assert upstream.hash == key, 'Upstream environment hashing contract changed'
    target = prefix / key
    # Upstream scikit-learn 1.2.1 binaries require the NumPy 1.x ABI.
    constraints = ['numpy<2', 'snakemake=7.32.4']
    if name == STAGE_FILES[2]:
        constraints.append('pulp<2.8')
    subprocess.run([str(mm), 'create', '-y', '-p', str(target), '-f', str(spec), *constraints], check=True)
    deploy = spec.with_suffix('.post-deploy.sh')
    if deploy.exists():
        subprocess.run([str(mm), 'run', '-p', str(target), 'bash', str(deploy)], check=True, cwd=repo)
    with (prefix / f'{key}.explicit.txt').open('w') as f:
        subprocess.run([str(mm), 'env', 'export', '-p', str(target), '--explicit'], stdout=f, check=True)
    if (target / 'bin/python').exists():
        with (prefix / f'{key}.pip.txt').open('w') as f:
            subprocess.run([str(target / 'bin/python'), '-m', 'pip', 'freeze'], stdout=f, check=True)
        imports = 'import numpy,pandas,scipy'
        if name != STAGE_FILES[0]:
            imports += ',sklearn'
        if name == STAGE_FILES[2]:
            imports += '; import fast_kendall_sc'
        subprocess.run([str(target / 'bin/python'), '-c', imports], check=True)
    manifest['environments'][name] = {'hash': key, 'extra_constraints': constraints}
    assert upstream.address == str(target), 'Snakemake would not reuse the prebuilt environment'
(prefix / 'manifest.json').write_text(json.dumps(manifest, indent=2))
verify_stage_environments(repo, prefix)
