import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from .io import run, write_json, software_root

MARADONER_COMMIT = "d01f9140bfee69d91e8e1fd3eac1e923e308d9a5"


def fit_activity(expression, B, groups, work, settings, root):
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    expr, load = work / "expression.tsv", work / "loadings.tsv"
    expression.to_csv(expr, sep="\t", index_label="gene_id")
    B.to_csv(load, sep="\t", index_label="gene_id")
    write_json(groups, work / "groups.json")
    backend = settings["backend"]
    if backend == "synthetic_ridge":
        # Explicit diagnostic backend. Never labelled MARADONER or scientific evidence.
        y = expression.to_numpy()
        y = y - y.mean(axis=1, keepdims=True)
        x = B.to_numpy()
        x = x - x.mean(axis=0, keepdims=True)
        a = np.linalg.solve(x.T @ x + np.eye(x.shape[1]), x.T @ y)
        result = pd.DataFrame(a, index=B.columns, columns=expression.columns)
        result.rename_axis("motif_id").to_csv(work / "activities.tsv", sep="\t")
        pd.DataFrame({"motif_id": B.columns, "delta": np.nan, "z": np.nan}).to_csv(work / "contrast.tsv", sep="\t", index=False)
    elif backend == "maradoner":
        repo = Path(settings["repository"])
        import subprocess
        from .io import sha256
        if (repo / ".source_revision.json").exists():
            receipt = json.loads((repo / ".source_revision.json").read_text())
            sha = receipt["commit"]
            if any(sha256(repo / f) != h for f, h in receipt["files"].items()):
                raise ValueError("Pinned source archive has been modified")
        else:
            sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo, text=True).strip():
                raise ValueError("MARADONER tracked source modified; adapter must be re-audited")
        if sha != MARADONER_COMMIT:
            raise ValueError(f"Unaudited MARADONER commit: {sha}")
        sources = {str(p.relative_to(repo / "maradoner")).replace("\\", "/"): sha256(p) for p in (repo / "maradoner").rglob("*.py")}
        q = {"expression": str(expr), "loadings": str(load), "groups": str(work / "groups.json"), "work": str(work), "source_hashes": sources}
        write_json(q, work / "request.json")
        run([settings["python"], str(software_root(root) / "scripts/maradoner_bridge.py"), str(work / "request.json")], work / "bridge.log", timeout=settings.get("timeout_seconds", 86400))
        result = pd.read_csv(work / "activities.tsv", sep="\t", index_col=0)
    else:
        raise ValueError(f"Unknown backend {backend}; no fallback is permitted")
    if set(result.index) != set(B.columns) or set(result.columns) != set(expression.columns):
        raise ValueError("Activity axes differ from frozen inputs")
    result = result.loc[B.columns, expression.columns]
    if not np.isfinite(result.to_numpy()).all():
        raise ValueError("Nonfinite activities")
    return result
