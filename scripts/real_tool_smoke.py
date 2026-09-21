"""Exercise real MARADONER on synthetic input. Linux optionally tests R/FIMO/scE2G.

Success is SOFTWARE validation only, never scientific validation.
"""
import argparse
import json
import platform
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from me.io import write_json, read_table, run
from me.model import fit_activity


def main():
    root = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser()
    p.add_argument("--python", default=str(root / ".runtime/envs/maradoner/bin/python"))
    p.add_argument("--with-sce2g", action="store_true")
    p.add_argument("--maradoner-only", action="store_true")
    args = p.parse_args()
    out = root / "results/real_tool_smoke"
    out.mkdir(parents=True, exist_ok=True)
    status = {"input": "synthetic", "scientific_validation": False, "platform": platform.platform(), "status": "running"}
    write_json(status, out / "status.json")
    try:
        rng = np.random.default_rng(120)
        genes = [f"g{i:04d}" for i in range(400)]
        motifs = [f"m{i}" for i in range(6)]
        samples = [f"s{i:02d}" for i in range(12)]
        b = rng.gamma(2, 1, size=(400, 6))
        b /= np.sqrt((b**2).mean(axis=0))
        u = rng.normal(0, .25, size=(6, 12))
        u[0, 6:] += .8
        y = 5 + rng.normal(0, .5, size=(400, 1)) + b @ u + rng.normal(0, .15, size=(400, 12))
        settings = {"backend": "maradoner", "python": str(Path(args.python).resolve()),
                    "repository": str(root / ".tools/MARADONER"), "timeout_seconds": 1800}
        values = fit_activity(pd.DataFrame(y, index=genes, columns=samples), pd.DataFrame(b, index=genes, columns=motifs),
                              {"NT": samples[:6], "KO": samples[6:]}, out / "maradoner", settings, root)
        assert np.isfinite(values.to_numpy()).all()
        status["MARADONER"] = {"status": "passed", "genes": 400, "motifs": 6, "samples": 12}
        if not args.maradoner_only:
            from me.genome import scan
            (out / "tiny.fa").write_text(">chr1\n" + "ACGT"*100 + "\n")
            (out / "tiny.meme").write_text("MEME version 4\n\nALPHABET= ACGT\n\nstrands: + -\n\nBackground letter frequencies\nA 0.25 C 0.25 G 0.25 T 0.25\n\nMOTIF toy\nletter-probability matrix: alength= 4 w= 4 nsites= 20 E= 0\n0.97 0.01 0.01 0.01\n0.01 0.97 0.01 0.01\n0.01 0.01 0.97 0.01\n0.01 0.01 0.01 0.97\n")
            regions = pd.DataFrame([{"region_id": "tiny", "chrom": "chr1", "start": 0, "end": 100}])
            sites = scan(regions, out / "tiny.fa", out / "tiny.meme", str(root / ".runtime/envs/scan/bin/fimo"), out / "scan", .01)
            assert len(sites) > 0
            status["FIMO"] = {"status": "passed", "sites": len(sites)}
            run([str(root / ".runtime/envs/r/bin/Rscript"), "-e", "library(Seurat); library(Signac); library(Matrix); x <- Matrix(matrix(c(1,0,2,3),2),sparse=TRUE); stopifnot(sum(x)==6); sessionInfo()"], out / "R.log")
            status["R"] = {"status": "passed_import_and_sparse_matrix"}
        if args.with_sce2g:
            import gzip
            from me.sce2g import subset_fragments, run_sce2g
            repo = root / ".tools/scE2G"
            source = repo / "resources/example_chr22_multiome_cluster/cluster1/atac_fragments.tsv.gz"
            with gzip.open(source, "rt") as f:
                cells = sorted({x.split("\t")[3] for x in f if not x.startswith("#")})
            metadata = pd.DataFrame({"cell_id": cells, "sample_id": "official_example", "donor": "example", "role": "build", "target": "NTC", "included": 1})
            frag = out / "example.fragments.tsv.gz"
            scanbin = root / ".runtime/envs/scan/bin"
            subset_fragments(source, metadata, frag, bgzip=str(scanbin / "bgzip"), tabix=str(scanbin / "tabix"))
            pred = run_sce2g(repo, frag, out / "sce2g", str(root / ".runtime/envs/sce2g/bin/snakemake"))
            assert len(pd.read_csv(pred, sep="\t")) > 0
            status["scE2G"] = {"status": "passed_official_chr22_example"}
        else:
            status["scE2G"] = {"status": "not_run;use_--with-sce2g"}
        status["status"] = "success"
    except Exception as e:
        status.update(status="failed", error=str(e))
        raise
    finally:
        write_json(status, out / "status.json")
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()

