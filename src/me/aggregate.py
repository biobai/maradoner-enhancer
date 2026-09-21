from pathlib import Path
import numpy as np
import pandas as pd
from scipy import sparse, io
from .io import require, write_table

GROUP = ["donor", "batch", "condition", "cell_type", "role", "target"]


def aggregate_mtx(matrix, genes, cells, metadata, output, reference):
    """Input MTX = genes x cells, metadata index = stable cell_id; no imputation."""
    x = io.mmread(matrix).tocsr()
    return aggregate(x, genes, cells, metadata, output, reference)


def aggregate(x, genes, cells, metadata, output, reference):
    require(metadata, ["cell_id", *GROUP, "included"], ["cell_id"])
    if len(set(genes)) != len(genes) or len(set(cells)) != len(cells):
        raise ValueError("Duplicate gene/cell IDs")
    if x.shape != (len(genes), len(cells)) or set(cells) != set(metadata.cell_id):
        raise ValueError("Counts and metadata are not aligned")
    vals = x.data if sparse.issparse(x) else np.asarray(x)
    if not np.isfinite(vals).all() or (vals < 0).any() or not np.allclose(vals, np.round(vals)):
        raise ValueError("Raw integer counts required")
    meta = metadata.set_index("cell_id").loc[cells].reset_index()
    keep = meta.included.astype(str).eq("1").to_numpy()
    meta = meta.loc[keep].copy()
    x = sparse.csr_matrix(x)[:, keep]
    keys = sorted(set(map(tuple, meta[GROUP].to_numpy())))
    lookup = {k: i for i, k in enumerate(keys)}
    codes = [lookup[tuple(v)] for v in meta[GROUP].to_numpy()]
    indicator = sparse.coo_matrix((np.ones(len(codes)), (np.arange(len(codes)), codes)), shape=(len(codes), len(keys)))
    pb = x @ indicator
    samples = pd.DataFrame(keys, columns=GROUP)
    samples.insert(0, "sample_id", [f"PB{i:05d}" for i in range(len(keys))])
    samples["n_cells"] = np.bincount(codes, minlength=len(keys))
    samples["modality"], samples["reference"], samples["included"] = "RNA", reference, 1
    counts = pd.DataFrame(pb.toarray(), columns=samples.sample_id, index=genes).astype("int64")
    counts.index.name = "gene_id"
    out = Path(output)
    write_table(counts.reset_index(), out / "counts.tsv")
    write_table(samples, out / "rna_samples.tsv")
    write_table(meta.assign(sample_id=[samples.sample_id.iloc[c] for c in codes]), out / "cell_membership.tsv")
    return counts, samples


def aggregate_h5ad(path, layer, output, reference, chunk=20000):
    import anndata as ad
    a = ad.read_h5ad(path, backed="r")
    if layer != "X":
        raise ValueError("Backed mode requires X to contain raw counts; use R/MTX for other layers")
    require(a.obs.reset_index(names="cell_id"), ["cell_id", *GROUP, "included"], ["cell_id"])
    meta = a.obs.copy()
    if not a.var_names.is_unique or not a.obs_names.is_unique:
        raise ValueError("Duplicate h5ad cell/gene IDs")
    keys = sorted(set(map(tuple, meta.loc[meta.included.astype(str).eq("1"), GROUP].to_numpy())))
    ids = {k: i for i, k in enumerate(keys)}
    acc = np.zeros((a.n_vars, len(keys)), dtype=np.float64)
    for start in range(0, a.n_obs, chunk):
        stop = min(start + chunk, a.n_obs)
        block = sparse.csr_matrix(a.X[start:stop])
        vals = block.data
        if not np.isfinite(vals).all() or (vals < 0).any() or not np.allclose(vals, np.round(vals)):
            raise ValueError("X is not raw counts")
        m = meta.iloc[start:stop]
        rows, cols = [], []
        for i, (_, r) in enumerate(m.iterrows()):
            if str(r.included) == "1":
                rows.append(i); cols.append(ids[tuple(r[GROUP])])
        ind = sparse.coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(stop-start, len(keys)))
        acc += (block.T @ ind).toarray()
    genes = list(a.var_names)
    a.file.close()
    # Feed pseudobulks as cells through the common writer; original membership remains external.
    m = pd.DataFrame(keys, columns=GROUP).assign(cell_id=[f"group{i}" for i in range(len(keys))], included=1)
    counts, samples = aggregate(sparse.csr_matrix(acc), genes, list(m.cell_id), m, output, reference)
    original = meta.reset_index(names="cell_id")
    original = original[original.included.astype(str).eq("1")].copy()
    codes = [ids[tuple(row)] for row in original[GROUP].to_numpy()]
    original["sample_id"] = [samples.sample_id.iloc[i] for i in codes]
    samples["n_cells"] = np.bincount(codes, minlength=len(keys))
    write_table(samples, Path(output) / "rna_samples.tsv")
    write_table(original, Path(output) / "cell_membership.tsv")
    return counts, samples
