"""Verify an extracted release in a fresh venv, including the real startup script."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import signal
import socket
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args()
    archive = args.archive.resolve()
    output = ROOT / 'outputs/release'
    output.mkdir(parents=True, exist_ok=True)
    log_dir = ROOT / 'logs/release'
    log_dir.mkdir(parents=True, exist_ok=True)
    debug = ROOT / 'debug/release'
    debug.mkdir(parents=True, exist_ok=True)
    (debug / 'note.md').write_text('Temporary extraction and clean environment for release validation.\n', encoding='utf-8')
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = archive.parent / 'SHA256SUMS.txt'
    if checksum.exists():
        assert f'{digest}  {archive.name}' in checksum.read_text(encoding='utf-8')
    temp = tempfile.TemporaryDirectory(prefix='verify-', dir=debug)
    extracted = Path(temp.name).resolve()
    extracted.relative_to(debug.resolve())
    process = None
    report = {'status': 'failed', 'platform': platform.system(), 'python': platform.python_version(),
              'archive': archive.name, 'sha256': digest}
    try:
        with zipfile.ZipFile(archive) as package:
            for member in package.namelist():
                (extracted / member).resolve().relative_to(extracted)
                parts = Path(member).parts
                assert not any(part in ('.git', '.venv', 'uploads', 'outputs', 'logs', 'debug') for part in parts)
                assert not Path(member).name.endswith(('.env', '.pyc'))
            package.extractall(extracted)
        manifest_file, = extracted.glob('*/RELEASE.json')
        manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
        report['commit'] = manifest['commit']
        report['version'] = manifest['version']
        code = manifest_file.parent / manifest['runtime_path']
        assert (code / 'server.py').is_file()
        assert (code / 'web/background.jpg').is_file()
        assert (manifest_file.parent / 'LICENSE').is_file()
        env = os.environ.copy()
        env.update({'RS_AGENT_LLM_ENABLED': '0', 'PYTHONUTF8': '1', 'PYTHONUNBUFFERED': '1'})
        with (log_dir / 'latest.log').open('w', encoding='utf-8') as log:
            def run(command):
                log.write('\nCOMMAND: ' + ' '.join(map(str, command)) + '\n')
                log.flush()
                subprocess.run(list(map(str, command)), cwd=code, env=env, stdout=log,
                               stderr=subprocess.STDOUT, check=True, timeout=300)
            run([sys.executable, '-m', 'venv', '.venv'])
            bin_dir = code / '.venv' / ('Scripts' if os.name == 'nt' else 'bin')
            python = bin_dir / ('python.exe' if os.name == 'nt' else 'python')
            run([python, '-m', 'pip', 'install', '-r', 'requirements-repro.txt'])
            run([python, '-m', 'pip', 'check'])
            run([python, 'scripts/test_regressions.py'])
            run([python, 'scripts/verify_reproduction.py'])
            env['PATH'] = str(bin_dir) + os.pathsep + env.get('PATH', '')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            env['RS_AGENT_HOST'] = '127.0.0.1'
            env['RS_AGENT_PORT'] = str(port)
            server_log = (log_dir / 'server.log').open('w', encoding='utf-8')
            try:
                if os.name == 'nt':
                    command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                               '-File', 'scripts/start_server.ps1', '-HostName', '127.0.0.1', '-Port', str(port)]
                    options = {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
                else:
                    command = ['bash', 'scripts/start_server.sh']
                    options = {'start_new_session': True}
                process = subprocess.Popen(command, cwd=code, env=env, stdout=server_log,
                                           stderr=subprocess.STDOUT, **options)
                run([python, 'scripts/smoke_deployment.py', '--base-url', f'http://127.0.0.1:{port}'])
                report['numpy'] = subprocess.check_output([str(python), '-c', 'import numpy; print(numpy.__version__)'], env=env, text=True).strip()
                report['status'] = 'passed'
                report['checks'] = ['archive_contents', 'sha256', 'fresh_venv_install', 'pip_check',
                                    'regression_suite', 'integration_suite', 'real_startup_script',
                                    'health', 'web_assets', 'agent_pipeline', 'sse', 'csv_upload', 'synthetic_audio_download']
            finally:
                if process is not None and process.poll() is None:
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=log, stderr=log, check=False)
                    else:
                        os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=15)
                server_log.close()
    finally:
        (output / f'verification-{platform.system().lower()}.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temp.cleanup()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
