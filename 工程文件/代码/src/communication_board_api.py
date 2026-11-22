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


def source_zip(generated):
    files = dict(generated['files'])
    metadata = {name: generated[name] for name in ('artifact_id', 'board', 'language', 'experiment', 'source_map', 'steps', 'expected')}
    files['experiment.json'] = json.dumps(metadata, ensure_ascii=False, indent=2) + '\n'
    steps = (['配置好 Pico SDK 后，进入此目录执行：', 'cmake -S . -B build -G Ninja',
              'cmake --build build', '将 build/randomsign_board.uf2 写入所选开发板的 BOOTSEL 盘。']
             if generated['language'] == 'cpp' else
             ['在所选板型上安装官方 MicroPython 固件，再将 main.py 上传至板载文件系统根目录并重启。'])
    files['README.txt'] = '\n'.join([
        f'RandomSign  {generated["board"]}  {generated["language"]}  {generated["experiment"]}',
        *steps,
        'BPSK 和 QPSK 在板内计算。UART 实验需要用跳线连接 GP0 与 GP1。',
        '打开工作台的开发板面板，选择此工程对应的板型、语言与 USB 串口，点击运行并回读。',
        '手动运行可用 USB 串口终端发送以下命令并以换行结尾。RS050 行包含逐块输出及最终指标。',
        f'RUN {generated["artifact_id"]} demo', ''
    ])
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        for name, contents in sorted(files.items()):
            archive.writestr(ZipInfo(name), contents.encode('utf-8'), compress_type=ZIP_DEFLATED)
    return Response(output.getvalue(), media_type='application/zip', headers={
        'Content-Disposition': f'attachment; filename="randomsign-{generated["board"]}-{generated["experiment"]}-{generated["language"]}-{generated["artifact_id"][:8]}.zip"'
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
        generated = await run_in_threadpool(codegen.generate, payload.get('document'), payload.get('language'), payload.get('board'))
    except codegen.BoardCodeError as exc:
        return JSONResponse({'error': str(exc), 'block_ids': exc.block_ids}, 400)
    if action == 'generate':
        return generated
    if action == 'export':
        return await run_in_threadpool(source_zip, generated)
    if action == 'build':
        return await run_in_threadpool(device.build_firmware, generated)
    if action == 'deploy':
        return await run_in_threadpool(device.deploy, generated, payload.get('device_id'), payload.get('build_id'))
    return await run_in_threadpool(device.measure, generated, payload.get('device_id'))
