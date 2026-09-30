"""Archive a committed revision with release metadata and a SHA-256 checksum."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import re
import stat
import subprocess
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def main():
    config = json.loads((ROOT / 'config/release.json').read_text(encoding='utf-8'))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='HEAD')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs/release')
    args = parser.parse_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+', config['version']):
        raise ValueError('Expected a numeric semantic version')
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=REPO)
    if dirty:
        raise RuntimeError('Commit tracked changes before building a release')
    commit = subprocess.check_output(['git', 'rev-parse', '--verify', args.ref + '^{commit}'], cwd=REPO, text=True).strip()
    folder = f"{config['name']}-v{config['version']}"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    archive = args.output_dir / f'{folder}-deploy.zip'
    manifest = {**config, 'commit': commit, 'artifact': archive.name}
    snapshot = subprocess.check_output(['git', 'archive', '--format=zip', commit], cwd=REPO)
    timestamp = int(subprocess.check_output(['git', 'show', '-s', '--format=%ct', commit], cwd=REPO, text=True).strip())
    date = datetime.fromtimestamp(timestamp, timezone.utc).timetuple()[:6]
    # Fixed timestamps, permissions and uncompressed storage make the archive
    # byte-identical across Windows/Linux and independent of zlib versions.
    with zipfile.ZipFile(io.BytesIO(snapshot)) as source, zipfile.ZipFile(archive, 'w') as package:
        for original in sorted(source.infolist(), key=lambda item: item.filename):
            entry = zipfile.ZipInfo(folder + '/' + original.filename, date_time=date)
            entry.create_system = 3
            mode = (stat.S_IFDIR | 0o755) if original.is_dir() else (stat.S_IFREG | (0o755 if (original.external_attr >> 16) & 0o111 else 0o644))
            entry.external_attr = mode << 16
            if original.is_dir():
                entry.external_attr |= 0x10
            package.writestr(entry, source.read(original))
        entry = zipfile.ZipInfo(folder + '/RELEASE.json', date_time=date)
        entry.create_system = 3
        entry.external_attr = (stat.S_IFREG | 0o644) << 16
        package.writestr(entry, json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (args.output_dir / 'SHA256SUMS.txt').write_text(f'{digest}  {archive.name}\n', encoding='utf-8')
    log = ROOT / 'logs/release/build.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    message = f'Version: {config["version"]}\nCommit: {commit}\nArchive: {archive}\nSHA256: {digest}\n'
    log.write_text(message, encoding='utf-8')
    print(message)


if __name__ == '__main__':
    main()
