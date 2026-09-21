import os
import platform
import shutil
import sys
from pathlib import Path
import psutil
from .io import write_json


def check(c, network=False):
    usage = shutil.disk_usage(c["_root"])
    mem = psutil.virtual_memory()
    issues = []
    if c["resources"]["cores"] < 1 or c["resources"]["cores"] > (os.cpu_count() or 1):
        issues.append("Configured cores must be positive and no greater than available CPUs")
    dependencies = {}
    if c["maradoner"]["backend"] == "maradoner":
        for name, path in {"MARADONER_python": c["maradoner"]["python"],
                           "MARADONER_source": c["maradoner"]["repository"],
                           "Rscript": str(Path(c["_root"])/".runtime/envs/r/bin/Rscript"),
                           "FIMO": str(Path(c["_root"])/".runtime/envs/scan/bin/fimo"),
                           "scE2G_snakemake": str(Path(c["_root"])/".runtime/envs/sce2g/bin/snakemake")}.items():
            dependencies[name] = Path(path).exists()
            if not dependencies[name]:
                issues.append(f"Missing {name}: {path}")
    if c["maradoner"]["backend"] == "maradoner" and platform.system() != "Linux":
        issues.append("Production deployment targets Linux; local diagnostics may run on other OS")
    if usage.free < c["resources"]["disk_gb"] * 1024**3:
        issues.append("Insufficient free disk for configured budget")
    if mem.available < c["resources"]["memory_gb"] * 1024**3:
        issues.append("Available memory below configured working budget; lower concurrency or select subset")
    connections = {}
    if network:
        import urllib.request
        for host in ["https://www.ncbi.nlm.nih.gov", "https://www.ebi.ac.uk", "https://github.com"]:
            try:
                with urllib.request.urlopen(host, timeout=15) as resp:
                    connections[host] = resp.status
            except Exception as e:
                connections[host] = str(e)
                issues.append(f"Data source connection failed: {host}")
    result = {"os": platform.platform(), "machine": platform.machine(), "python": sys.version,
              "cpu": os.cpu_count(), "available_memory_gb": mem.available / 1024**3,
              "free_disk_gb": usage.free / 1024**3, "glibc": platform.libc_ver(), "issues": issues,
              "network": connections, "dependencies": dependencies,
              "missing_inputs": [v for v in c["inputs"].values() if not Path(v).exists()]}
    write_json(result, Path(c["_root"]) / "results/preflight.json")
    return result
