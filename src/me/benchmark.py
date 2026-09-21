import numpy as np
import pandas as pd
from scipy.stats import rankdata


def family_scores(delta, mapping, mode="max"):
    mm = mapping[["motif_id", "family_id"]].drop_duplicates()
    mm = mm[mm.motif_id.isin(delta.index)].copy()
    mm["score"] = mm.motif_id.map(delta.abs())
    if mode == "mean_rank":
        # Larger score = higher within-vector activity percentile.
        percentiles = pd.Series(rankdata(delta.abs(), method="average") / len(delta), index=delta.index)
        mm["score"] = mm.motif_id.map(percentiles)
        return mm.groupby("family_id").score.mean()
    return mm.groupby("family_id").score.max()


def target_rank(scores, target_families):
    available = set(scores.index)
    target = set(target_families) & available
    if not target:
        raise ValueError("No evaluable target family")
    # Conservative fixed handling of ties: average rank; all acceptable target families preserved.
    ranks = pd.Series(rankdata(-scores.to_numpy(), method="average"), index=scores.index)
    rank = float(ranks.loc[sorted(target)].min())
    return {"rank": rank, "mrr": 1 / rank, "top5": float(rank <= 5), "n_families": len(scores),
            "target_families": ";".join(sorted(target)), "n_acceptable_families": len(target)}


def cross_bootstrap(metrics, model, baseline="promoter", repeats=1000, seed=17):
    """Crossed resampling by target-family signature and donor; retain pairing.

    Descriptive intervals only when <4 clusters on either axis.
    """
    keys = ["target", "target_families", "donor", "condition", "unit"]
    a = metrics[metrics.model.eq(model)][keys + ["mrr"]]
    b = metrics[metrics.model.eq(baseline)][keys + ["mrr"]]
    df = a.merge(b, on=keys, suffixes=("_a", "_b"), validate="one_to_one")
    if len(df) != len(a) or len(df) != len(b) or df.empty:
        raise ValueError("Incomplete paired benchmark universe")
    df["difference"] = df.mrr_a - df.mrr_b
    df = df.groupby(["target_families", "donor", "condition"], as_index=False).difference.mean()
    families, donors = sorted(df.target_families.unique()), sorted(df.donor.unique())
    rng = np.random.default_rng(seed)
    estimates = []
    def average(fw, dw):
        conditions = []
        for _, cd in df.groupby("condition"):
            values, weights = [], []
            for family, fd in cd.groupby("target_families"):
                w = fd.donor.map(dw).fillna(0).to_numpy(float)
                if w.sum() and fw.get(family, 0):
                    values.append(np.average(fd.difference, weights=w))
                    weights.append(fw[family])
            if weights:
                conditions.append(np.average(values, weights=weights))
        return float(np.mean(conditions)) if conditions else None
    for _ in range(repeats):
        fw = pd.Series(rng.choice(families, len(families))).value_counts()
        dw = pd.Series(rng.choice(donors, len(donors))).value_counts()
        estimate = average(fw, dw)
        if estimate is not None:
            estimates.append(estimate)
    return {"model": model, "baseline": baseline, "difference": average(dict.fromkeys(families, 1), dict.fromkeys(donors, 1)),
            "lo": float(np.quantile(estimates, .025)), "hi": float(np.quantile(estimates, .975)),
            "n_families": len(families), "n_donors": len(donors),
            "interval_scope": "descriptive_small_clusters" if min(len(families), len(donors)) < 4 else "crossed_cluster_bootstrap",
            "successful_draws": len(estimates), "seed": seed}


def pseudo_target_null(scores, target_count=1, repeats=1000, seed=17):
    rng = np.random.default_rng(seed)
    ranks = rankdata(-scores.to_numpy(), method="average")
    rr = [1 / min(ranks[rng.choice(len(ranks), target_count, replace=False)]) for _ in range(repeats)]
    return {"null_mrr_mean": float(np.mean(rr)), "null_mrr_lo": float(np.quantile(rr, .025)),
            "null_mrr_hi": float(np.quantile(rr, .975)), "null_type": "uniform_pseudo_targets_not_effect_calibration"}
