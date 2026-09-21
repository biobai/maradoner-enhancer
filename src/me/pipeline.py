from __future__ import annotations
import contextlib
import hashlib
import html
import json
import os
import platform
import shutil
import time
from pathlib import Path
import numpy as np
import pandas as pd
from . import __version__
from .io import read_table, write_table, write_json, sha256
from .validate import load_inputs
from .matrices import build_matrices, distance_links, permute_links, scale_arms, normalize_counts
from .model import fit_activity
from .benchmark import family_scores, target_rank, cross_bootstrap, pseudo_target_null

STAGES = ("validate", "features", "fit", "evaluate", "report")


def validate(c, out):
    tables = load_inputs(c)
    counts = tables["counts"]
    # MARADONER is dense internally: fail before accidental full matrix allocations.
    g = len(tables["genes"])
    m = tables["mapping"].motif_id.nunique()
    estimate = 8 * (g*m*8 + m*m*10 + g*len(counts.columns)*4)
    if estimate > c["resources"]["memory_gb"] * 1024**3:
        raise ValueError(f"Dense working-set estimate {estimate/1024**3:.1f} GiB exceeds configured memory budget")
    write_json({"n_genes": g, "n_motifs": m, "n_samples": len(counts.columns)-1,
                "dense_estimate_gb": estimate/1024**3, "reference": c["reference"],
                "backend": c["maradoner"]["backend"], "counts_are_raw": True}, out / "qc.json")


def features(c, out):
    t = load_inputs(c)
    g, r, ss, links, mm = (t[k] for k in ["genes", "regions", "sites", "links", "mapping"])
    # One physical sequence cannot contribute twice via overlapping enhancer regions.
    e = r[r.kind.eq("enhancer")]
    for _, rr in e.groupby("chrom"):
        rr = rr.sort_values("start")
        if len(rr) > 1 and (rr.start.to_numpy()[1:] < np.maximum.accumulate(rr.end.to_numpy())[:-1]).any():
            raise ValueError("Overlapping enhancer regions: merge peaks before scanning/linking")
    candidates = distance_links(g, r, c["analysis"]["cis_window"], c["analysis"]["distance_power"])
    l = links.merge(candidates[["region_id", "gene_id", "distance"]], on=["region_id", "gene_id"], how="left", validate="one_to_one")
    if l.distance.isna().any():
        raise ValueError("scE2G link outside common cis candidate universe")
    variants = {"sce2g": l, "distance": candidates}
    for seed in c["analysis"]["permutation_seeds"]:
        variants[f"permuted_{seed}"] = permute_links(l, candidates, c["analysis"]["distance_bins"], seed)
    ids, motifs, P, _ = build_matrices(g, r, ss, l, mm.motif_id)
    raw_P = P.copy()
    H = {name: build_matrices(g, r, ss, ll, motifs)[3] for name, ll in variants.items()}
    # RNA-independent structural selection, but assess all predeclared target deletion masks.
    targets = sorted(set(t["samples"].loc[t["samples"].role.eq("perturb"), "target"]))
    keep, arms, scaling = scale_arms(P, H, c["analysis"]["alpha_factors"])
    valid = keep.copy()
    for target in targets:
        rows = np.asarray(ids) != target
        for b in arms.values():
            valid[np.flatnonzero(keep)] &= b[rows].std(axis=0) > 1e-12
    # Recompute all alphas after the common exclusion, then verify every deletion again.
    if not np.array_equal(valid, keep):
        P[:, ~valid] = 0
        keep, arms, scaling = scale_arms(P, H, c["analysis"]["alpha_factors"])
    retained = list(np.asarray(motifs)[keep])
    for target in targets:
        for b in arms.values():
            if (b[np.asarray(ids) != target].std(axis=0) <= 1e-12).any():
                raise ValueError("Target deletion causes degenerate motif; revise frozen universe before fitting")
    for name, b in arms.items():
        write_table(pd.DataFrame(b, index=ids, columns=retained).rename_axis("gene_id").reset_index(), out / f"B_{name}.parquet")
    write_table(pd.DataFrame(raw_P, index=ids, columns=motifs).rename_axis("gene_id").reset_index(), out / "P_raw.parquet")
    for name, h in H.items():
        write_table(pd.DataFrame(h, index=ids, columns=motifs).rename_axis("gene_id").reset_index(), out / f"H_{name}.parquet")
        write_table(variants[name], out / f"links_{name}.parquet")
    write_json(scaling, out / "scaling.json")
    write_json({"models": list(arms), "genes": ids, "motifs": retained}, out / "universe.json")
    write_table(pd.DataFrame({"motif_id": motifs, "included": keep.astype(int),
        "reason": ["common_nonconstant" if x else "constant_or_target_deletion_degenerate" for x in keep]}), out / "feature_audit.tsv")


