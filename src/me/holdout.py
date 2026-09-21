"""Train-only parameter estimation without invoking upstream's leaking split.

Outcome is test-row-centered expression variation, NOT unseen absolute expression.
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from .io import write_table, write_json, sha256
from .model import fit_activity


def train_and_predict(expression_train, B_train, B_test, groups, work, settings, root):
    """No test expression argument: test outcomes cannot reach parameter estimation."""
    a = fit_activity(expression_train, B_train, groups, Path(work) / "fit", settings, root)
    residual = expression_train.to_numpy() - B_train.to_numpy() @ a.to_numpy()
    sample_offset = residual.mean(axis=0)
    pred = B_test.to_numpy() @ a.to_numpy() + sample_offset[None, :]
    return pd.DataFrame(pred, index=B_test.index, columns=expression_train.columns)


def score_centered(test_expression, predictions):
    if not test_expression.index.equals(predictions.index) or not test_expression.columns.equals(predictions.columns):
        raise ValueError("Holdout axes differ")
    y = test_expression.to_numpy()
    y = y - y.mean(axis=1, keepdims=True)
    p = predictions.to_numpy()
    p = p - p.mean(axis=1, keepdims=True)
    denominator = float(np.sum(y*y))
    if denominator <= 0:
        raise ValueError("No between-sample expression variation in test genes")
    return 1.0 - float(np.sum((y-p)**2)) / denominator


def run_holdout(expression_file, loadings_file, test_genes_file, groups_file, settings, root, output):
    """Consumes frozen log-expression and loading files; never calls upstream gof.

    Library normalization has already happened upstream. Guarantee is conditional on
    these fixed inputs, not independence of raw-count library-size factors.
    """
    y = pd.read_csv(expression_file, sep="\t", index_col=0)
    b = pd.read_csv(loadings_file, sep="\t", index_col=0).loc[y.index]
    test = set(Path(test_genes_file).read_text().splitlines())
    if not test or not test < set(y.index):
        raise ValueError("Holdout must be a nonempty proper subset of expression genes")
    if not np.isfinite(y.to_numpy()).all() or not np.isfinite(b.to_numpy()).all():
        raise ValueError("Nonfinite input")
    train = sorted(set(y.index)-test); test = sorted(test)
    constant = b.loc[train].std(axis=0).le(1e-12)
    if constant.any():
        raise ValueError("Training loading has constant columns; freeze a common fold universe across arms first")
    groups = json.loads(Path(groups_file).read_text())
    output = Path(output)
    pred = train_and_predict(y.loc[train], b.loc[train], b.loc[test], groups, output, settings, root)
    metric = score_centered(y.loc[test], pred)
    write_table(pred.rename_axis("gene_id").reset_index(), output / "test_predictions.tsv")
    result = {"metric": "train_only_fit_test_row_centered_dynamic_FOV", "value": metric,
              "n_train_genes": len(train), "n_test_genes": len(test),
              "test_mean_used_only_in_scoring": True, "normalization_scope": "conditional_on_frozen_log_expression",
              "absolute_unseen_expression_prediction": False, "backend": settings["backend"],
              "inputs": {str(p): sha256(p) for p in [expression_file, loadings_file, test_genes_file, groups_file]}}
    write_json(result, output / "holdout_metric.json")
    return result
