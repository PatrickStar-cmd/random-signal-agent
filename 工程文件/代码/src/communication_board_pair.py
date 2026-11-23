"""Coordinate two independently deployed programs over their USB control ports."""
import itertools
import secrets
from contextlib import ExitStack

from src import communication_board_device as device, communication_board_link as link

_sequences = itertools.count(secrets.randbelow(65536))
RX_FAILURES = {'timeout', 'crc_error', 'sequence_error', 'length_error', 'frame_error'}


def _check_event(frame, ep, nonce, kind):
    identity = {k: ep[k] for k in ('artifact_id', 'board', 'language', 'experiment', 'role')}
    identity.update(nonce=nonce, type=kind, sequence=int(nonce[-4:], 16))
    if kind == 'ready':
        identity['status'] = 'ready'
    if any(frame.get(k) != v for k, v in identity.items()):
        raise ValueError('请核对两端程序、角色和本次运行序号。')


def _wire(frame, count, sequence):
    observed = frame.get('sequence')
    crc = frame.get('crc16')
    payload = frame.get('payload')
    if (any(type(n) is not int or not 0 <= n <= 65535 for n in (observed, crc)) or
            type(frame.get('count')) is not int or frame['count'] != count or
            not isinstance(payload, list) or len(payload) != (count+7)//8 or
            any(type(n) is not int or not 0 <= n <= 255 for n in payload)):
        raise ValueError('接收板回传的 UART 原始帧格式异常。')
    body = link.HEADER.pack(link.MAGIC, observed, count) + bytes(payload)
    computed = int.from_bytes(link.crc16_bytes(body), 'big')
    status = 'crc_error' if computed != crc else 'sequence_error' if observed != sequence else 'ok'
    bits = [(payload[i//8] >> (7 - i%8)) & 1 for i in range(count)]
    return {'rx_sequence': observed, 'crc16': crc, 'computed_crc16': computed,
            'crc_ok': computed == crc, 'received': bits, 'status': status}


def _collect(records, ep, nonce):
    nodes, syndromes = {}, {}
    wire = None
    first = ep['steps'][0]['id']
    for row in records:
        if row.get('type') == 'wire':
            if ep['role'] != 'rx' or wire is not None or nodes:
                raise ValueError('原始帧回读顺序异常。')
            wire = _wire(row, len(ep['expected']['nodes'][first]), int(nonce[-4:], 16))
            continue
        if row.get('type') != 'done':
            device._record_node(ep, nodes, syndromes, row)
            continue
        _check_event(row, ep, nonce, 'done')
        status = row.get('status')
        if status == 'ok':
            if list(nodes) != list(ep['expected']['nodes']):
                raise ValueError('端点回读的积木数量不完整。')
        elif ep['role'] != 'rx' or status not in RX_FAILURES or nodes:
            raise ValueError('端点回读状态与节点数据不一致。')
        if ep['role'] == 'rx' and (wire is not None or status in ('ok','crc_error','sequence_error')):
            if not wire or status != wire['status'] or (status == 'ok' and wire['received'] != nodes[first]):
                raise ValueError('接收结果与 UART 原始帧校验不一致。')
        return {'status': status, 'wire': wire, 'nodes': nodes, 'syndromes': syndromes, 'artifact_id': ep['artifact_id'],
                'board': ep['board'], 'language': ep['language']}
    raise ValueError('端点运行记录不完整。')


def run_ports(project, tx_port, rx_port, nonce):
    eps = project['endpoints']
    for port in (rx_port, tx_port):
        port.reset_input_buffer()
    def start(role, port):
        port.write(f"RUN {eps[role]['artifact_id']} {nonce}\n".encode('ascii'))
        port.flush()
        return device._records(port, nonce)
    rx_stream = start('rx', rx_port)
    _check_event(next(rx_stream), eps['rx'], nonce, 'ready')
    tx = _collect(start('tx', tx_port), eps['tx'], nonce)
    rx = _collect(rx_stream, eps['rx'], nonce)
    bridge = project['bridge']
    received = rx['status'] == 'ok'
    source = [v for s in eps['tx']['steps'] if s['kind'] in ('bit_pattern', 'text', 'pn_bits')
              for v in tx['nodes'][s['id']]]
    sink = rx['nodes'][eps['rx']['steps'][-1]['id']] if received else []
    compared = len(sink)
    if received and len(source) != compared:
        raise ValueError('实收有效长度与发送信源长度不一致。')
    errors = sum(a != b for a, b in zip(source, sink))
    frame = rx.pop('wire') or {'rx_sequence': None, 'crc16': None, 'computed_crc16': None,
                                  'crc_ok': None, 'received': None, 'status': rx['status']}
    tx.pop('wire')
    # A bridge on the canvas denotes the receiver output. Its TX trace is
    # retained separately even when no frame reaches the receiver.
    nodes = {k:v for k,v in tx['nodes'].items() if k != bridge} | rx['nodes']
    matches = received and nodes == project['expected']['nodes'] and tx['nodes'][bridge] == rx['nodes'][bridge]
    return {'status': rx['status'], 'artifact_id': project['artifact_id'], 'nonce': nonce,
            'matches_reference': matches, 'nodes': nodes, 'syndromes': rx['syndromes'],
            'endpoints': {'tx': tx, 'rx': rx},
            'frame': {**frame, 'sequence': int(nonce[-4:], 16), 'sent': tx['nodes'][bridge]},
            'metrics': {'expected_frames': 1, 'received_frames': int(received), 'lost_frames': int(not received),
                        'compared_bits': compared, 'bit_errors': errors, 'ber': errors/compared if compared else None}}


def measure(project, device_ids):
    import serial
    if not isinstance(device_ids, dict) or not all(isinstance(device_ids.get(k), str) and device_ids[k] for k in ('tx','rx')):
        raise ValueError('请分别选择发送端和接收端的串口。')
    with device._device_lock, ExitStack() as stack:
        selected = {role: device._serial_for(device_ids[role], ep['board']) for role, ep in project['endpoints'].items()}
        if selected['tx']['path'] == selected['rx']['path']:
            raise ValueError('两个端点需要两个独立 USB 串口。')
        try:
            ports = {role: stack.enter_context(device._usb_port(d, project['endpoints'][role]['board']))
                     for role, d in selected.items()}
            nonce = secrets.token_hex(8) + format(next(_sequences) & 0xffff, '04x')
            result = run_ports(project, ports['tx'], ports['rx'], nonce)
        except serial.SerialException as exc:
            raise ValueError('双板 USB 串口访问失败 ' + str(exc)) from exc
        return {**result, 'device_ids': dict(device_ids)}
