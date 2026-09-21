"""Deterministic annotation, promoter subtraction and FIMO coordinates."""
import gzip
import hashlib
import re
from pathlib import Path
import numpy as np
import pandas as pd
from .io import read_table, write_table, run, require


def representative_tss(gtf, reference):
    """Lexicographically smallest transcript_id per gene; expression independent."""
    rows = []
    opener = gzip.open if str(gtf).endswith(".gz") else open
    with opener(gtf, "rt") as f:
        for line in f:
            if line.startswith("#"):
                continue
            fields = line.rstrip().split("\t")
            if len(fields) != 9 or fields[2] != "transcript":
                continue
            attrs = dict(re.findall(r'(\w+) "([^"]*)"', fields[8]))
            if "gene_id" not in attrs or "transcript_id" not in attrs:
                raise ValueError("GTF transcript lacks gene_id/transcript_id")
            tss = int(fields[3]) - 1 if fields[6] == "+" else int(fields[4]) - 1
            rows.append((attrs["gene_id"], attrs["transcript_id"], fields[0], tss, fields[6], reference))
    df = pd.DataFrame(rows, columns=["gene_id", "transcript_id", "chrom", "tss", "strand", "reference"])
    if df.empty:
        raise ValueError("No transcript features in GTF")
    return df.sort_values(["gene_id", "transcript_id", "chrom", "tss"]).drop_duplicates("gene_id")


def prepare_regions(genes, peaks, flank=2000):
    require(peaks, ["region_id", "chrom", "start", "end"], ["region_id"])
    rows = []
    masks = {}
    for g in genes.itertuples():
        lo, hi = max(0, int(g.tss) - flank), int(g.tss) + flank + 1
        masks.setdefault(g.chrom, []).append((lo, hi))
        rows.append((f"P_{g.gene_id}", g.chrom, lo, hi, "promoter", g.gene_id, g.reference, f"P_{g.gene_id}"))
    for chrom, values in masks.items():
        merged = []
        for a, b in sorted(values):
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
            else:
                merged.append((a, b))
        masks[chrom] = merged
    for e in peaks.sort_values("region_id").itertuples():
        pieces = [(int(e.start), int(e.end))]
        if e.end <= e.start or e.start < 0:
            raise ValueError("Invalid peak interval")
        for a, b in masks.get(e.chrom, []):
            nxt = []
            for lo, hi in pieces:
                if hi <= a or lo >= b:
                    nxt.append((lo, hi))
                else:
                    if lo < a:
                        nxt.append((lo, a))
                    if b < hi:
                        nxt.append((b, hi))
            pieces = nxt
        for i, (lo, hi) in enumerate(pieces):
            rows.append((f"E_{e.region_id}_{i}", e.chrom, lo, hi, "enhancer", "-", genes.reference.iloc[0], e.region_id))
    return pd.DataFrame(rows, columns=["region_id", "chrom", "start", "end", "kind", "gene_id", "reference", "parent_region_id"])


def scan(regions, fasta, motifs, fimo, output, threshold=1e-4):
    from pyfaidx import Fasta
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    fa = Fasta(str(fasta), as_raw=True)
    region_fasta = out / "regions.fa"
    with region_fasta.open("w") as f:
        for r in regions.itertuples():
            if r.chrom not in fa or r.end > len(fa[r.chrom]):
                raise ValueError(f"Region outside FASTA: {r.region_id}")
            f.write(f">{r.region_id}\n{fa[r.chrom][int(r.start):int(r.end)]}\n")
    fa.close()
    # FIMO --text streams all thresholded hits without silently truncating the site store.
    run([fimo, "--text", "--thresh", str(threshold), str(motifs), str(region_fasta)], out / "fimo.log", stdout_path=out / "fimo.tsv")
    hits = pd.read_csv(out / "fimo.tsv", sep="\t", comment="#")
    return parse_fimo(hits, regions, str(out / "fimo.tsv"))


def parse_fimo(hits, regions, source):
    rr = regions.set_index("region_id")
    rows = []
    for h in hits.to_dict("records"):
        r = rr.loc[h["sequence_name"]]
        # FIMO positions are 1-based inclusive, irrespective of matched strand.
        a, b = int(r.start) + int(h["start"]) - 1, int(r.start) + int(h["stop"])
        identity = f'{h["sequence_name"]}:{h["motif_id"]}:{a}:{b}:{h["strand"]}'
        rows.append((hashlib.sha256(identity.encode()).hexdigest()[:24], h["sequence_name"],
                     h["motif_id"], r.chrom, a, b, h["strand"], h["score"], source))
    return pd.DataFrame(rows, columns=["site_id", "region_id", "motif_id", "chrom", "start", "end", "strand", "score", "source"])