def fit(c, out):
    t = load_inputs(c)
    fdir = Path(c["output"]) / "features"
    universe = json.loads((fdir / "universe.json").read_text())
    genes, motifs = universe["genes"], universe["motifs"]
    counts = t["counts"].set_index("gene_id")
    # Compute library-size denominators before gene restriction or target masking.
    norm = pd.DataFrame(normalize_counts(counts.to_numpy()), index=counts.index, columns=counts.columns)
    samples = t["samples"]
    samples = samples[samples.included.astype(str).eq("1") & samples.role.isin(["control", "perturb"])].copy()
    rows, contrasts, excluded, pairing = [], [], [], []
    for target in sorted(samples.loc[samples.role.eq("perturb"), "target"].unique()):
        families = set(t["mapping"].loc[t["mapping"].tf_id.eq(target) & t["mapping"].motif_id.isin(motifs), "family_id"])
        if not families:
            excluded.append({"target": target, "reason": "no_mapped_retained_motif"}); continue
        if target not in counts.index or ";" in target or "," in target:
            excluded.append({"target": target, "reason": "target_gene_absent_or_not_single_TF"}); continue
        subset = samples[samples.target.eq(target) | samples.role.eq("control")]
        selected = []
        for (donor, batch), group in subset.groupby(["donor", "batch"], sort=True):
            ko = group[group.role.eq("perturb")]
            nt = group[group.role.eq("control")]
            if ko.empty or nt.empty:
                if not ko.empty:
                    excluded.append({"target": target, "reason": f"no_paired_NTC:{donor}:{batch}"})
                continue
            selected.extend(group.sample_id)
            pairing.append({"target": target, "donor": donor, "batch": batch,
                            "unit": f"{donor}|{batch}", "condition": group.condition.iloc[0],
                            "ko": list(ko.sample_id), "nt": list(nt.sample_id), "families": sorted(families)})
        if not selected:
            continue
        subset = subset.set_index("sample_id").loc[sorted(selected)]
        if len(selected) < c["analysis"]["min_expression_samples"]:
            raise ValueError(f"{target}: only {len(selected)} expression samples; cannot fit planned model")
        gids = [x for x in genes if x != target]
        expression = norm.loc[gids, sorted(selected)]
        groups = {"KO": sorted(subset.index[subset.role.eq("perturb")]), "NT": sorted(subset.index[subset.role.eq("control")])}
        safe = hashlib.sha256(target.encode()).hexdigest()[:16]
        for model in universe["models"]:
            b = read_table(fdir / f"B_{model}.parquet").set_index("gene_id").loc[gids, motifs]
            w = out / "models" / safe / model
            a = fit_activity(expression, b, groups, w, c["maradoner"], c["_root"])
            long = a.rename_axis("motif_id").reset_index().melt(id_vars="motif_id", var_name="sample_id", value_name="activity")
            long["model"], long["target_context"] = model, target
            long["posterior_sd"] = np.nan
            long["uncertainty_scope"] = "sample_SD_unavailable;see_group_posterior_sd"
            rows.append(long)
            z = read_table(w / "contrast.tsv")
            z["model"], z["target"] = model, target
            z["scope"] = "group_model_conditional_not_donor_replicate"
            contrasts.append(z)
    if not rows:
        raise ValueError("No evaluable TF perturbations; inspect mapping and paired controls")
    write_table(pd.concat(rows, ignore_index=True), out / "activities.parquet")
    write_table(pd.concat(contrasts, ignore_index=True), out / "group_contrasts.tsv")
    write_table(pd.DataFrame(excluded, columns=["target", "reason"]), out / "exclusions.tsv")
    write_json(pairing, out / "pairing.json")
    all_targets = set(samples.loc[samples.role.eq("perturb"), "target"])
    evaluated = {p["target"] for p in pairing}
    write_json({"n_input_targets": len(all_targets), "n_evaluated_targets": len(evaluated),
                "target_coverage": len(evaluated)/len(all_targets), "evaluated_targets": sorted(evaluated),
                "n_paired_units": len(pairing)}, out / "coverage.json")


