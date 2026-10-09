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
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    assert b'<html' in request('/').lower()
    release = json.loads((ROOT / 'config/release.json').read_text(encoding='utf-8'))
    assert health['version'] == release['version'], 'Running application version differs from this package'
    for asset in ('ocean-whale.webp', 'ocean.css', 'ocean.js', 'model-settings.css', 'model-settings.js', 'report.js'):
        delivered = request('/' + asset)
        assert delivered == (ROOT / 'web' / asset).read_bytes(), f'Missing or stale packaged asset: {asset}'
    artwork = request('/ocean-whale.webp')
    assert artwork[:4] == b'RIFF' and artwork[8:12] == b'WEBP'
    assert len(request('/background.jpg')) > 100
    session = 'deployment-' + uuid.uuid4().hex
    model_setup = json.loads(request(f'/api/model/settings?session_id={session}'))
    assert {provider['id'] for provider in model_setup['providers']} == {'openai', 'deepseek', 'custom'}
    assert 'api_key' not in model_setup['settings'] and model_setup['settings']['source'] == 'environment'
    message = (f"采集一段 {config['duration']} 秒、采样率 {config['sample_rate']}Hz、主频 {config['frequency']}Hz "
               f"的正弦信号加高斯噪声，随机种子 {config['seed']}")
    result = json.loads(request('/api/chat', {'session_id': session, 'message': message, 'agent_mode': True}))
    assert result['state']['has_processed'] and result['state']['has_summary']
    assert result['state']['signal']['sample_count'] == config['sample_rate'] * config['duration']
    report_payload = {'session_id':session,'options':{'title':'部署验收分析报告','edition':'brief'}}
    report_preview = json.loads(request('/api/reports/preview',report_payload))
    pdf = request('/api/reports/pdf',{**report_payload,'token':report_preview['token']})
    assert pdf.startswith(b'%PDF-') and len(pdf)>10000
    history = json.loads(request(f'/api/reports/history?session_id={session}'))['history']
    assert len(history)==1 and not history[0]['locked']
    assert request(f'/api/reports/plot/history/{history[0]["id"]}?session_id={session}').startswith(b'<svg')
    selected = {**report_payload,'selection':[{'kind':'history','id':history[0]['id']}]}
    multi_preview = json.loads(request('/api/reports/preview',selected))
    assert multi_preview['group_count']==1
    assert request('/api/reports/pdf',{**selected,'token':multi_preview['token']}).startswith(b'%PDF-')
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
    renamed = json.loads(request('/api/experiments/rename',{'session_id':session,'id':saved['id'],'name':'Deployment · renamed'}))
    assert renamed['name']=='Deployment · renamed'
    copied = json.loads(request('/api/experiments/duplicate',{'session_id':session,'id':saved['id'],'name':'Temporary copy'}))
    compare_payload={'session_id':session,'ids':[saved['id'],copied['id']]}
    comparison=json.loads(request('/api/experiments/compare',compare_payload))
    assert comparison['score_comparable'] and len(comparison['experiments'])==2
    report=request('/api/experiments/compare',{**compare_payload,'format':'html'})
    assert report.startswith(b'<!doctype html>') and report.count(b'<svg')==2
    deletion = {'session_id':session,'id':copied['id'],'request_id':'delete-check'}
    assert json.loads(request('/api/experiments/delete',deletion))['deleted']
    assert json.loads(request('/api/experiments/delete',deletion))['deleted']
    remaining = json.loads(request(f'/api/experiments?session_id={session}'))['experiments']
    assert [e['id'] for e in remaining]==[saved['id']] and remaining[0]['name']=='Deployment · renamed'
    assert data==request(f'/api/experiments/export?session_id={session}&format=csv')
    mapped='time_ms,unused,value\n'+'\n'.join(f'{i*5},label,{math.sin(i)}' for i in range(50))
    def mapped_form(token=None):
        fields={'session_id':session+'-mapped','options':json.dumps({'signal_column':2,'time_column':0,'time_unit':'ms'})}
        if token:fields['token']=token
        parts=[f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n' for key,value in fields.items()]
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="mapped.csv"\r\nContent-Type: text/csv\r\n\r\n{mapped}\r\n--{boundary}--\r\n')
        return ''.join(parts).encode()
    preview=json.loads(request('/api/data/preview',data=mapped_form(),content_type=f'multipart/form-data; boundary={boundary}'))
    assert preview['valid'] and preview['rows']==50 and abs(preview['sample_rate']-200)<1e-8
    imported=json.loads(request('/api/data/import',data=mapped_form(preview['token']),content_type=f'multipart/form-data; boundary={boundary}'))
    assert imported['state']['signal']['sample_count']==50
    tasks=json.loads(request(f'/api/tasks?session_id={session}'))['tasks']
    assert tasks and all('result' not in task for task in tasks)
    assert not json.loads(request(f'/api/tasks/{tasks[0]["task_id"]}/cancel',{'session_id':session}))['cancel_requested']
    storage=json.loads(request('/api/storage'));assert 'reclaimable_bytes' in storage and 'token' in storage
    diagnostic_session=session+'-diagnostic'
    def diagnostic(action,**extra):
        return json.loads(request('/api/diagnostics/'+action,{'session_id':diagnostic_session,**extra}))
    demo=diagnostic('demo',blind=True);assert 'truth' not in demo['state']['diagnostic_lab']
    event=next(e for e in demo['diagnostics']['events'] if e['kind']=='narrowband')
    trial=diagnostic('verify',event_id=event['id'],token=demo['diagnostics']['token'])
    assert trial['diagnostics']['metrics']['after_rmse'] is None
    assert trial['diagnostics']['metrics']['after_band_energy']<trial['diagnostics']['metrics']['before_band_energy']
    adopted=diagnostic('adopt');assert adopted['state']['preprocess']['method']=='diagnostic_trial'
    revealed=diagnostic('reveal');assert revealed['state']['diagnostic_lab']['revealed']
    assert 'evaluation' in revealed['state']['diagnostic_lab']
    assert request(f'/api/diagnostics/view?session_id={diagnostic_session}&format=html').startswith(b'<!doctype html>')
    assert request(f'/api/experiments/export?session_id={diagnostic_session}&format=zip').startswith(b'PK')
    return {'status': 'passed', 'session_id':session, 'saved_experiment':saved['id'], 'csv_sha256':hashlib.sha256(data).hexdigest(),
            'diagnostic_session':diagnostic_session,'report_history_id':history[0]['id'],
            'checks': ['health', 'application_version', 'web_assets', 'ocean_ui_assets', 'model_settings_api', 'pdf_report', 'report_history', 'agent_pipeline', 'sse', 'csv_upload', 'synthetic_audio_download', 'experiment_save', 'full_data_export', 'snapshot_rename_duplicate_delete', 'delete_retry', 'shared_data_preserved', 'mapped_import', 'snapshot_comparison_report', 'task_list_cancel_endpoint', 'storage_preview', 'diagnostic_blind_trial_reveal_export']}


def check_persistence(base_url, previous):
    deadline=time.monotonic()+60
    while True:
        try:
            with urllib.request.urlopen(base_url+'/api/health',timeout=3) as response:
                assert json.load(response)['status']=='ok'
            break
        except OSError:
            if time.monotonic()>deadline:raise
            time.sleep(1)
    session=previous['session_id']
    with urllib.request.urlopen(base_url+f'/api/experiments/export?session_id={session}&format=csv',timeout=15) as response:
        assert hashlib.sha256(response.read()).hexdigest()==previous['csv_sha256']
    with urllib.request.urlopen(base_url+f'/api/experiments?session_id={session}',timeout=15) as response:
        assert any(e['id']==previous['saved_experiment'] for e in json.load(response)['experiments'])
    previous['checks'].append('restart_persistence')
    with urllib.request.urlopen(base_url+f'/api/diagnostics/view?session_id={previous["diagnostic_session"]}',timeout=30) as response:
        diagnostic=json.load(response);assert diagnostic['lab']['revealed'] and diagnostic['lab']['verification']
    previous['checks'].append('diagnostic_restart_persistence')
    with urllib.request.urlopen(base_url+f'/api/reports/history?session_id={session}',timeout=15) as response:
        assert any(e['id']==previous['report_history_id'] for e in json.load(response)['history'])
    previous['checks'].append('report_history_restart_persistence')
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
