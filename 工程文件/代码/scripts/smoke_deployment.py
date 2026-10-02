"""Check a running deployment using synthetic signals and a fresh session."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


def check(base_url):
    config = json.loads((ROOT / 'config/deployment-check.json').read_text(encoding='utf-8'))
    base_url = base_url.rstrip('/')
    def request(path, payload=None, data=None, content_type='application/json'):
        if payload is not None:
            data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(base_url + path, data=data, headers={'Content-Type': content_type})
        with urllib.request.urlopen(req, timeout=config['request_timeout']) as response:
            return response.read()
    deadline = time.monotonic() + config['startup_timeout']
    while True:
        try:
            health = json.loads(request('/api/health'))
            assert health['status'] == 'ok'
            break
        except (urllib.error.URLError, TimeoutError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    assert b'<html' in request('/').lower()
    assert len(request('/background.jpg')) > 100
    session = 'deployment-' + uuid.uuid4().hex
    message = (f"采集一段 {config['duration']} 秒、采样率 {config['sample_rate']}Hz、主频 {config['frequency']}Hz "
               f"的正弦信号加高斯噪声，随机种子 {config['seed']}")
    result = json.loads(request('/api/chat', {'session_id': session, 'message': message, 'agent_mode': True}))
    assert result['state']['has_processed'] and result['state']['has_summary']
    assert result['state']['signal']['sample_count'] == config['sample_rate'] * config['duration']
    stream = request('/api/chat/stream', {'session_id': session, 'message': '分析时域和频域特征'}).decode('utf-8')
    assert 'data: [DONE]' in stream
    events = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith('data: {')]
    assert events and not any(event.get('event') == 'error' for event in events)
    samples = '\n'.join(f'{i/config["sample_rate"]},{math.sin(2*math.pi*config["frequency"]*i/config["sample_rate"])}' for i in range(100))
    boundary = 'deploycheck'
    upload = (f'--{boundary}\r\nContent-Disposition: form-data; name="session_id"\r\n\r\n{session}-upload\r\n'
              f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="sample.csv"\r\n'
              f'Content-Type: text/csv\r\n\r\n{samples}\r\n--{boundary}--\r\n').encode('utf-8')
    uploaded = json.loads(request('/api/upload', data=upload, content_type=f'multipart/form-data; boundary={boundary}'))
    assert uploaded['state']['signal']['sample_count'] == 100
    audio_samples = [0.2*math.sin(2*math.pi*440*i/8000) for i in range(4000)]
    audio = json.loads(request('/api/microphone', {'session_id': session+'-audio', 'sample_rate': 8000,
                                                  'samples': audio_samples}))['state']['audio_result']
    assert len(request(audio['denoised_url'])) > 44
    saved = json.loads(request('/api/experiments/save', {'session_id':session,'name':'Deployment acceptance'}))
    data = request(f'/api/experiments/export?session_id={session}&format=csv')
    package = request(f'/api/experiments/export?session_id={session}&format=zip')
    assert package.startswith(b'PK') and len(data.splitlines()) == config['sample_rate'] * config['duration'] + 1
    return {'status': 'passed', 'session_id':session, 'saved_experiment':saved['id'], 'csv_sha256':hashlib.sha256(data).hexdigest(),
            'checks': ['health', 'web_assets', 'agent_pipeline', 'sse', 'csv_upload', 'synthetic_audio_download', 'experiment_save', 'full_data_export']}


def check_persistence(base_url, previous):
    deadline=time.monotonic()+60
    while True:
        try:
            with urllib.request.urlopen(base_url+'/api/health',timeout=3) as response:
                assert json.load(response)['status']=='ok'
            break
        except (urllib.error.URLError,TimeoutError):
            if time.monotonic()>deadline:raise
            time.sleep(1)
    session=previous['session_id']
    with urllib.request.urlopen(base_url+f'/api/experiments/export?session_id={session}&format=csv',timeout=15) as response:
        assert hashlib.sha256(response.read()).hexdigest()==previous['csv_sha256']
    with urllib.request.urlopen(base_url+f'/api/experiments?session_id={session}',timeout=15) as response:
        assert any(e['id']==previous['saved_experiment'] for e in json.load(response)['experiments'])
    previous['checks'].append('restart_persistence')
    return previous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--check-persistence', action='store_true')
    args = parser.parse_args()
    log = ROOT / 'logs/deployment/latest.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = check_persistence(args.base_url,json.loads(log.read_text(encoding='utf-8'))) if args.check_persistence else check(args.base_url)
        message = json.dumps(result, ensure_ascii=False, indent=2)
        log.write_text(message + '\n', encoding='utf-8')
        print(message)
    except Exception as exc:
        log.write_text(f'FAILED: {type(exc).__name__}: {exc}\n', encoding='utf-8')
        raise


if __name__ == '__main__':
    main()
