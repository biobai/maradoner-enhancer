from __future__ import annotations
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
import numpy as np
import pandas as pd
import yaml


def software_root(project_root):
    """Immutable image software location, or project-local development installation."""
    return Path(os.environ.get("ME_SOFTWARE_ROOT", project_root)).resolve()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 * 1024**2), b""):
            h.update(block)
    return h.hexdigest()


def read_table(path):
    p = Path(path)
    if p.suffix == ".parquet":
        return pd.read_parquet(p)
    return pd.read_csv(p, sep="\t", keep_default_na=False)


def write_table(df, path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".partial")
    if p.suffix == ".parquet":
        df.to_parquet(tmp, index=False)
    else:
        df.to_csv(tmp, sep="\t", index=False)
    os.replace(tmp, p)


def write_json(data, path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".partial")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(tmp, p)


def require(df, columns, unique=None, name="table"):
    missing = set(columns) - set(df.columns)
    if missing:
        raise ValueError(f"{name}: missing columns {sorted(missing)}")
    for c in columns:
        if df[c].isna().any() or df[c].astype(str).str.strip().eq("").any():
            raise ValueError(f"{name}: missing/empty {c}")
    if unique and df.duplicated(unique).any():
        raise ValueError(f"{name}: duplicate IDs {unique}")


def numeric(df, columns, nonnegative=True):
    for c in columns:
        df[c] = pd.to_numeric(df[c], errors="raise")
        v = df[c].to_numpy(float)
        if not np.isfinite(v).all() or (nonnegative and (v < 0).any()):
            raise ValueError(f"invalid values in {c}")


def config(path):
    path = Path(path).resolve()
    c = yaml.safe_load(path.read_text(encoding="utf-8"))
    # root is relative to the config file, all other paths relative to root.
    root = (path.parent / c.get("root", "..")).resolve()
    c["_root"] = str(root)
    c["_config"] = str(path)
    for key in ("inputs", "references"):
        for k, v in c.get(key, {}).items():
            if v:
                c[key][k] = str((root / v).resolve())
    c["output"] = str((root / c["output"]).resolve())
    for k in ("python", "repository"):
        if c.get("maradoner", {}).get(k):
            c["maradoner"][k] = str((root / c["maradoner"][k]).resolve())
    if os.environ.get("ME_SOFTWARE_ROOT") and c.get("maradoner", {}).get("backend") == "maradoner":
        installed = software_root(root)
        c["maradoner"]["python"] = str(installed / ".runtime/envs/maradoner/bin/python")
        c["maradoner"]["repository"] = str(installed / ".tools/MARADONER")
    return c


def run(command, log, cwd=None, timeout=86400, stdout_path=None, env=None):
    """No shell interpolation. Always persist command, exit status and stderr."""
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    record = {"argv": list(map(str, command)), "cwd": str(cwd) if cwd else None,
              "started": time.time(), "status": "running"}
    write_json(record, str(log) + ".json")
    try:
        import contextlib
        with contextlib.ExitStack() as stack:
            stream = stack.enter_context(log.open("w", encoding="utf-8"))
            output = stack.enter_context(Path(stdout_path).open("w", encoding="utf-8")) if stdout_path else stream
            proc = subprocess.run(record["argv"], cwd=cwd, stdout=output,
                                  stderr=stream if stdout_path else subprocess.STDOUT, timeout=timeout, check=False, env=env)
        record["exit_code"] = proc.returncode
        if proc.returncode:
            raise RuntimeError(f"External command exited {proc.returncode}; see {log}")
        record["status"] = "success"
    except Exception as e:
        record.update(status="failed", error=str(e))
        raise
    finally:
        record["finished"] = time.time()
        write_json(record, str(log) + ".json")
