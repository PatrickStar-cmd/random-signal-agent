"""Source export and local-device operations for the communication workbench."""
from io import BytesIO
import json
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo

from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from src import communication_board_codegen as codegen


def local_device_request(request):
    hosts = {'127.0.0.1', '::1', 'localhost'}
    origin = request.headers.get('origin')
    return (request.client is not None and request.client.host in hosts
            and request.url.hostname in hosts
            and (not origin or origin == str(request.base_url).rstrip('/')))


def _export_files(generated):
    files = dict(generated['files'])
    metadata = {name: generated[name] for name in ('artifact_id', 'board', 'language', 'experiment', 'source_map', 'steps', 'expected')}
    esp = generated['board'] == codegen.ESP32
    if generated['language'] == 'micropython':
        setup = '安装所选板型的官方 MicroPython 固件，上传 main.py 并重启。'
    elif esp:
        setup = '从 ESP-IDF 终端运行 idf.py build 和 idf.py -p PORT flash。使用 USB 转 UART 接口作为控制台。'
    else:
        setup = '配置 Pico SDK 后执行 cmake -S . -B build -G Ninja 和 cmake --build build。将 build/randomsign_board.uf2 写入 BOOTSEL 盘。'
    pins = 'GPIO17 TX / GPIO18 RX' if esp else 'GP0 TX / GP1 RX'
    role = generated.get('role')
    if role:
        metadata['role'] = role
        guide = '板间 UART 使用发送端 TX 接接收端 RX 并共地，两端分别使用 USB 部署与回读。接收端先运行，出现 ready 后启动发送端。两个端点使用相同十六进制运行标识，末四位为帧序号。'
    elif generated['experiment'] == 'uart':
        guide = '用跳线连接本板 TX 与 RX。USB 用于部署与回读。'
    else:
        guide = '在板内计算符号，USB 回传各积木输出。'
    files['experiment.json'] = json.dumps(metadata, ensure_ascii=False, indent=2) + '\n'
    files['README.txt'] = '\n'.join([f"RandomSign  {generated['board']}  {generated['language']}  {role or generated['experiment']}",
                                    setup, pins, guide, '手动运行命令', f"RUN {generated['artifact_id']} 0001", ''])
    return files


def source_zip(generated):
    if 'endpoints' in generated:
        files = {role+'/'+name: content for role, ep in generated['endpoints'].items()
                 for name, content in _export_files(ep).items()}
        files['experiment.json'] = json.dumps({k: generated[k] for k in ('artifact_id','experiment','source_map','steps','frame','expected','bridge')},
                                              ensure_ascii=False, indent=2) + '\n'
        files['README.txt'] = '分别打开 tx 和 rx 目录。按两端 README 接线，在工作台点击运行双板实验。\n'
        label = 'dual-uart'
    else:
        files = _export_files(generated)
        label = '-'.join((generated['board'], generated['experiment'], generated['language']))
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        for name, contents in sorted(files.items()):
            archive.writestr(ZipInfo(name), contents.encode('utf-8'), compress_type=ZIP_DEFLATED)
    return Response(output.getvalue(), media_type='application/zip', headers={
        'Content-Disposition': f'attachment; filename="randomsign-{label}-{generated["artifact_id"][:8]}.zip"'
    })


async def dispatch(action, request, payload):
    if action not in ('generate', 'export', 'devices', 'build', 'deploy', 'run'):
        raise ValueError('请选择有效的开发板操作。')
    if action not in ('generate', 'export') and not local_device_request(request):
        return JSONResponse({'error': '请在连接开发板的电脑上通过 localhost 或 127.0.0.1 打开工作台。'}, 403)
    from src import communication_board_device as device
    if action == 'devices':
        return await run_in_threadpool(device.devices)
    try:
        generated = await run_in_threadpool(codegen.generate, payload.get('document'), payload.get('language', 'cpp'), payload.get('board', 'pico'), payload.get('targets'))
    except codegen.BoardCodeError as exc:
        return JSONResponse({'error': str(exc), 'block_ids': exc.block_ids}, 400)
    if action == 'generate':
        return generated
    if 'endpoints' in generated:
        if action == 'run':
            from src import communication_board_pair
            return await run_in_threadpool(communication_board_pair.measure, generated, payload.get('device_ids'))
        role = payload.get('role')
        if role is not None or action in ('build', 'deploy'):
            if role not in ('tx', 'rx'):
                raise ValueError('请选择发送端或接收端。')
            generated = generated['endpoints'][role]
    if action == 'export':
        return await run_in_threadpool(source_zip, generated)
    if action == 'build':
        return await run_in_threadpool(device.build_firmware, generated)
    if action == 'deploy':
        return await run_in_threadpool(device.deploy, generated, payload.get('device_id'), payload.get('build_id'))
    return await run_in_threadpool(device.measure, generated, payload.get('device_id'))
