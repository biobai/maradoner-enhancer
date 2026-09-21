import gzip
import json
import subprocess
from pathlib import Path
import pandas as pd
import yaml
from .io import require, run, sha256, write_json, write_table, read_table

COMMIT = "7cb2af750fb96006f5d2b7c5475dcff30ea0e6c9"


def subset_fragments(source, membership, output, heldout=None, bgzip="bgzip", tabix="tabix"):
    """Stream one donor/library at a time; barcodes must be unique within that library."""
    require(membership, ["cell_id", "sample_id", "donor", "role", "target", "included"], ["cell_id"])
    selected = membership[membership.included.astype(str).eq("1") & membership.role.eq("build")]
    if heldout:
        selected = selected[selected.donor != heldout]
    if selected.empty or (selected.target != "NTC").any():
        raise ValueError("No unperturbed build cells, or target labels in build set")
    wanted = set(selected.cell_id)
    output = Path(output).resolve()
    if not str(output).endswith(".gz"):
        raise ValueError("Fragment output must end in .gz for bgzip/tabix")
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = output.with_suffix(".unsorted.tsv")
    seen, previous = set(), None
    opener = gzip.open if str(source).endswith(".gz") else open
    with opener(source, "rt") as f, raw.open("w") as dst:
        for line in f:
            if line.startswith("#"):
                continue
            a = line.rstrip().split("\t")
            if len(a) != 5:
                raise ValueError("Fragments require exactly five columns")
            chrom, start, end, cell, count = a
            start, end, count = int(start), int(end), int(count)
            if start < 0 or end <= start or count < 1:
                raise ValueError("Invalid fragment")
            if cell in wanted:
                dst.write(line); seen.add(cell)
    if not seen:
        raise ValueError("No matching fragments")
    # sort output is streamed into a file rather than accumulated in memory.
    import os
    env = os.environ.copy(); env["LC_ALL"] = "C"
    sorted_file = output.with_suffix("")
    with sorted_file.open("wb") as f:
        subprocess.run(["sort", "-k1,1", "-k2,2n", str(raw)], stdout=f, env=env, check=True)
    run([bgzip, "-f", str(sorted_file)], str(output) + ".bgzip.log")
    run([tabix, "-f", "-p", "bed", str(output)], str(output) + ".tabix.log")
    raw.unlink()
    receipt = {"build_sample_ids": sorted(selected.sample_id.unique()), "donors": sorted(selected.donor.unique()),
               "heldout_donor": heldout, "source_sha256": sha256(source), "membership_sha256": sha256_bytes(membership),
               "fragments_sha256": sha256(output), "n_selected": len(wanted), "n_with_fragments": len(seen),
               "missing_cells": sorted(wanted-seen)}
    write_json(receipt, str(output) + ".provenance.json")
    return receipt


def sha256_bytes(df):
    import hashlib
    return hashlib.sha256(df.sort_values("cell_id").to_csv(index=False).encode()).hexdigest()