def evaluate(c, out):
    odir = Path(c["output"])
    a = read_table(odir / "fit/activities.parquet")
    mapping = read_table(c["inputs"]["mapping"])
    pairs = json.loads((odir / "fit/pairing.json").read_text())
    records, nulls = [], []
    for p in pairs:
        for model, x in a[a.target_context.eq(p["target"])].groupby("model", sort=True):
            x = x.pivot(index="motif_id", columns="sample_id", values="activity")
            delta = x[p["ko"]].mean(axis=1) - x[p["nt"]].mean(axis=1)
            for aggregation in ("max", "mean_rank"):
                scores = family_scores(delta, mapping, aggregation)
                base = {k: p[k] for k in ["target", "donor", "condition", "unit"]}
                base.update(model=model, aggregation=aggregation)
                base.update(target_rank(scores, p["families"]))
                records.append(base)
            if len(p["nt"]) >= 2:
                nt = sorted(p["nt"])
                cut = len(nt)//2
                d = x[nt[:cut]].mean(axis=1) - x[nt[cut:]].mean(axis=1)
                nulls.append({"model": model, "target_context": p["target"], "unit": p["unit"],
                              "kind": "NTC_effect", "mean_abs_delta": float(d.abs().mean()), "status": "computed"})
            else:
                nulls.append({"model": model, "target_context": p["target"], "unit": p["unit"],
                              "kind": "NTC_effect", "status": "insufficient_independent_NTC;provide_split_NTC_input"})
            nulls.append({"model": model, "target_context": p["target"], "unit": p["unit"],
                          "kind": "ranking_null", **pseudo_target_null(family_scores(delta, mapping),
                          len(set(p["families"])), seed=c["analysis"]["seed"])})
    metrics = pd.DataFrame(records)
    primary = metrics[metrics.aggregation.eq("max")]
    intervals = [cross_bootstrap(primary, m, repeats=c["analysis"]["bootstrap_repeats"], seed=c["analysis"]["seed"])
                 for m in sorted(set(primary.model)-{"promoter"})]
    write_table(metrics, out / "benchmark_metrics.tsv")
    write_table(pd.DataFrame(intervals), out / "paired_differences.tsv")
    write_table(pd.DataFrame(nulls), out / "null_calibration.tsv")
    # Equal family and condition weights; guide counts never define biological n.
    summary = primary.groupby(["model", "condition", "target_families", "donor"], as_index=False)[["mrr", "top5"]].mean()
    summary = summary.groupby(["model", "condition", "target_families"], as_index=False)[["mrr", "top5"]].mean()
    summary = summary.groupby(["model", "condition"], as_index=False)[["mrr", "top5"]].mean()
    write_table(summary, out / "condition_summary.tsv")
    gz = read_table(odir / "fit/group_contrasts.tsv")
    zz = []
    for (model, target), group in gz.groupby(["model", "target"]):
        values = pd.to_numeric(group.set_index("motif_id").z, errors="coerce")
        if not np.isfinite(values).all():
            continue
        fam = mapping.loc[mapping.tf_id.eq(target), "family_id"]
        zz.append({"model": model, "target": target, "scope": "group_Z_secondary", **target_rank(family_scores(values, mapping), fam)})
    write_table(pd.DataFrame(zz, columns=["model", "target", "scope", "rank", "mrr", "top5", "n_families", "target_families", "n_acceptable_families"]), out / "group_z_metrics.tsv")


