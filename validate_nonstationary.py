"""No API calls. Fixed-control diagnostics and ensemble checks; not model rankings."""
from pathlib import Path
import csv,json
from datetime import datetime
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from offline_simulator import OfflineSimulator
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'validation'
def main():
    OUT.mkdir(exist_ok=True)
    data=ROOT/'level2_emulator_240_snapshot.csv'
    rows=list(csv.DictReader((ROOT/'calibration'/'controls_summary.csv').open()))
    fig,axes=plt.subplots(2,1,figsize=(12,7),sharex=True)
    t0=datetime.fromisoformat(rows[0]['started_utc'])
    for session in sorted({r['session'] for r in rows}):
        rr=[r for r in rows if r['session']==session];x=[(datetime.fromisoformat(r['started_utc'])-t0).total_seconds()/3600 for r in rr]
        axes[0].plot(x,[float(r['dpa']) for r in rr],'-o',label=f'Session {session}')
        axes[1].plot(x,[float(r['baseline_change_pct']) for r in rr],'-o')
        for xx,r in zip(x,rr):
            if r['valid']=='False':axes[0].scatter(xx,float(r['dpa']),marker='x',s=90,color='black',zorder=5)
    axes[0].set_ylabel('Fitted DPA contrast (dB)');axes[0].legend(ncol=5,fontsize=9)
    axes[1].set_ylabel('Baseline change (%)');axes[1].set_xlabel('Hours since first control (includes gaps between sessions)')
    for threshold in [-10,10]:axes[1].axhline(threshold,ls='--',color='gray')
    for ax in axes:ax.grid(alpha=.2)
    fig.suptitle('Measured fixed-bias controls: Ib = 10.5 µA, Phib = 22.75 µA\nBlack crosses: QC rejected; lines connect sparse controls within each session',fontsize=13)
    fig.tight_layout(rect=[0,0,1,.93])
    for ext in ['png','pdf']:fig.savefig(OUT/f'measured_controls.{ext}',dpi=180)
    plt.close(fig)
    sim=OfflineSimulator(data,'qc_weighted','nonstationary_qc');sim.start_run('demo',200)
    results=[];states=[]
    for n in range(1,51):
        results.append(sim.evaluate_bias_point(10.5,22.75,'demo',n));states.append(sim.hidden_environment_state('demo'))
    fig,ax=plt.subplots(3,1,figsize=(12,8),sharex=True);x=np.arange(1,51);y=[r['metrics']['gain_fit']['contrast_db'] for r in results]
    ax[0].plot(x,y,'o-',ms=4,label='Synthetic observed DPA');ax[0].axhline(sim.latent_at(10.5,22.75)[0],ls='--',color='black',label='Fixed underlying map value')
    bad=[j for j,r in enumerate(results) if not r['valid_for_comparison']];ax[0].scatter(x[bad],np.array(y)[bad],marker='x',color='red',s=65,label='QC rejected');ax[0].legend(fontsize=9,ncol=3);ax[0].set_ylabel('Contrast (dB)')
    ax[1].plot(x,[s['bias_db'][0] for s in states],label='Hidden DPA bias (dB)');ax[1].plot(x,[s['sigma_db'][0] for s in states],label='Hidden DPA noise sigma (dB)');ax[1].legend(fontsize=9);ax[1].set_ylabel('Hidden disturbances')
    ax[2].plot(x,[s['baseline_observed_pct'] for s in states]);ax[2].axhline(10,ls='--',color='gray');ax[2].axhline(-10,ls='--',color='gray');ax[2].set_ylabel('Synthetic baseline change (%)');ax[2].set_xlabel('Evaluation (each approximately four simulated minutes)')
    for a in ax:
        a.grid(alpha=.2)
        for j,s in enumerate(states):
            if s['disturbed']:a.axvspan(j+.5,j+1.5,color='orange',alpha=.12)
    fig.suptitle('Synthetic nonstationary example — moderate profile, seed 200\nFixed control bias; shaded regions are hidden disturbed periods',fontsize=13)
    fig.tight_layout(rect=[0,0,1,.93])
    for ext in ['png','pdf']:fig.savefig(OUT/f'synthetic_example.{ext}',dpi=180)
    plt.close(fig)
    summary={}
    for profile in ['mild','moderate','severe']:
        sim=OfflineSimulator(data,'qc_weighted','nonstationary_qc',disturbance_profile=profile)
        yields=[];streaks=[];errors=[]
        for seed in range(200,300):
            rid=str(seed);sim.start_run(rid,seed);good=0;streak=0;longest=0
            for n in range(1,51):
                r=sim.evaluate_bias_point(10.5,22.75,rid,n);passed=r['valid_for_comparison'];good+=passed
                streak=0 if passed else streak+1;longest=max(streak,longest)
                errors.append(r['metrics']['gain_fit']['contrast_db']-sim.latent_at(10.5,22.75)[0])
            yields.append(good/50);streaks.append(longest)
        summary[profile]=dict(campaigns=100,seed_range=[200,299],control_pass_fraction=float(np.mean(yields)),median_longest_qc_failure_streak=float(np.median(streaks)),dpa_error_p05_p50_p95=np.percentile(errors,[5,50,95]).tolist())
    summary['interpretation']='Fixed-control software sanity checks, not fitted reproduction of experimental statistics and not agent benchmark results.'
    (OUT/'ensemble_checks.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