def run_sce2g(repository, fragments, output, snakemake, cores=4, memory_mb=32000, dry_run=False):
    repo, output, fragments = map(lambda x: Path(x).resolve(), (repository, output, fragments))
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if sha != COMMIT:
        raise ValueError(f"Unaudited scE2G revision {sha}")
    provenance_file = Path(str(fragments) + ".provenance.json")
    receipt = json.loads(provenance_file.read_text())
    if receipt["fragments_sha256"] != sha256(fragments):
        raise ValueError("Fragment membership receipt does not match")
    if not Path(str(fragments) + ".tbi").exists():
        raise ValueError("Missing tabix index")
    output.mkdir(parents=True, exist_ok=True)
    clusters = output / "clusters.tsv"
    # Header verified against pinned config/config_cell_clusters.tsv.
    pd.DataFrame([{"cluster": "build", "rna_matrix_file": "", "atac_frag_file": str(fragments),
        "HiC_file": "", "HiC_type": "", "HiC_resolution": "", "alt_TSS": "", "alt_genes": "",
        "model_dir": "models/scATAC_powerlaw_v3"}]).to_csv(clusters, sep="\t", index=False)
    cfg = yaml.safe_load((repo / "config/config.yaml").read_text())
    cfg.update(cell_clusters=str(clusters), results_dir=str(output / "results"), IGV_dir=str(output / "igv"),
               max_memory_allocation_mb=memory_mb, threads=cores, benchmark_performance=False, make_IGV_tracks=False,
               max_cell_count=receipt["n_with_fragments"] + 1)
    config = output / "sce2g.yaml"
    config.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    command = [snakemake, "--configfile", str(config), "--cores", str(cores), "--use-conda", "--conda-prefix", str(output / "conda_envs")]
    if dry_run:
        command.append("--dry-run")
    import os
    env = os.environ.copy()
    env["PATH"] = str(Path(snakemake).resolve().parent) + os.pathsep + env.get("PATH", "")
    env["CONDA_PREFIX"] = str(Path(snakemake).resolve().parent.parent)
    run(command, output / "sce2g.log", cwd=repo, env=env)
    pred = output / "results/build/scATAC_powerlaw_v3/scE2G_predictions.tsv.gz"
    if not dry_run and not pred.exists():
        raise FileNotFoundError(f"Upstream output contract changed: {pred}")
    write_json({**receipt, "commit": sha, "dry_run": dry_run, "prediction_file": str(pred),
                "source_files": [{"path": str(fragments), "sha256": sha256(fragments)}]}, output / "provenance.json")
    return str(pred)


def import_links(predictions, column_map, regions, genes, provenance, output, reference, threshold=0):
    """Explicit column mapping avoids guessing upstream schemas; splits inherit weights.

    Expected mapped coordinates are 0-based half-open ORIGINAL peak coordinates.
    Regions.parent_region_id must be 'chrom:start-end' for imported scE2G peaks.
    """
    src = pd.read_csv(predictions, sep="\t", keep_default_na=False)
    data = src.rename(columns={v: k for k, v in column_map.items()})
    require(data, ["chrom", "start", "end", "gene_id", "weight"])
    data["weight"] = pd.to_numeric(data.weight)
    data = data[data.weight >= threshold].copy()
    data["parent_region_id"] = data.chrom + ":" + data.start.astype(str) + "-" + data.end.astype(str)
    if data.duplicated(["parent_region_id", "gene_id"]).any():
        raise ValueError("Duplicate scE2G pairs; select one build grouping before import")
    if not set(data.gene_id) <= set(genes.gene_id):
        raise ValueError("scE2G gene IDs differ from annotation; explicit mapping required")
    enh = regions[regions.kind.eq("enhancer")]
    missing = set(data.parent_region_id) - set(regions.parent_region_id)
    # Original scE2G peaks fully covered by promoters disappear during subtraction.
    # Exclude only intervals whose complete coverage can be proven from the atlas.
    covered = set()
    for row in data[data.parent_region_id.isin(missing)].itertuples():
        cursor = int(row.start)
        pp = regions[regions.kind.eq("promoter") & regions.chrom.eq(row.chrom)].sort_values("start")
        for p in pp.itertuples():
            if p.end <= cursor:
                continue
            if p.start > cursor:
                break
            cursor = max(cursor, int(p.end))
            if cursor >= int(row.end):
                covered.add(row.parent_region_id)
                break
    missing -= covered
    if missing:
        raise ValueError(f"scE2G candidate regions absent from region atlas: {len(missing)}")
    merged = data.merge(enh[["region_id", "parent_region_id"]], on="parent_region_id")
    result = merged[["region_id", "gene_id", "weight"]].copy()
    result["source"], result["build_group"] = str(Path(predictions).resolve()), "build"
    out = Path(output)
    write_table(result, out)
    prov = json.loads(Path(provenance).read_text())
    prov.update(reference=reference, links_sha256=sha256(out), score_column=column_map["weight"], threshold=threshold,
                excluded_promoter_only_regions=sorted(covered),
                source_files=[{"path": str(Path(predictions).resolve()), "sha256": sha256(predictions)}], column_map=column_map)
    write_json(prov, str(out) + ".provenance.json")
