from __future__ import annotations
import numpy as np
import pandas as pd
from scipy import sparse
from .io import require, numeric


def build_matrices(genes, regions, sites, links, motif_ids):
    """Only genomic inputs. No expression, target labels or evaluation metadata."""
    gene_ids = sorted(genes.gene_id.astype(str))
    motif_ids = sorted(set(motif_ids))
    rid = sorted(regions.region_id.astype(str))
    gi, mi, ri = ({v: i for i, v in enumerate(ids)} for ids in (gene_ids, motif_ids, rid))
    ss = sites[sites.motif_id.isin(mi)].copy()
    # M is hit count, deliberately not sum of uncalibrated FIMO log-odds scores.
    M = sparse.coo_matrix((np.ones(len(ss)),
        ([ri[x] for x in ss.region_id], [mi[x] for x in ss.motif_id])),
        shape=(len(rid), len(mi))).tocsr()
    prom = regions[regions.kind.eq("promoter")]
    A = sparse.coo_matrix((np.ones(len(prom)),
        ([gi[x] for x in prom.gene_id], [ri[x] for x in prom.region_id])),
        shape=(len(gi), len(ri))).tocsr()
    P = (A @ M).toarray()
    W = sparse.coo_matrix((links.weight.to_numpy(float),
        ([gi[x] for x in links.gene_id], [ri[x] for x in links.region_id])),
        shape=(len(gi), len(ri))).tocsr()
    return gene_ids, motif_ids, P, (W @ M).toarray()


def distance_links(genes, regions, window, power):
    rows = []
    for g in genes.sort_values("gene_id").itertuples():
        rr = regions[(regions.chrom == g.chrom) & regions.kind.eq("enhancer")].copy()
        d = np.abs((rr.start.to_numpy() + rr.end.to_numpy()) / 2 - g.tss)
        for r, dist in zip(rr.itertuples(), d):
            if dist <= window:
                rows.append((r.region_id, g.gene_id, (max(dist, 2000) / 2000)**(-power), dist))
    return pd.DataFrame(rows, columns=["region_id", "gene_id", "weight", "distance"])


def permute_links(links, candidates, bins, seed):
    """Gene-stratified sampling without replacement; preserve weight multiset and bins.

    Identity draws are allowed: removing them would change the defined conditional null.
    """
    rng = np.random.default_rng(seed)
    links = links.sort_values(["gene_id", "region_id"]).copy()
    candidates = candidates.sort_values(["gene_id", "region_id"]).copy()
    links["bin"] = np.searchsorted(bins, links.distance, side="right")
    candidates["bin"] = np.searchsorted(bins, candidates.distance, side="right")
    rows = []
    for (gene, b), group in links.groupby(["gene_id", "bin"], sort=True):
        pool = candidates[(candidates.gene_id == gene) & (candidates.bin == b)]
        if len(pool) < len(group):
            raise ValueError(f"Insufficient permutation candidates: {gene}, bin={b}")
        draw = pool.iloc[rng.choice(len(pool), len(group), replace=False)].copy()
        draw["weight"] = rng.permutation(group.weight.to_numpy())
        rows.append(draw.drop(columns="bin"))
    if not rows:
        return links.drop(columns="bin")
    return pd.concat(rows, ignore_index=True).sort_values(["gene_id", "region_id"])


def scale_arms(P, enhancements, factors=(0.5, 1., 2.), tolerance=1e-12):
    """Structural feature intersection before fitting; alpha has input-norm semantics."""
    keep = np.isfinite(P).all(axis=0) & (P.std(axis=0) > tolerance)
    for H in enhancements.values():
        if H.shape != P.shape or not np.isfinite(H).all() or (H < 0).any():
            raise ValueError("Invalid enhancer matrix")
    if (P < 0).any():
        raise ValueError("Negative motif counts")
    # Intersection may change alpha; converge monotonically on structural exclusions.
    while keep.any():
        scale = np.sqrt(np.mean(P[:, keep]**2, axis=0))
        p = P[:, keep] / scale
        arms, alphas = {"promoter": p}, {}
        valid = np.ones(p.shape[1], dtype=bool)
        for name, H in enhancements.items():
            h = H[:, keep] / scale
            alpha = np.linalg.norm(p) / np.linalg.norm(h) if np.linalg.norm(h) else 0.
            alphas[name] = float(alpha)
            for factor in factors:
                b = p + factor * alpha * h
                arms[f"{name}__{factor:g}"] = b
                valid &= b.std(axis=0) > tolerance
        if valid.all():
            return keep, arms, {"column_scales": scale.tolist(), "alpha": alphas,
                                "factors": list(factors), "transform": "none"}
        keep[np.flatnonzero(keep)[~valid]] = False
    raise ValueError("No common nonconstant motif columns remain")


def normalize_counts(counts, target_sum=1e6):
    x = np.asarray(counts, dtype=float)
    if not np.isfinite(x).all() or (x < 0).any() or not np.allclose(x, np.round(x)):
        raise ValueError("Expression input must be raw nonnegative integer counts")
    depth = x.sum(axis=0)
    if (depth == 0).any():
        raise ValueError("Zero-library sample")
    return np.log1p(x / depth * target_sum)