def report(c, out):
    t = load_inputs(c)
    regions, sites, links = (t[k] for k in ("regions", "sites", "links"))
    tfmap = t["mapping"].groupby("motif_id").tf_id.apply(lambda x: ";".join(sorted(set(x)))).rename("candidate_tfs")
    base = sites.merge(regions, on="region_id", suffixes=("", "_region")).merge(tfmap, on="motif_id", how="left")
    prom = base[base.kind.eq("promoter")].copy()
    prom["link_weight"], prom["link_source"] = np.nan, "promoter_annotation"
    enh = base[base.kind.eq("enhancer")].drop(columns="gene_id").merge(
        links.rename(columns={"weight": "link_weight", "source": "link_source"}), on="region_id")
    edges = pd.concat([prom, enh], ignore_index=True)
    edges["evidence_type"], edges["causal_label"] = "sequence_and_link_candidate", "unassigned"
    edges["motif_source_sha256"] = sha256(c["inputs"]["sites"])
    edges["link_source_sha256"] = sha256(c["inputs"]["links"])
    write_table(edges, out / "candidate_edges.parquet")
    for name, key in [("samples.tsv", "samples"), ("enhancer_links.parquet", "links"), ("motif_sites.parquet", "sites")]:
        write_table(t[key], out / name)
    root = Path(c["output"])
    copies = {"fit": ["activities.parquet", "exclusions.tsv", "group_contrasts.tsv", "coverage.json"],
              "evaluate": ["benchmark_metrics.tsv", "paired_differences.tsv", "null_calibration.tsv", "condition_summary.tsv", "group_z_metrics.tsv"],
              "features": ["feature_audit.tsv", "scaling.json"]}
    for folder, names in copies.items():
        for name in names:
            shutil.copyfile(root / folder / name, out / name)
    synthetic = c.get("synthetic", False) or c["maradoner"]["backend"] != "maradoner"
    summary = read_table(out / "condition_summary.tsv")
    bars = []
    for i, row in enumerate(summary.itertuples()):
        y = 35 + i * 30
        label = html.escape(str(row.model))
        bars.append(f'<text x="5" y="{y+15}" font-size="12">{label}</text><rect x="220" y="{y}" width="{float(row.mrr)*500:.2f}" height="20" fill="#287a91"/><text x="{225+float(row.mrr)*500:.2f}" y="{y+15}" font-size="12">{float(row.mrr):.3f}</text>')
    (out / "family_mrr.svg").write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="{65+30*len(summary)}"><rect width="100%" height="100%" fill="white"/><text x="220" y="20">Family MRR (0–1); descriptive</text>{"".join(bars)}</svg>', encoding="utf-8")
    status = "SYNTHETIC_DIAGNOSTIC_ONLY" if synthetic else "PERTURBATION_EVALUATION_COMPLETED_REQUIRES_INTERPRETATION"
    write_table(pd.DataFrame([{"metric": "strict_holdout_FOV", "status": "disabled_upstream_leakage_not_repaired", "value": np.nan}]), out / "expression_metrics.tsv")
    report_html = f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>MARADONER enhancer report</title>
