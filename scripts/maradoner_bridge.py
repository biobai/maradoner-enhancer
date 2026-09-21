"""Runs inside the isolated MARADONER environment; pinned source interface.

No user-supplied pickle is loaded: only artifacts created in this invocation.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("request")
    args = parser.parse_args()
    q = json.loads(Path(args.request).read_text(encoding="utf-8"))
    import hashlib
    import maradoner
    package = Path(maradoner.__file__).parent
    for filename, expected in q["source_hashes"].items():
        if hashlib.sha256((package / filename).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Installed package differs from pinned source: {filename}")
    root = Path(q["work"])
    root.mkdir(parents=True, exist_ok=True)
    project = str(root / "model")
    def call(stage, argv):
        with (root / f"{stage}.log").open("w", encoding="utf-8") as f:
            p = subprocess.run([sys.executable, "-c", "from maradoner.main import main; main()", *argv], stdout=f, stderr=subprocess.STDOUT)
        (root / f"{stage}.exit.json").write_text(json.dumps({"argv": argv, "exit_code": p.returncode}))
        if p.returncode:
            raise RuntimeError(f"MARADONER {stage} failed: {root / (stage + '.log')}")
    # Pinned CLI declares n_jobs float; datatable.fread rejects 1.0. Call the
    # actual public Python constructor with an integer rather than patch upstream.
    from maradoner.create import create_project
    import contextlib
    create_args = dict(loading_matrix_filenames=[q["loadings"]], sample_groups=q["groups"],
                       loading_matrix_transformations=["none"], promoter_filter_lowexp_cutoff=1.,
                       promoter_filter_plot_filename=None, n_jobs=1, compression="raw", verbose=True)
    try:
        with (root / "create.log").open("w", encoding="utf-8") as stream, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            create_project(project, q["expression"], **create_args)
        create_status = {"api": "maradoner.create.create_project", "kwargs": create_args, "exit_code": 0}
    except Exception as e:
        create_status = {"api": "maradoner.create.create_project", "kwargs": create_args, "exit_code": 1, "error": str(e)}
        raise
    finally:
        (root / "create.exit.json").write_text(json.dumps(create_status, indent=2))
    from maradoner.utils import read_init, openers
    import dill
    data = read_init(project)
    expected_m = pd.read_csv(q["loadings"], sep="\t").columns[1:].tolist()
    expected_g = pd.read_csv(q["loadings"], sep="\t").iloc[:, 0].astype(str).tolist()
    if list(data.motif_names) != expected_m or list(data.promoter_names) != expected_g:
        raise ValueError("Upstream create changed the frozen feature universe")
    call("fit", ["fit", project])
    call("predict", ["predict", project, "--no-filter-motifs"])
    with openers[data.fmt](f"{project}.predict.{data.fmt}", "rb") as f:
        act = dill.load(f)
    with openers[data.fmt](f"{project}.fit.{data.fmt}", "rb") as f:
        fit = dill.load(f)
    if act.filtered_motifs is not None and len(act.filtered_motifs):
        raise ValueError("Unexpected motif filtering")
    from maradoner.fit import motif_mean_matrix
    total = np.asarray(act.U_raw) + np.asarray(motif_mean_matrix(fit.motif_mean, data.X))
    if total.shape != (len(expected_m), len(data.sample_names)) or not np.isfinite(total).all():
        raise ValueError("Invalid activity matrix")
    pd.DataFrame(total, index=expected_m, columns=data.sample_names).rename_axis("motif_id").to_csv(root / "activities.tsv", sep="\t")
    # Group posterior SD is not a sample-specific uncertainty; export separately.
    cov = [np.asarray(v) for v in act.cov()]
    if len(cov) != len(data.group_names):
        raise ValueError("Group covariance dimensions changed")
    gd = pd.DataFrame(np.sqrt(np.maximum(0, np.asarray([v.diagonal() for v in cov]))).T,
                      index=expected_m, columns=data.group_names)
    gd.rename_axis("motif_id").to_csv(root / "group_posterior_sd.tsv", sep="\t")
    # Fixed diagonal group covariance model only. This is a model-conditional contrast.
    ix = {v: i for i, v in enumerate(data.group_names)}
    delta = np.asarray(act.U)[:, ix["KO"]] - np.asarray(act.U)[:, ix["NT"]]
    var = np.diag(cov[ix["KO"]]) + np.diag(cov[ix["NT"]])
    z = np.divide(delta, np.sqrt(np.maximum(var, 0)), out=np.full_like(delta, np.nan), where=var > 0)
    pd.DataFrame({"motif_id": expected_m, "delta": delta, "z": z}).to_csv(root / "contrast.tsv", sep="\t", index=False)
    import importlib.metadata
    (root / "versions.json").write_text(json.dumps({x: importlib.metadata.version(x) for x in
        ["maradoner", "jax", "numpy", "scipy", "pandas", "datatable"]}, indent=2))


if __name__ == "__main__":
    main()
