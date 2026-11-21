"""Local Pico build, USB deployment and experiment telemetry."""
import ctypes
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time


FIRMWARE = {
    'pico': 'https://micropython.org/download/RPI_PICO/',
    'pico_w': 'https://micropython.org/download/RPI_PICO_W/',
}
PICO_HOME = Path.home() / '.pico-sdk'
CACHE = Path(os.environ.get('RS_AGENT_DATA_DIR', Path(__file__).resolve().parents[1] / 'data')) / 'board-builds'
_device_lock = threading.Lock()


def _installed(pattern):
    paths = [p for p in PICO_HOME.glob(pattern) if p.is_file()]
    paths.sort(key=lambda p: [int(n) for n in re.findall(r'\d+', str(p.relative_to(PICO_HOME)))], reverse=True)
    return str(paths[0]) if paths else None


def _toolchain():
    suffix = '.exe' if os.name == 'nt' else ''
    sdk = os.environ.get('PICO_SDK_PATH')
    if not sdk:
        sdk_file = _installed('sdk/*/pico_sdk_init.cmake')
        sdk = str(Path(sdk_file).parent) if sdk_file else None
    cc = shutil.which('arm-none-eabi-gcc')
    if os.environ.get('PICO_TOOLCHAIN_PATH'):
        root = Path(os.environ['PICO_TOOLCHAIN_PATH'])
        cc = shutil.which('arm-none-eabi-gcc', path=os.pathsep.join(map(str, (root / 'bin', root))))
    return {
        'sdk': sdk if sdk and (Path(sdk) / 'external/pico_sdk_import.cmake').is_file() else None,
        'compiler': cc or _installed('toolchain/*/bin/arm-none-eabi-gcc' + suffix),
        'cmake': shutil.which('cmake') or _installed('cmake/*/bin/cmake' + suffix),
        'ninja': shutil.which('ninja') or _installed('ninja/*/ninja' + suffix),
        'picotool_config': _installed('picotool/*/picotool/picotoolConfig.cmake'),
    }


def _bootsel_drives():
    if os.name != 'nt':
        return
    kernel = ctypes.windll.kernel32
    drives = kernel.GetLogicalDrives()
    for index in range(26):
        if not drives & (1 << index):
            continue
        root = Path(chr(65 + index) + ':\\')
        if kernel.GetDriveTypeW(str(root)) != 2:  # DRIVE_REMOVABLE
            continue
        try:
            with (root / 'INFO_UF2.TXT').open('rb') as marker:
                identity = marker.read(2048).decode('ascii')
            if not re.search(r'^Board-ID:\s*RPI-RP2\s*$', identity, re.MULTILINE):
                continue
            volume = ctypes.create_unicode_buffer(64)
            if not kernel.GetVolumeNameForVolumeMountPointW(str(root), volume, len(volume)):
                continue
            yield {'kind': 'bootsel', 'id': 'bootsel:' + volume.value,
                   'label': f'RP2040 BOOTSEL ({root.drive})', 'path': volume.value}
        except (OSError, UnicodeError):
            continue


def _connected():
    yield from _bootsel_drives()
    if importlib.util.find_spec('serial'):
        from serial.tools.list_ports import comports
        for port in comports():
            if port.vid == 0x2E8A:
                yield {'id': f'serial:{port.device}:{port.serial_number or ""}', 'kind': 'serial',
                       'label': f'{port.description} ({port.device})', 'path': port.device}


def devices():
    capabilities = {k: bool(v) for k, v in _toolchain().items() if k != 'picotool_config'}
    capabilities.update({k: bool(importlib.util.find_spec(k)) for k in ('serial', 'mpremote')})
    return {'devices': [{k: d[k] for k in ('id', 'kind', 'label')} for d in _connected()],
            'tools': capabilities, 'micropython_firmware': FIRMWARE}


def _select(device_id, kind):
    for device in _connected():
        if device['id'] == device_id and device['kind'] == kind:
            return device
    raise ValueError('请刷新设备并选择已连接的 ' + ('RP2040 BOOTSEL 盘。' if kind == 'bootsel' else 'Pico USB 串口。'))


