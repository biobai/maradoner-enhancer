"""Fetch pinned MARADONER source, with an official archive fallback."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile

COMMIT = 'd01f9140bfee69d91e8e1fd3eac1e923e308d9a5'
URL = f'https://codeload.github.com/autosome-ru/MARADONER/zip/{COMMIT}'


def digest(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def valid_existing(destination):
    receipt = destination / '.source_revision.json'
    if receipt.exists():
        data = json.loads(receipt.read_text())
        if data.get('commit') != COMMIT or not data.get('files'):
            raise ValueError('Existing source receipt has an unexpected revision or no hashes')
        for name, expected in data['files'].items():
            path = (destination / name).resolve()
            if not path.is_relative_to(destination.resolve()) or digest(path) != expected:
                raise ValueError(f'Existing source changed: {name}')
        return True
    if (destination / '.git').exists():
        sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=destination, text=True).strip()
        dirty = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=destination, text=True).strip()
        if dirty:
            raise ValueError('Existing Git checkout has tracked changes; preserve them before retrying')
        if sha != COMMIT:
            # Resume a clone that completed before bootstrap could pin its revision.
            exists = subprocess.run(['git', 'cat-file', '-e', COMMIT+'^{commit}'], cwd=destination,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if exists.returncode:
                subprocess.run(['git', 'fetch', 'origin', COMMIT], cwd=destination, check=True)
            subprocess.run(['git', 'checkout', '--detach', COMMIT], cwd=destination, check=True)
        return True
    return False


def extract_archive(archive, destination):
    with zipfile.ZipFile(archive) as z:
        prefix = f'MARADONER-{COMMIT}/'
        for entry in z.infolist():
            path = (destination / entry.filename).resolve()
            mode = entry.external_attr >> 16
            if not entry.filename.startswith(prefix) or not path.is_relative_to(destination.resolve()) or (mode & 0o170000) == 0o120000:
                raise ValueError('Unexpected or unsafe archive member')
        z.extractall(destination)
    source = destination / f'MARADONER-{COMMIT}'
    if not (source / 'setup.py').is_file() or not (source / 'maradoner/create.py').is_file():
        raise ValueError('Archive lacks required MARADONER source files')
    if (source / '.gitmodules').exists() and (source / '.gitmodules').read_text().strip():
        raise ValueError('Archive requires submodules; cannot use incomplete source')
    receipt = {'commit': COMMIT, 'url': URL, 'archive_sha256': digest(archive),
               'files': {str(p.relative_to(source)).replace('\\', '/'): digest(p)
                         for p in sorted(source.rglob('*')) if p.is_file()}}
    (source / '.source_revision.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return source


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--destination', required=True)
    p.add_argument('--archive', help='Official pinned-commit ZIP downloaded on another machine')
    args = p.parse_args()
    dest = Path(args.destination).resolve()
    if valid_existing(dest):
        print('Verified existing pinned MARADONER source; no network access needed.')
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    # An incomplete previous clone is preserved, never recursively deleted.
    if dest.exists():
        backup = dest.with_name(dest.name + '.incomplete.' + str(time.time_ns()))
        dest.rename(backup)
        print(f'Preserved incomplete download at {backup}', flush=True)
    with tempfile.TemporaryDirectory(prefix='maradoner-download-', dir=dest.parent) as temp:
        work = Path(temp)
        archive = Path(args.archive).resolve() if args.archive else work / 'source.zip'
        if not args.archive:
            error = None
            for attempt in range(3):
                try:
                    print(f'Downloading official commit archive (attempt {attempt+1}/3): {URL}', flush=True)
                    request = urllib.request.Request(URL, headers={'User-Agent': 'maradoner-enhancer-bootstrap'})
                    with urllib.request.urlopen(request, timeout=45) as response, archive.open('wb') as out:
                        shutil.copyfileobj(response, out)
                    with zipfile.ZipFile(archive) as z:
                        if z.testzip() is not None:
                            raise ValueError('Archive CRC verification failed')
                    error = None
                    break
                except Exception as e:
                    error = e
                    print(f'Download failed: {e}', flush=True)
                    if attempt < 2:
                        time.sleep(2 * (attempt + 1))
            if error:
                raise RuntimeError(f'Official archive unavailable. Download {URL} on another machine, upload the ZIP, then set MARADONER_ARCHIVE=/absolute/path/source.zip when rerunning bootstrap.') from error
        source = extract_archive(archive, work / 'extracted')
        source.rename(dest)
    print(f'Installed pinned source at {dest}; archive and source hashes recorded.')


if __name__ == '__main__':
    main()
