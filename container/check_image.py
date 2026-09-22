"""Read-only runtime acceptance: fail rather than install missing dependencies."""
from pathlib import Path
import subprocess
from me.prebuilt import verify_stage_environments

root = Path('/opt/maradoner-enhancer')
commands = [
    [str(root/'.runtime/envs/core/bin/python'), '-c', 'import me,numpy,pandas,scipy,pyarrow,anndata,pyfaidx,psutil,yaml'],
    [str(root/'.runtime/envs/maradoner/bin/python'), '-c', 'import maradoner,jax,datatable,tables,pygam'],
    [str(root/'.runtime/envs/scan/bin/fimo'), '--version'],
    [str(root/'.runtime/envs/r/bin/Rscript'), '-e', 'library(Seurat);library(Signac);library(Matrix);library(jsonlite)'],
    [str(root/'.runtime/envs/sce2g/bin/python'), '-c', 'import snakemake; assert snakemake.__version__ == "7.32.4"'],
]
for command in commands:
    subprocess.run(command, check=True)
verify_stage_environments(root/'.tools/scE2G', '/opt/me-stage-envs')
print('All preinstalled software checks passed; no installation performed.')