<style>body{{max-width:1100px;margin:40px auto;font:16px system-ui}}table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:8px}}.warning{{background:#fff2cc;padding:16px}}</style>
<h1>增强子整合研究报告</h1><p class="warning">{html.escape(status)}</p>
<p>合成诊断不构成真实软件或科学有效性证据。完成计算不等于证明改善。主指标为家族 MRR；各输入和运行版本见运行清单。</p>
<p>严格留出 FOV 已禁用：所固定上游版本拟合参数使用全体基因。没有用内部 FOV 宣称泛化。</p>
<h2>条件分层结果</h2>{summary.to_html(index=False, escape=True)}
<img src="family_mrr.svg" alt="Family MRR descriptive chart" style="max-width:100%">
<h2>限制</h2><p>同研究对照建网与留出扰动不是外部复制。小供体/家族区间仅描述；缺少NTC重复会在null_calibration.tsv中标记。网络边没有直接因果或激活/抑制标签。</p>
<p><a href="paired_differences.tsv">配对差异</a> · <a href="null_calibration.tsv">零假设校准</a> · <a href="feature_audit.tsv">特征覆盖</a> · <a href="exclusions.tsv">排除记录</a></p></html>'''
    (out / "report.html").write_text(report_html, encoding="utf-8")
    write_json({"status": status, "scientific_claim": "not_automatically_assigned", "strict_FOV": "disabled"}, out / "scientific_status.json")


def fingerprint(c):
    inputs = {k: sha256(v) for k, v in c["inputs"].items() if v}
    source = Path(__file__).parent
    code = {str(p.relative_to(source)): sha256(p) for p in sorted(source.glob("*.py"))}
    code["maradoner_bridge.py"] = sha256(Path(c["_root"]) / "scripts/maradoner_bridge.py")
    import importlib.metadata
    versions = {k: importlib.metadata.version(k) for k in ("numpy", "pandas", "scipy", "pyarrow", "pyyaml")}
    if c["maradoner"]["backend"] == "maradoner":
        import subprocess
        versions["isolated_environment"] = subprocess.check_output([c["maradoner"]["python"], "-c",
            "import importlib.metadata as m,json; print(json.dumps(sorted((d.metadata['Name'],d.version) for d in m.distributions())))"], text=True).strip()
        repo = Path(c["maradoner"]["repository"])
        code.update({"upstream/"+str(p.relative_to(repo)): sha256(p) for p in sorted((repo / "maradoner").rglob("*.py"))})
    return hashlib.sha256(json.dumps({"config": c, "inputs": inputs, "code": code, "versions": versions}, sort_keys=True).encode()).hexdigest(), inputs


def pipeline(c, until="report", dry_run=False, force=False):
    if until not in STAGES:
        raise ValueError("Unknown stage")
    if c["maradoner"]["backend"] != "maradoner" and not c.get("synthetic", False):
        raise ValueError("Diagnostic backend requires explicit synthetic: true")
    root = Path(c["output"])
    if root.resolve() == Path(c["_root"]).resolve():
        raise ValueError("Output must not be project root")
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".run.lock"
    if dry_run:
        return {"stages": list(STAGES[:STAGES.index(until)+1]), "config": c["_config"],
                "missing_inputs": [v for v in c["inputs"].values() if not Path(v).exists()]}
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(f"Run lock exists: {lock}; check PID before manual removal") from None
    os.write(fd, str(os.getpid()).encode()); os.close(fd)
    record = {"started": time.time(), "status": "running", "version": __version__, "platform": platform.platform(), "config": c}
    try:
        key, inputs = fingerprint(c)
        record.update(fingerprint=key, inputs=inputs, stages=[])
        write_json(record, root / "run_manifest.json")
        for stage in STAGES[:STAGES.index(until)+1]:
            dst = root / stage
            stamp = dst / "success.json"
            cached = False
            if not force and stamp.exists():
                previous = json.loads(stamp.read_text())
                cached = previous.get("fingerprint") == key and all((dst/f).exists() and sha256(dst/f) == h for f, h in previous.get("outputs", {}).items())
            if cached:
                record["stages"].append({"stage": stage, "status": "cached"})
                continue
            # Invalidate downstream success declarations before starting the changed stage.
            for future in STAGES[STAGES.index(stage):]:
                (root / future / "success.json").unlink(missing_ok=True)
            (root / "report/report.html").unlink(missing_ok=True)
            temp = root / f".{stage}.running.{os.getpid()}"
            temp.mkdir(exist_ok=False)
            try:
                globals()[stage](c, temp)
                outputs = {str(p.relative_to(temp)): sha256(p) for p in temp.rglob("*") if p.is_file()}
                write_json({"fingerprint": key, "outputs": outputs, "finished": time.time()}, temp / "success.json")
                if dst.exists():
                    # Only tool-owned named stage directory; preserve the previous attempt for audit.
                    old = root / f".{stage}.previous.{time.time_ns()}"
                    dst.rename(old)
                temp.rename(dst)
            except Exception:
                record["failed_stage"] = stage
                record["failure_artifacts"] = str(temp)
                raise
            record["stages"].append({"stage": stage, "status": "success"})
            write_json(record, root / "run_manifest.json")
        record["status"] = "success"
        record["completed_through"] = until
        if until == "report":
            write_json(record, root / "report/run_manifest.json")
    except Exception as e:
        record.update(status="failed", error=str(e))
        (root / "report/report.html").unlink(missing_ok=True)
        (root / "report/success.json").unlink(missing_ok=True)
        if (root / "report").exists():
            write_json({"status": "INVALIDATED_BY_FAILED_RERUN", "error": str(e)}, root / "report/scientific_status.json")
        raise
    finally:
        record["finished"] = time.time()
        write_json(record, root / "run_manifest.json")
        lock.unlink(missing_ok=True)
    return {"status": record["status"], "output": str(root), "completed_through": until}
