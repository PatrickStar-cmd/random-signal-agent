"""Archive a committed revision with release metadata and a SHA-256 checksum."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import zipfile

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
    subprocess.run(['git', 'archive', '--format=zip', '--prefix=' + folder + '/',
                    '--output=' + str(archive.resolve()), commit], cwd=REPO, check=True)
    manifest = {**config, 'commit': commit, 'artifact': archive.name}
    with zipfile.ZipFile(archive, 'a', compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr(folder + '/RELEASE.json', json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (args.output_dir / 'SHA256SUMS.txt').write_text(f'{digest}  {archive.name}\n', encoding='utf-8')
    log = ROOT / 'logs/release/build.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    message = f'Version: {config["version"]}\nCommit: {commit}\nArchive: {archive}\nSHA256: {digest}\n'
    log.write_text(message, encoding='utf-8')
    print(message)


if __name__ == '__main__':
    main()