def _command(args, timeout, env=None):
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        raise ValueError('工具执行超时，请检查工具链或 USB 连接。') from exc
    if result.returncode:
        raise ValueError((result.stdout + '\n' + result.stderr).strip()[-4000:] or '工具执行失败。')
    return result.stdout


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def build_firmware(generated):
    if generated['language'] != 'cpp' or generated['board'] not in FIRMWARE:
        raise ValueError('请选择 Pico 或 Pico W 的 C++ 工程进行固件构建。')
    tools = _toolchain()
    missing = [k for k in ('sdk', 'compiler', 'cmake', 'ninja') if not tools[k]]
    if missing:
        raise ValueError('请配置开发板构建工具 ' + ', '.join(missing))
    with tempfile.TemporaryDirectory(prefix='rs-pico-') as temporary:
        project = Path(temporary)
        for name in ('main.cpp', 'CMakeLists.txt'):
            (project / name).write_text(generated['files'][name], encoding='utf-8')
        build = project / 'build'
        cc_bin = str(Path(tools['compiler']).parent)
        env = {**os.environ, 'PATH': cc_bin + os.pathsep + os.environ['PATH'],
               'PICO_SDK_PATH': tools['sdk']}
        configure = [tools['cmake'], '-S', str(project), '-B', str(build), '-G', 'Ninja',
                     '-DPICO_BOARD=' + generated['board'], '-DPICO_SDK_PATH=' + tools['sdk'],
                     '-DCMAKE_MAKE_PROGRAM=' + tools['ninja']]
        if tools['picotool_config']:
            configure.append('-Dpicotool_DIR=' + str(Path(tools['picotool_config']).parent))
        _command(configure, 180, env)
        _command([tools['cmake'], '--build', str(build), '--parallel', '4'], 300, env)
        binary = (build / 'randomsign_board.uf2').read_bytes()
    sha = _digest(binary)
    artifact = generated['artifact_id']
    build_id = _digest((artifact + sha).encode('ascii'))
    info = {'build_id': build_id, 'artifact_id': artifact, 'board': generated['board'],
            'filename': 'randomsign_board.uf2', 'size': len(binary), 'sha256': sha}
    CACHE.mkdir(exist_ok=True, parents=True)
    with tempfile.TemporaryDirectory(dir=CACHE) as temporary:
        staged = Path(temporary) / 'complete'
        staged.mkdir()
        (staged / info['filename']).write_bytes(binary)
        (staged / 'manifest.json').write_text(json.dumps(info), encoding='ascii')
        try:
            staged.rename(CACHE / build_id)
        except OSError:
            if not (CACHE / build_id).is_dir():
                raise
    return info


def firmware_path(build_id, artifact_id=None):
    if not isinstance(build_id, str) or not re.fullmatch(r'[a-f0-9]{64}', build_id):
        raise ValueError('请选择已构建的固件。')
    folder = CACHE / build_id
    binary = folder / 'randomsign_board.uf2'
    if not binary.is_file():
        raise ValueError('固件尚未构建。')
    info = json.loads((folder / 'manifest.json').read_text(encoding='ascii'))
    checked_id = _digest((info['artifact_id'] + _digest(binary.read_bytes())).encode('ascii'))
    if checked_id != build_id or (artifact_id is not None and artifact_id != info['artifact_id']):
        raise ValueError('当前工程与固件不匹配，请重新构建。')
    return binary


def deploy(generated, device_id, build_id=None):
    board, language = generated['board'], generated['language']
    if board not in FIRMWARE or language not in ('cpp', 'micropython'):
        raise ValueError('请选择支持的板型和语言。')
    with _device_lock:
        if language == 'cpp':
            binary = firmware_path(build_id, generated['artifact_id'])
            root = Path(_select(device_id, 'bootsel')['path'])
            try:
                shutil.copyfile(binary, root / 'randomsign.uf2')
            except OSError as exc:
                raise ValueError('BOOTSEL 写入失败，请检查所选开发板的 USB 连接。') from exc
        else:
            device = _select(device_id, 'serial')
            if not importlib.util.find_spec('mpremote'):
                raise ValueError('请在当前 Python 环境安装 mpremote。')
            machine = 'Raspberry Pi Pico W' if board == 'pico_w' else 'Raspberry Pi Pico'
            # Check the installed interpreter's board identity in the same connection as the upload.
            check = f"import sys; assert sys.implementation._machine == '{machine} with RP2040', sys.implementation._machine"
            with tempfile.TemporaryDirectory(prefix='rs-mp-') as temporary:
                local = Path(temporary) / 'main.py'
                local.write_text(generated['files']['main.py'], encoding='utf-8')
                remote = 'rs_' + secrets.token_hex(6) + '.tmp'
                _command([sys.executable, '-m', 'mpremote', 'connect', device['path'],
                          'exec', check, 'fs', 'cp', str(local), ':' + remote, '+',
                          'exec', f"import os; os.rename('{remote}', 'main.py')", 'reset'], 60)
    return {'status': 'written', 'device_id': device_id, 'board': board, 'language': language}


