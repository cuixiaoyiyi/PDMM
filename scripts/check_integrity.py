"""Verify the publication manifest and reject credential material in artifact files."""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import re


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=root / 'artifact-manifest.json')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf8'))
    secret = re.compile(rb'(?:gh[pousr]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
    for row in manifest['files']:
        path = (root / row['path']).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Manifest path escapes the repository')
        data = path.read_bytes()
        if len(data) != row['size'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('Checksum mismatch: ' + row['path'])
        text = gzip.decompress(data) if path.suffix == '.gz' else data
        if secret.search(text):
            raise ValueError('Credential pattern found in: ' + row['path'])
    print('Verified', len(manifest['files']), 'files; credential scan passed')


if __name__ == '__main__':
    main()
