"""Bounded seeded Monte Carlo sweeps, energy conversion and Wilson intervals."""
import copy
import math
import time
import numpy as np

NOISE_FIELDS={'awgn':'esn0_db','complex_awgn':'snr_db','sample_awgn':'snr_db','bandlimited_awgn':'snr_db'}


def interval(errors, total):
    if not total: return [0.,1.]
    z=1.959963984540054; p=errors/total; denominator=1+z*z/total
    center=(p+z*z/(2*total))/denominator
    half=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/denominator
    return [max(0.,center-half),min(1.,center+half)]


def sweep(raw, token, settings):
    from src import communications as c
    compiled=c.build(raw)
    if token!=compiled['token']: raise ValueError('配置已改变，请重新 Build 后扫描。')
    if not isinstance(settings,dict) or set(settings)-{'block_id','mode','start','stop','step','frames','target_errors'}: raise ValueError('扫描参数格式无效。')
    start=c.numeric(settings.get('start',0),'起始 dB',-10,40)
    stop=c.numeric(settings.get('stop',12),'结束 dB',-10,40)
    step=c.numeric(settings.get('step',2),'步长 dB',.25,20)
    frames=c.numeric(settings.get('frames',10),'每点帧数',1,c.CONFIG['max_sweep_frames'],True)
    target=c.numeric(settings.get('target_errors',100),'目标错误数',1,100000,True)
    mode=settings.get('mode','native')
    if mode not in ('native','ebn0') or stop<start: raise ValueError('请选择 SNR / Es/N₀ 或 Eb/N₀，结束值须不小于起始值。')
    values=[start+i*step for i in range(math.floor((stop-start)/step+1e-9)+1)]
    if len(values)>c.CONFIG['max_sweep_points'] or len(values)*frames>c.CONFIG['max_sweep_runs']: raise ValueError('扫描最多 21 点、总计 300 帧，请减少点数或每点帧数。')
    p=compiled['program']; noise=next((b for b in p['blocks'] if b['id']==settings.get('block_id')),None)
    if noise is None or noise['kind'] not in NOISE_FIELDS: raise ValueError('请选择一个数字 / 基带白噪声积木。')
    baseline=c.run(p,token); m=baseline['metrics']
    if 'bit_count' not in m: raise ValueError('误码扫描需要数字传输链路。')
    real=baseline.get('transport')=='baseband'
    if real:
        wave=baseline['baseband']; energy=wave['transmit_power']*wave['transmitter']['count']; power=wave['data_power']
    elif baseline.get('transport')=='advanced':
        energy=m['tx_energy']; power=energy/m['tx_sample_count']
    else:
        # Measure the same finite encoded frame, including non-unit realized
        # 16QAM energy, without changing legacy Run's result contract.
        from src import advanced_communications as advanced
        source,texts,count=c.source_data(p)
        calibration=advanced.run(advanced.build(p),source,texts,count,np.random.default_rng(np.random.SeedSequence(p['seed']).spawn(2)[1]))
        energy=calibration['metrics']['tx_energy']; power=energy/calibration['metrics']['tx_sample_count']
    if mode=='ebn0' and energy<=1e-20: raise ValueError('Eb/N₀ 标定需要非零发送能量。')
    eb=energy/m['bit_count']; field=NOISE_FIELDS[noise['kind']]
    shift=10*math.log10((1 if field=='esn0_db' else power)*(2 if real else 1)/eb) if mode=='ebn0' else 0.
    for value in values: c.numeric(value+shift,'换算后的噪声参数',-10,60)
    allowed={'random_bits','pn_bits','bit_pattern','text','mod_bpsk','mod_qpsk','awgn','ideal','demod_bpsk','demod_qpsk','sink'}
    theory=all(b['kind'] in allowed for b in p['blocks']) and sum(b['kind']=='awgn' for b in p['blocks'])==1
    width=2 if any(b['kind']=='mod_qpsk' for b in p['blocks']) else 1
    rows=[]; started=time.monotonic(); complete=True
    for value in values:
        total_bits=bit_errors=symbols=symbol_errors=frame_errors=crc_errors=done=0
        for iteration in range(frames):
            if time.monotonic()-started>c.CONFIG['max_sweep_seconds']:
                complete=False; break
            candidate=copy.deepcopy(p); candidate['seed']=(p['seed']+iteration)%4294967295
            next(b for b in candidate['blocks'] if b['id']==noise['id'])['params'][field]=value+shift
            # Keep the soft metric's channel variance consistent with AWGN.
            pure_awgn=noise['kind']=='awgn' and all(b['kind'] not in c.CHANNELS or b['kind'] in ('ideal','awgn') for b in candidate['blocks']) and sum(b['kind']=='awgn' for b in candidate['blocks'])==1
            if pure_awgn:
                for b in candidate['blocks']:
                    if b['kind'].startswith('soft_'): b['params']['noise_variance']=max(.000001,min(100,10**(-(value+shift)/10)))
            built=c.build(candidate); result=c.run(built['program'],built['token']); metrics=result['metrics']
            total_bits+=metrics['bit_count']; bit_errors+=metrics['bit_errors']; symbols+=metrics['symbol_count']; symbol_errors+=metrics['symbol_errors']
            frame_errors+=metrics.get('frame_errors',int(metrics['bit_errors']>0)); crc_errors+=metrics.get('crc_detected_frame_errors') or 0; done+=1
            if bit_errors>=target: break
        if done:
            row={'db':value,'noise_db':value+shift,'frames':done,'bit_count':total_bits,'bit_errors':bit_errors,'ber':bit_errors/total_bits,'ber_interval':interval(bit_errors,total_bits),
                 'symbol_count':symbols,'symbol_errors':symbol_errors,'ser':symbol_errors/symbols,'ser_interval':interval(symbol_errors,symbols),
                 'frame_errors':frame_errors,'fer':frame_errors/done,'fer_interval':interval(frame_errors,done),'crc_detected_errors':crc_errors,
                 'stop_reason':'target_errors' if bit_errors>=target else 'frame_limit' if done==frames else 'time_limit'}
            if theory:
                gamma=10**((value+shift)/10); row['theory_ber']=.5*math.erfc(math.sqrt(gamma/width))
            rows.append(row)
        if not complete: break
    return {'program':p,'token':token,'settings':settings,'mode':mode,'axis':'Eb/N₀ / dB' if mode=='ebn0' else 'Es/N₀ / dB' if field=='esn0_db' else '采样 SNR / dB',
            'confidence':.95,'interval_method':'Wilson','energy_reference':'发送参考帧总能量 / 信息比特数（含前导、导频、CP、尾位和填充）','reference_eb':eb,'noise_db_shift':shift,
            'seed_policy':'每个扫描点使用相同种子序列 seed + 帧序号','points':rows,'complete':complete,'elapsed_seconds':time.monotonic()-started}