def _finish(generated, nodes, frame):
    for key in ('artifact_id', 'board', 'language', 'experiment'):
        if frame.get(key) != generated[key]:
            raise ValueError('设备回传的工程或板型与当前选择不一致。')
    expected = generated['expected']['nodes']
    order = list(expected)
    metrics = frame.get('metrics')
    if not isinstance(metrics, dict):
        raise ValueError('设备指标缺失。')
    status = frame.get('status')
    if status == 'ok' and list(nodes) == order:
        reference = expected[order[-1]]
        compared = len(reference)
        errors = sum(a != b for a, b in zip(reference, nodes[order[-1]]))
        received = 1
    elif status == 'timeout' and generated['experiment'] == 'uart':
        uart = next(i for i, s in enumerate(generated['steps']) if s['kind'] == 'uart_loopback')
        if list(nodes) != order[:uart]:
            raise ValueError('串口超时前的节点回传不完整。')
        compared, errors, received = 0, 0, 0
    else:
        raise ValueError('节点回传顺序或运行状态异常。')
    counts = {'compared_bits': compared, 'bit_errors': errors, 'expected_frames': 1,
              'received_frames': received, 'lost_frames': 1 - received}
    if any(type(metrics.get(k)) is not int or metrics[k] != v for k, v in counts.items()):
        raise ValueError('板端计数与实际回传不符。')
    ber = metrics.get('ber')
    if 'ber' not in metrics or (not compared and ber is not None) or (compared and
            (type(ber) not in (int, float) or not math.isclose(ber, errors / compared, rel_tol=1e-5, abs_tol=1e-9))):
        raise ValueError('板端 BER 与回传比特不符。')
    return {k: frame[k] for k in ('artifact_id', 'board', 'language', 'experiment', 'status', 'metrics')} | {
        'nodes': nodes, 'matches_reference': status == 'ok' and nodes == expected}


def _receive(serial_port, generated, nonce):
    expected = generated['expected']['nodes']
    nodes = {}
    deadline = time.monotonic() + 20
    pending = bytearray()
    while time.monotonic() < deadline:
        pending.extend(serial_port.read(min(8192, max(1, serial_port.in_waiting))))
        while b'\n' in pending:
            end = pending.index(b'\n') + 1
            line = bytes(pending[:end]).strip()
            del pending[:end]
            if not line.startswith(b'RS050 '):
                continue
            frame = json.loads(line[6:])
            if not isinstance(frame, dict) or frame.get('nonce') != nonce:
                continue
            if frame.get('type') == 'done':
                return _finish(generated, nodes, frame)
            key, values = frame.get('id'), frame.get('values')
            if (frame.get('type') != 'node' or not isinstance(key, str) or key not in expected or key in nodes
                    or not isinstance(values, list) or len(values) != len(expected[key])
                    or any(type(x) is not int or x not in (-1, 0, 1) for x in values)):
                raise ValueError('设备回传的节点或数据格式异常。')
            nodes[key] = values
        if len(pending) > 16384:
            raise ValueError('设备回传行过长。')
    raise ValueError('开发板实验响应超时，请确认串口和当前部署的工程。')


def measure(generated, device_id):
    import serial
    with _device_lock:
        device = _select(device_id, 'serial')
        nonce = secrets.token_hex(12)
        try:
            with serial.Serial(device['path'], 115200, timeout=0.2, write_timeout=2) as port:
                port.reset_input_buffer()
                port.write(f"RUN {generated['artifact_id']} {nonce}\n".encode('ascii'))
                port.flush()
                result = _receive(port, generated, nonce)
        except serial.SerialException as exc:
            raise ValueError('USB 串口访问失败 ' + str(exc)) from exc
    return {**result, 'device_id': device_id}
