"""Extract summary-level empirical anchors; no model-performance tuning.
Usage: python calibrate_nonstationary.py ACTIONS.zip --out calibration
"""
import argparse, csv, hashlib, json, zipfile
from pathlib import Path
from datetime import datetime
import numpy as np

def extract(path, out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    rows=[]
    with zipfile.ZipFile(path) as z:
        for name in sorted(n for n in z.namelist() if n.endswith('/intent.json') and '__MACOSX' not in n):
            i=json.loads(z.read(name));r=json.loads(z.read(name.replace('intent.json','wrapper_result.json')))
            m=r.get('metrics') or {};t=r.get('tuning') or {};b=m.get('baseline') or {}
            rows.append(dict(action_id=i['action_id'],session=i['session_id'],role=i['role'],Ib=i['Ib'],Phib=i['Phib'],
                started_utc=r['started_utc'],finished_utc=r.get('finished_utc'),status=r['status'],valid=r.get('valid_for_comparison',False),
                dpa=m.get('gain_fit',{}).get('contrast_db'),complex=m.get('contrast_uncertainty',{}).get('complex',{}).get('estimate_db'),
                baseline_change_pct=b.get('baseline_amplitude_change_percent'),baseline_before_mvrms=b.get('baseline_before_mvrms'),
                retuned=r.get('retuned_this_evaluation',False),probe_hz=t.get('probe_hz'),tuning_age_s=t.get('age_at_acquisition_s'),
                q_loaded=t.get('q_summary',{}).get('mean_q_loaded'),runner_version=i.get('runner_version'),control_policy=i.get('control_policy')))
    controls=[r for r in rows if r['role'] in ('readiness','periodic_control') and r['status']!='failed']
    def stats(k):
        a=np.array([r[k] for r in controls if r[k] is not None],float)
        return dict(n=len(a),median=float(np.median(a)),robust_sigma=float(1.4826*np.median(abs(a-np.median(a)))),min=float(a.min()),max=float(a.max()))
    durations=[(datetime.fromisoformat(r['finished_utc'])-datetime.fromisoformat(r['started_utc'])).total_seconds() for r in rows if r['finished_utc'] and not r['retuned'] and r['status']!='failed']
    result=dict(version='controls_summary_v1',source_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),n_actions=len(rows),n_controls=len(controls),
        control_bias_uA=[10.5,22.75],control_pass_fraction=sum(r['valid'] for r in controls)/len(controls),
        measurement_duration_s=float(np.median(durations)),dpa=stats('dpa'),complex=stats('complex'),baseline_change_pct=stats('baseline_change_pct'),
        caveats=['Control spread includes fit error, drift, retuning and session changes; it is not an identified noise variance.',
                 'No inferred persistence time, covariance, burst probability or causal shielding model.',
                 'Control noise scales at one bias do not establish global spatial dependence.'])
    (out/'empirical_anchors.json').write_text(json.dumps(result,indent=2)+'\n')
    for filename,rr in [('actions_summary.csv',rows),('controls_summary.csv',controls)]:
        with (out/filename).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rr)
    print(json.dumps(result,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('--out',type=Path,default=Path(__file__).with_name('calibration'));a=p.parse_args();extract(a.archive,a.out)
