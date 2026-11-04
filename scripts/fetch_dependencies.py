"""Download the recorded dependency versions and verify their SHA-256 hashes."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import urllib.request


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=root / 'dependencies/jars')
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root / 'dependencies/manifest.json').read_text())
    for row in manifest['files']:
        target = args.output / row['name']
        if target.is_file():
            if sha(target) != row['sha256']:
                raise ValueError('Existing dependency has the wrong hash: ' + target.name)
            print('Verified', target.name)
            continue
        temporary = target.with_suffix(target.suffix + '.download')
        try:
            request = urllib.request.Request(row['url'], headers={'User-Agent': 'PDMM-reproduction'})
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open('wb') as out:
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
            if temporary.stat().st_size != row['size'] or sha(temporary) != row['sha256']:
                raise ValueError('Dependency checksum mismatch: ' + target.name)
            os.replace(temporary, target)
            print('Downloaded and verified', target.name)
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
