import json
import numpy as np
from .io import read_table, require, numeric, sha256


def load_inputs(c):
    names = ["samples", "genes", "regions", "sites", "links", "mapping", "counts"]
    tables = {k: read_table(c["inputs"][k]) for k in names}
    s, g, r, sites, links, mapping, counts = [tables[k] for k in names]
    require(s, ["sample_id", "donor", "batch", "condition", "cell_type", "modality", "role",
                "target", "reference", "included"], ["sample_id"], "samples")
    require(g, ["gene_id", "chrom", "tss", "reference"], ["gene_id"], "genes")
    require(r, ["region_id", "chrom", "start", "end", "kind", "gene_id", "reference"], ["region_id"], "regions")
    require(sites, ["site_id", "region_id", "motif_id", "chrom", "start", "end", "strand", "score", "source"], ["site_id"], "sites")
    require(links, ["region_id", "gene_id", "weight", "source", "build_group"], ["region_id", "gene_id"], "links")
    require(mapping, ["tf_id", "motif_id", "family_id"], ["tf_id", "motif_id", "family_id"], "mapping")
    require(counts, ["gene_id"], ["gene_id"], "counts")
    for df in (s, g, r):
        if set(df.reference) != {c["reference"]}:
            raise ValueError("Reference version conflict")
    for df, cols in [(g, ["tss"]), (r, ["start", "end"]), (sites, ["start", "end"]), (links, ["weight"])]:
        numeric(df, cols)
    numeric(sites, ["score"], nonnegative=False)
    if not set(r.kind) <= {"promoter", "enhancer"}:
        raise ValueError("Unknown region kind")
    if (r.end <= r.start).any() or (sites.end <= sites.start).any():
        raise ValueError("Invalid half-open genomic intervals")
    for df, cols in ((r, ["start", "end"]), (sites, ["start", "end"]), (g, ["tss"])):
        if any(not np.allclose(df[x], np.round(df[x])) for x in cols):
            raise ValueError("Coordinates must be integers")
    if not set(links.gene_id) <= set(g.gene_id) or not set(links.region_id) <= set(r[r.kind.eq("enhancer")].region_id):
        raise ValueError("Links contain unknown genes or non-enhancer regions")
    if not set(r[r.kind.eq("promoter")].gene_id) <= set(g.gene_id):
        raise ValueError("Promoter has unknown gene")
    if not set(sites.region_id) <= set(r.region_id):
        raise ValueError("Site region absent")
    joined = sites.merge(r, on="region_id", suffixes=("_site", "_region"))
    if ((joined.chrom_site != joined.chrom_region) | (joined.start_site < joined.start_region) |
        (joined.end_site > joined.end_region)).any():
        raise ValueError("Motif site is not inside declared region")
    if sites.duplicated(["motif_id", "chrom", "start", "end", "strand", "region_id"]).any():
        raise ValueError("Duplicate motif hits")
    # Enhancer windows must be disjoint from ALL promoter windows, not just target's.
    for chrom, ee in r[r.kind.eq("enhancer")].groupby("chrom"):
        pp = r[(r.chrom == chrom) & r.kind.eq("promoter")].sort_values("start")
        ends = np.maximum.accumulate(pp.end.to_numpy())
        starts = pp.start.to_numpy()
        for e in ee.itertuples():
            i = np.searchsorted(starts, e.end, side="left") - 1
            if i >= 0 and ends[i] > e.start:
                raise ValueError("Enhancer overlaps a promoter; subtract first")
    if not set(s.role) <= {"build", "control", "perturb"}:
        raise ValueError("Unknown sample role")
    if not set(s.modality) <= {"RNA", "ATAC", "multiome"}:
        raise ValueError("Unknown modality")
    if not set(s.included.astype(str)) <= {"1", "0"}:
        raise ValueError("included must be 0 or 1")
    active = s[s.included.astype(str).eq("1")]
    if (active[active.role.isin(["build", "control"])].target != "NTC").any():
        raise ValueError("Build/control samples must have target NTC")
    if active.condition.nunique() != 1 or active.cell_type.nunique() != 1:
        raise ValueError("One run must contain exactly one condition and cell type")
    build = active[active.role.eq("build")]
    if build.empty or (~build.modality.isin(["ATAC", "multiome"])).any():
        raise ValueError("No declared unperturbed ATAC build samples")
    evaluation = active[active.role.isin(["control", "perturb"])]
    if evaluation.empty or (~evaluation.modality.isin(["RNA", "multiome"])).any():
        raise ValueError("No RNA evaluation samples")
    if set(counts.columns) != {"gene_id"} | set(evaluation.sample_id):
        raise ValueError("Count columns must exactly equal included evaluation sample IDs")
    if not set(g.gene_id) <= set(counts.gene_id):
        raise ValueError("Count rows missing required genes")
    for col in counts.columns[1:]:
        numeric(counts, [col])
        if not np.allclose(counts[col], np.round(counts[col])):
            raise ValueError("Counts must be integers, not normalized expression")
    # Required receipt binds imported links to actual unperturbed input membership.
    with open(c["inputs"]["link_provenance"], encoding="utf-8") as f:
        provenance = json.load(f)
    if set(provenance["build_sample_ids"]) != set(build.sample_id):
        raise ValueError("Link build membership differs from declared build samples")
    if provenance.get("links_sha256") != sha256(c["inputs"]["links"]):
        raise ValueError("Links changed since provenance was recorded")
    if provenance.get("reference") != c["reference"]:
        raise ValueError("Link reference mismatch")
    heldout = c.get("heldout_donor")
    if heldout and heldout in set(build.donor):
        raise ValueError("Held-out donor entered link construction")
    if heldout and (provenance.get("heldout_donor") != heldout or heldout in provenance.get("donors", [])):
        raise ValueError("Held-out donor lacks matching fragment rebuild receipt")
    if not provenance.get("source_files"):
        raise ValueError("Missing original link source evidence")
    tables["provenance"] = provenance
    return tables
