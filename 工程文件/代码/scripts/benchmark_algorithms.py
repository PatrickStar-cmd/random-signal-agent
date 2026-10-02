"""Fixed-seed numerical baseline; SciPy is used only as a test oracle."""
from pathlib import Path
import csv
import json
import sys
import time
import numpy as np
from scipy.signal import welch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.signal_processing import SignalConfig, generate_random_signal, estimate_snr
from src.preprocessing import PREPROCESS_METHODS, PreprocessConfig, preprocess_signal
from src.advanced_analysis import estimate_welch_psd
from src.dialogue_agent import RandomSignalDialogueAgent, ConversationState


def main():
    config=json.loads((ROOT/'config/benchmark.json').read_text(encoding='utf-8'))
    rows=[]; agent=RandomSignalDialogueAgent()
    for waveform in config['waveforms']:
      for rate in config['sample_rates']:
       for noise in config['noise_levels']:
        for seed in config['seeds']:
         bundle=generate_random_signal(SignalConfig(sample_rate=rate,duration=config['duration'],waveform=waveform,
               noise_model='gaussian_impulse' if waveform=='impulses' else 'gaussian',noise_std=noise,seed=seed))
         if waveform=='impulses':
             bundle.clean[:]=0;bundle.clean[::max(1,int(rate)//4)]=2
             bundle.observed=bundle.clean+bundle.noise
         state=ConversationState('benchmark',bundle=bundle)
         for method in PREPROCESS_METHODS:
          start=time.perf_counter()
          result=preprocess_signal(bundle.observed,PreprocessConfig(method=method,sample_rate=rate,lowpass_cutoff_hz=rate*.18))
          elapsed=(time.perf_counter()-start)*1000
          summary=agent._candidate_preprocess_summary(state,result)
          metrics=agent._preprocess_quality_details(state,result,summary)
          row={'waveform':waveform,'sample_rate':rate,'noise_std':noise,'seed':seed,'method':method,
               'rmse':float(np.sqrt(np.mean((bundle.clean-result.signal)**2))),
               'snr_db':float(estimate_snr(bundle.clean,result.signal)),
               'correlation':metrics['clean_correlation'],'residual_correlation':metrics['residual_correlation'],
               'rms_change':metrics['rms_ratio_error'],'spectral_entropy':summary['frequency_features']['spectral_entropy'],
               'duration_ms':round(elapsed,4)}
          assert all(np.isfinite(v) for v in row.values() if isinstance(v,(int,float)))
          rows.append(row)
    # Match symmetric Hann, overlap rounding, segment detrending and AC-only convention.
    max_error=0.0
    for nperseg in (127,128,255,256):
        signal=np.random.default_rng(42).normal(size=2048)
        ours=estimate_welch_psd(signal,200,nperseg,.5)
        f,p=welch(signal,fs=200,window=np.hanning(nperseg),nperseg=nperseg,
                  noverlap=nperseg-int(nperseg*.5),detrend='constant',scaling='density')
        p[0]=0
        np.testing.assert_allclose(ours['frequencies'],f,rtol=1e-12,atol=1e-12)
        np.testing.assert_allclose(ours['power'],p,rtol=1e-10,atol=1e-12)
        max_error=max(max_error,float(np.max(np.abs(np.asarray(ours['power'])-p))))
    out=ROOT/'outputs/benchmark';out.mkdir(parents=True,exist_ok=True)
    with (out/'baseline.csv').open('w',newline='',encoding='utf-8') as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    report={'status':'passed','cases':len(rows),'scipy_psd_max_absolute_error':max_error,
            'note':'Fixed parameters, not tuned scores. No method is assumed best across all signals.',
            'config':config}
    (out/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    log=ROOT/'logs/benchmark/latest.log';log.parent.mkdir(parents=True,exist_ok=True)
    log.write_text(json.dumps(report,indent=2),encoding='utf-8');print(log.read_text(encoding='utf-8'))


if __name__=='__main__':main()
