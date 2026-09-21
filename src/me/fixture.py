"""Small deterministic fixture; no scientific conclusions can be drawn from it."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import yaml
from .io import write_table, write_json, sha256


def make_fixture(root, backend="synthetic_ridge", n_genes=160, n_motifs=8):
    root = Path(root).resolve()
    data = root / "data/synthetic"
    data.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(3107)
    gids = [f"GENE{i:04d}" for i in range(n_genes)]
    mids = [f"M{i:03d}" for i in range(n_motifs)]
    genes = pd.DataFrame({"gene_id": gids, "chrom": "chr1", "tss": np.arange(n_genes)*10000+5000, "reference": "synthetic-v1"})
    regions, sites, links = [], [], []
    for j, g in genes.iterrows():
        for kind, prefix, start in [("promoter", "P", int(g.tss)-2000), ("enhancer", "E", int(g.tss)+3000)]:
            rid = f"{prefix}{j}"
            regions.append([rid, "chr1", start, start+1000, kind, g.gene_id if kind=="promoter" else "-", "synthetic-v1", rid])
            for k in rng.choice(n_motifs, int(rng.integers(1, 5)), replace=False):
                sites.append([f"{rid}_{k}", rid, mids[k], "chr1", start+int(k)*12, start+int(k)*12+8, "+", 10., "synthetic_fixture"])
        links.append([f"E{j}", g.gene_id, float(rng.uniform(.1, 1)), "synthetic_fixture", "build"])
    mapping = pd.DataFrame({"tf_id": gids[:n_motifs], "motif_id": mids, "family_id": [f"F{i}" for i in range(n_motifs)]})
    samples = []
    for donor in range(4):
        samples.append([f"ATAC{donor}", f"D{donor}", "B1", "untreated", "synthetic", "ATAC", "build", "NTC", "synthetic-v1", 1])
        for target in ["NTC", gids[0], gids[1]]:
            for rep in range(2):
                sid = f"D{donor}_{target}_{rep}"
                samples.append([sid, f"D{donor}", "B1", "untreated", "synthetic", "RNA", "control" if target=="NTC" else "perturb", target, "synthetic-v1", 1])
    samples = pd.DataFrame(samples, columns=["sample_id", "donor", "batch", "condition", "cell_type", "modality", "role", "target", "reference", "included"])
    expr_ids = list(samples.loc[samples.modality.eq("RNA"), "sample_id"])
    base = rng.lognormal(3.5, .7, n_genes)
    counts = np.column_stack([rng.poisson(base * rng.lognormal(0, .2, n_genes)) for _ in expr_ids])
    tables = {"genes": genes, "samples": samples, "mapping": mapping,
              "counts": pd.DataFrame(counts, index=gids, columns=expr_ids).rename_axis("gene_id").reset_index(),
              "regions": pd.DataFrame(regions, columns=["region_id", "chrom", "start", "end", "kind", "gene_id", "reference", "parent_region_id"]),
              "sites": pd.DataFrame(sites, columns=["site_id", "region_id", "motif_id", "chrom", "start", "end", "strand", "score", "source"]),
              "links": pd.DataFrame(links, columns=["region_id", "gene_id", "weight", "source", "build_group"])}
    for k, v in tables.items():
        write_table(v, data / f"{k}.tsv")
    write_json({"build_sample_ids": list(samples.loc[samples.role.eq("build"), "sample_id"]),
                "links_sha256": sha256(data / "links.tsv"), "reference": "synthetic-v1",
                "source_files": [{"path": "fixture_generator", "seed": 3107}]}, data / "link_provenance.json")
    c = {"root": "..", "output": "results/synthetic", "synthetic": True, "reference": "synthetic-v1",
         "inputs": {k: f"data/synthetic/{k}.tsv" for k in tables},
         "analysis": {"seed": 17, "cis_window": 100000, "distance_power": 1., "distance_bins": [2000, 10000, 50000],
                      "permutation_seeds": [19, 23], "alpha_factors": [.5, 1., 2.], "bootstrap_repeats": 100,
                      "min_expression_samples": 6}, "resources": {"memory_gb": 4, "disk_gb": 1, "cores": 2},
         "maradoner": {"backend": backend, "python": ".runtime/envs/maradoner/bin/python",
                       "repository": ".tools/MARADONER", "timeout_seconds": 1800}}
    c["inputs"]["link_provenance"] = "data/synthetic/link_provenance.json"
    (root / "config").mkdir(exist_ok=True)
    config = root / "config/synthetic.yaml"
    config.write_text(yaml.safe_dump(c, sort_keys=False), encoding="utf-8")
    return str(config)

