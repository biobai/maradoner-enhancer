"""Resumable downloads with identity-aware range requests and checksum manifests."""
import json
import os
import time
import urllib.request
from pathlib import Path
from .io import sha256, write_json, read_table, require


def download(url, destination, expected_sha256=None, retries=3):
    dst = Path(destination)
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + ".part")
    state = dst.with_name(dst.name + ".part.json")
    if dst.exists():
        digest = sha256(dst)
        if expected_sha256 and digest == expected_sha256:
            return {"path": str(dst), "sha256": digest, "verified_expected": True, "url": url}
        # Without a trusted expected checksum, a previous receipt must match.
        receipt = dst.with_name(dst.name + ".receipt.json")
        if not expected_sha256 and receipt.exists():
            old = json.loads(receipt.read_text())
            if old.get("url") == url and old.get("sha256") == digest:
                return old
    for attempt in range(retries):
        try:
            old = json.loads(state.read_text()) if state.exists() else {}
            offset = part.stat().st_size if part.exists() else 0
            headers = {"User-Agent": "maradoner-enhancer/0.1", "Accept-Encoding": "identity"}
            if offset and old.get("url") == url and old.get("validator"):
                headers.update({"Range": f"bytes={offset}-", "If-Range": old["validator"]})
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as resp:
                append = resp.status == 206 and "Range" in headers
                if append and not resp.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                    raise ValueError("Invalid Content-Range; refusing corrupt resume")
                validator = resp.headers.get("ETag") or resp.headers.get("Last-Modified")
                write_json({"url": url, "validator": validator}, state)
                expected = resp.headers.get("Content-Length")
                transferred = 0
                with part.open("ab" if append else "wb") as f:
                    for block in iter(lambda: resp.read(1024**2), b""):
                        f.write(block)
                        transferred += len(block)
                if expected and transferred != int(expected):
                    raise IOError("Truncated download")
            digest = sha256(part)
            if expected_sha256 and digest != expected_sha256:
                part.unlink(missing_ok=True)
                raise ValueError(f"Checksum mismatch for {url}")
            os.replace(part, dst)
            state.unlink(missing_ok=True)
            result = {"url": url, "path": str(dst), "bytes": dst.stat().st_size,
                      "sha256": digest, "verified_expected": bool(expected_sha256)}
            write_json(result, str(dst) + ".receipt.json")
            return result
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(min(2**attempt, 8))


def download_manifest(manifest, directory):
    df = read_table(manifest)
    require(df, ["id", "url", "filename", "source", "version"], ["id"])
    root = Path(directory).resolve()
    receipts = []
    for r in df.to_dict("records"):
        dst = (root / r["filename"]).resolve()
        if not dst.is_relative_to(root):
            raise ValueError("Manifest filename escapes data directory")
        receipts.append(download(r["url"], dst, r.get("sha256") or None))
    write_json(receipts, root / "download_manifest.json")

