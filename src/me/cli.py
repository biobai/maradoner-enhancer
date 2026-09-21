import argparse
import json
from pathlib import Path
import sys
from .io import config, read_table, write_table


def main(argv=None):
    p = argparse.ArgumentParser(prog="me", description="Auditable enhancer integration research workflow")
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--config", required=True); r.add_argument("--until", default="report", choices=["validate", "features", "fit", "evaluate", "report"])
    r.add_argument("--dry-run", action="store_true"); r.add_argument("--force", action="store_true")
    r.add_argument("--cores", type=int, default=None)
    f = sub.add_parser("fixture"); f.add_argument("--root", default=".")
    f.add_argument("--backend", choices=["synthetic_ridge", "maradoner"], default="synthetic_ridge")
    f.add_argument("--genes", type=int, default=160)
    d = sub.add_parser("download"); d.add_argument("manifest"); d.add_argument("directory")
    q = sub.add_parser("check"); q.add_argument("--config", required=True); q.add_argument("--network", action="store_true")
    a = sub.add_parser("aggregate-mtx")
    for key in ["matrix", "genes", "cells", "metadata", "output", "reference"]: a.add_argument("--"+key, required=True)
    a = sub.add_parser("aggregate-h5ad")
    for key in ["input", "output", "reference"]: a.add_argument("--"+key, required=True)
    a.add_argument("--layer", default="X")
    a = sub.add_parser("regions")
    for key in ["gtf", "peaks", "reference", "output"]: a.add_argument("--"+key, required=True)
    a.add_argument("--flank", default=2000, type=int)
    a = sub.add_parser("scan")
    for key in ["regions", "fasta", "motifs", "output"]: a.add_argument("--"+key, required=True)
    a.add_argument("--fimo", default="fimo"); a.add_argument("--threshold", type=float, default=1e-4)
    a = sub.add_parser("fragments")
    for key in ["input", "membership", "output"]: a.add_argument("--"+key, required=True)
    a.add_argument("--heldout-donor")
    a = sub.add_parser("sce2g")
    for key in ["repository", "fragments", "output", "snakemake"]: a.add_argument("--"+key, required=True)
    a.add_argument("--cores", type=int, default=4); a.add_argument("--memory-mb", type=int, default=32000)
    a.add_argument("--dry-run", action="store_true")
    a = sub.add_parser("import-links")
    for key in ["predictions", "columns", "regions", "genes", "provenance", "output", "reference"]: a.add_argument("--"+key, required=True)
    a.add_argument("--threshold", type=float, default=0)
    a = sub.add_parser("holdout")
    for key in ["config", "expression", "loadings", "test-genes", "groups", "output"]: a.add_argument("--"+key, required=True)
    args = p.parse_args(argv)
    try:
        if args.command == "run":
            from .pipeline import pipeline
            c = config(args.config)
            if args.cores is not None:
                c["resources"]["cores"] = args.cores
            result = pipeline(c, args.until, args.dry_run, args.force)
        elif args.command == "fixture":
            from .fixture import make_fixture
            result = {"config": make_fixture(args.root, args.backend, args.genes)}
        elif args.command == "download":
            from .download import download_manifest
            download_manifest(args.manifest, args.directory); result = {"download": "completed"}
        elif args.command == "check":
            from .preflight import check
            result = check(config(args.config), args.network)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result["issues"] else 0
        elif args.command == "aggregate-mtx":
            from .aggregate import aggregate_mtx
            ids = lambda p: Path(p).read_text().splitlines()
            aggregate_mtx(args.matrix, ids(args.genes), ids(args.cells), read_table(args.metadata), args.output, args.reference)
            result = {"output": args.output}
        elif args.command == "aggregate-h5ad":
            from .aggregate import aggregate_h5ad
            aggregate_h5ad(args.input, args.layer, args.output, args.reference); result = {"output": args.output}
        elif args.command == "regions":
            from .genome import representative_tss, prepare_regions
            genes = representative_tss(args.gtf, args.reference)
            regions = prepare_regions(genes, read_table(args.peaks), args.flank)
            write_table(genes, Path(args.output) / "genes.tsv")
            write_table(regions, Path(args.output) / "regions.tsv"); result = {"output": args.output}
        elif args.command == "scan":
            from .genome import scan
            sites = scan(read_table(args.regions), args.fasta, args.motifs, args.fimo, args.output, args.threshold)
            write_table(sites, Path(args.output) / "motif_sites.parquet"); result = {"sites": len(sites)}
        elif args.command == "fragments":
            from .sce2g import subset_fragments
            result = subset_fragments(args.input, read_table(args.membership), args.output, args.heldout_donor)
        elif args.command == "sce2g":
            from .sce2g import run_sce2g
            result = {"predictions": run_sce2g(args.repository, args.fragments, args.output, args.snakemake, args.cores, args.memory_mb, args.dry_run)}
        elif args.command == "import-links":
            from .sce2g import import_links
            import_links(args.predictions, json.loads(Path(args.columns).read_text()), read_table(args.regions), read_table(args.genes),
                         args.provenance, args.output, args.reference, args.threshold)
            result = {"output": args.output}
        elif args.command == "holdout":
            from .holdout import run_holdout
            c = config(args.config)
            result = run_holdout(args.expression, args.loadings, args.test_genes, args.groups, c["maradoner"], c["_root"], args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
