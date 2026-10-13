"""Run the same seeded Monte Carlo experiment as the communication-lab UI."""
from pathlib import Path
import argparse
import csv
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src import communications as c
from src.communication_sweep import NOISE_FIELDS, sweep


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preset',choices=list(c.PRESETS),default='soft_viterbi')
    parser.add_argument('--program',type=Path,help='Exported project JSON overrides --preset')
    parser.add_argument('--noise-id',help='Defaults to the first supported noise block')
    parser.add_argument('--mode',choices=['native','ebn0'],default='native')
    parser.add_argument('--start',type=float,default=0)
    parser.add_argument('--stop',type=float,default=12)
    parser.add_argument('--step',type=float,default=2)
    parser.add_argument('--frames',type=int,default=10)
    parser.add_argument('--target-errors',type=int,default=100)
    parser.add_argument('--output',type=Path,default=ROOT/'outputs/communications/sweep.json')
    args=parser.parse_args()
    p=json.loads(args.program.read_text(encoding='utf-8')) if args.program else c.PRESETS[args.preset]['program']
    noise=args.noise_id or next((b['id'] for b in p['blocks'] if b['kind'] in NOISE_FIELDS),'')
    built=c.build(p)
    result=sweep(p,built['token'],{'block_id':noise,'mode':args.mode,'start':args.start,'stop':args.stop,'step':args.step,'frames':args.frames,'target_errors':args.target_errors})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with args.output.with_suffix('.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['db','frames','bit_count','bit_errors','BER','BER_low','BER_high','SER','FER'])
        for p in result['points']: writer.writerow([p['db'],p['frames'],p['bit_count'],p['bit_errors'],p['ber'],*p['ber_interval'],p['ser'],p['fer']])
    message=f"Sweep complete={result['complete']}; points={len(result['points'])}; JSON={args.output}; CSV={args.output.with_suffix('.csv')}\n"
    log=ROOT/'logs/communications/sweep.log';log.parent.mkdir(parents=True,exist_ok=True);log.write_text(message,encoding='utf-8');print(message)


if __name__=='__main__': main()
