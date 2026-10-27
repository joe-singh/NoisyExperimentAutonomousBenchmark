"""Run offline SQUID searches with selectable reconstructed landscapes and measurement modes."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import statistics

import numpy as np

from offline_simulator import OfflineSimulator, BOUNDS, LANDSCAPES
from measurement_model import ENVIRONMENTS


def propose_random(rng, history):
    return rng.uniform(*BOUNDS['Ib']), rng.uniform(*BOUNDS['Phib']), 'uniform exploratory query'


def get_contrast(result, objective='dpa'):
    if objective=='dpa': return float(result['metrics']['gain_fit']['contrast_db'])
    if objective=='complex': return float(result['metrics']['contrast_uncertainty']['complex']['estimate_db'])
    raise ValueError('objective must be dpa or complex')


def propose_adaptive(rng, history, objective='dpa'):
    """Handwritten adaptive baseline, NOT an LLM or Bayesian optimizer.

    QC-invalid data must not be used for ranking; the invalid outcome consumes
    an evaluation. The policy sees only its own agent-facing measurement history.
    """
    valid = [h for h in history if h['result']['valid_for_comparison']]
    if len(valid)<5 or rng.random()<.30:
        return propose_random(rng, history)
    best = max(valid,key=lambda h:get_contrast(h['result'],objective))
    parent = best['result']['requested_bias_uA']
    n=len(history)
    iw=max(.035,.85*(.97**n));pw=max(.30,13.0*(.97**n))
    ib=min(max(rng.gauss(parent['Ib'], iw),10),15)
    ph=min(max(rng.gauss(parent['Phib'], pw),0),70)
    return ib,ph,f'local refinement around best QC-valid observed {objective} ({parent["Ib"]:.4f}, {parent["Phib"]:.4f})'


def save_plot(sim, history, truth, output, objective='dpa'):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    ibs=np.linspace(10,15,115);phib=np.linspace(0,70,280)
    ig,pg=np.meshgrid(ibs,phib,indexing='ij')
    zz=sim.model.predict_many(np.c_[ig.ravel(),pg.ravel()]).reshape(*ig.shape,2)[:,:,0 if objective=='dpa' else 1]
    fig,axs=plt.subplots(1,3,figsize=(17.5,5.1))
    norm=LogNorm(vmin=max(.05,float(zz.min())),vmax=float(zz.max()))
    m=axs[0].pcolormesh(pg,ig,np.maximum(zz,.05),cmap='viridis',norm=norm,shading='auto')
    ph=np.array([h['decision']['Phib_uA'] for h in history]);ib=np.array([h['decision']['Ib_uA'] for h in history])
    valid=np.array([h['result']['valid_for_comparison'] for h in history])
    axs[0].plot(ph,ib,color='crimson',lw=1.3,alpha=.85)
    axs[0].scatter(ph[valid],ib[valid],s=23,facecolor='white',edgecolor='crimson',lw=.6,label='QC-valid')
    axs[0].scatter(ph[~valid],ib[~valid],s=30,marker='x',color='crimson',label='QC-rejected')
    axs[0].scatter(ph[0],ib[0],s=95,marker='D',edgecolor='crimson',facecolor='none',zorder=5)
    axs[0].set(xlabel='Flux bias (µA)',ylabel='Bias current (µA)',title=f'Trajectory · {sim.landscape_name}')
    axs[0].legend(loc='best',fontsize=8)
    fig.colorbar(m,ax=axs[0],label=f'Hidden {objective} map · dB (log color)')
    for k,ax in enumerate(axs[1:]):
        metric=('dpa','complex')[k]
        o=np.array([get_contrast(h['result'],metric) for h in history]); t=np.array([row[metric] for row in truth])
        q=np.where(valid,o,np.nan)
        running=[];best=-np.inf
        for v in q:
            if np.isfinite(v): best=max(best,v)
            running.append(best if np.isfinite(best) else np.nan)
        ax.scatter(np.arange(1,len(o)+1),q,s=16,color='tab:blue',alpha=.6,label='QC-valid observation')
        ax.scatter(np.flatnonzero(~valid)+1,o[~valid],s=23,color='tab:orange',marker='x',label='QC-invalid observation')
        ax.plot(np.arange(1,len(t)+1),np.maximum.accumulate(t),color='black',lw=1.5,label='Best hidden map value visited')
        ax.plot(range(1,len(o)+1),running,color='tab:blue',lw=1,label='Best accepted observation')
        ax.set(xlabel='Evaluation number',ylabel='Contrast (dB)',title=metric.upper()+' · true vs reported')
        ax.legend(loc='best',fontsize=8)
    fig.suptitle(f'OFFLINE EXPLORATORY MODEL · {sim.landscape_name} / {sim.environment} (not verified physical truth)',fontsize=10)
    fig.tight_layout()
    fig.savefig(output,dpi=160)
    plt.close(fig)


def run_one(sim, policy, seed, budget, outdir, dist, plot, objective='dpa', other_dist=None):
    if objective not in ('dpa','complex'):raise ValueError('objective must be dpa or complex')
    rng=random.Random(seed)
    outdir=Path(outdir)
    run_id=f'offline_{policy}_{objective}_{seed}_{outdir.name}'
    sim.start_run(run_id, seed)
    outdir.mkdir(parents=True,exist_ok=False)
    history=[];truth=[]
    with (outdir/'evaluations.jsonl').open('w',encoding='utf-8') as records, \
         (outdir/'HIDDEN_GRADER_ONLY.jsonl').open('w',encoding='utf-8') as hidden:
        for n in range(1,budget+1):
            if policy=='adaptive':ib,ph,rationale=propose_adaptive(rng,history,objective)
            elif policy=='random':ib,ph,rationale=propose_random(rng,history)
            else:raise ValueError('Unknown policy '+str(policy))
            # Hidden map scoring is separate from the agent-facing result.
            dpa_true, complex_true=sim.latent_at(ib,ph)
            result=sim.evaluate_bias_point(ib,ph,run_id,n)
            record={'evaluation':n,'decision':{'Ib_uA':ib,'Phib_uA':ph,'rationale':rationale},'result':result}
            history.append(record)
            records.write(json.dumps(record,allow_nan=False)+'\n')
            tr={'evaluation':n,'Ib_uA':ib,'Phib_uA':ph,'dpa':float(dpa_true),'complex':float(complex_true),
                'qc_valid':bool(result['valid_for_comparison'])}
            if sim.environment == 'nonstationary_qc': tr['environment_state']=sim.hidden_environment_state(run_id)
            truth.append(tr)
            hidden.write(json.dumps(tr,allow_nan=False)+'\n')

    dpa_ob=np.array([get_contrast(h['result'],'dpa') for h in history]); comp_ob=np.array([get_contrast(h['result'],'complex') for h in history]);
    dpa_true=np.array([t['dpa'] for t in truth]);comp_true=np.array([t['complex'] for t in truth]);valid=np.array([t['qc_valid'] for t in truth])
    if other_dist is None:other_dist=sim.reference_distribution(objective=('complex' if objective=='dpa' else 'dpa'))
    dpa_dist = dist if objective=='dpa' else other_dist
    comp_dist = dist if objective=='complex' else other_dist
    dpa_p=np.searchsorted(dpa_dist,dpa_true,side='right')/len(dpa_dist)*100
    comp_p=np.searchsorted(comp_dist,comp_true,side='right')/len(comp_dist)*100
    obj_p=dpa_p if objective=='dpa' else comp_p
    obs=dpa_ob if objective=='dpa' else comp_ob
    latent=dpa_true if objective=='dpa' else comp_true
    valid_indices=np.flatnonzero(valid)
    best_ob_idx=int(valid_indices[np.argmax(obs[valid])]) if valid.any() else None
    best_true_idx=int(np.argmax(latent))
    t10=np.flatnonzero(obj_p>=90)
    obsbest=float(obs[best_ob_idx]) if best_ob_idx is not None else None
    summary={
        'run_id':run_id,'seed':seed,'strategy':policy,'objective':objective,'budget':budget,
        'data_sha256':sim.sha256,'landscape':sim.landscape_name,'environment':sim.environment,
        'noise_scale':sim.settings.noise_scale,'hotspot_tails':sim.settings.hotspot_tails,
        'qc_valid_evaluations':int(valid.sum()),'qc_rejected_evaluations':int((~valid).sum()),
        # Main score is based on map value at visited coordinates, NOT noisy estimates.
        'best_latent_objective_db':float(latent.max()),
        'best_latent_dpa_db':float(dpa_true.max()),'best_latent_complex_db':float(comp_true.max()),
        'best_map_percentile':float(obj_p.max()),
        'best_dpa_map_percentile':float(dpa_p.max()),'best_complex_map_percentile':float(comp_p.max()),
        'top_10pct_queries':int((obj_p>=90).sum()),
        'top_10pct_dpa_queries':int((dpa_p>=90).sum()),'top_10pct_complex_queries':int((comp_p>=90).sum()),
        'first_top_10pct_evaluation':int(t10[0]+1) if t10.size else None,
        # Observed values are computed only over QC-accepted results.
        'best_valid_observed_objective_db':obsbest,
        'best_valid_observed_dpa_db':float(dpa_ob[valid].max()) if valid.any() else None,
        'best_valid_observed_complex_db':float(comp_ob[valid].max()) if valid.any() else None,
        'best_latent_objective_among_qc_valid_db':float(latent[valid].max()) if valid.any() else None,
        'best_observed_objective_evaluation':best_ob_idx+1 if best_ob_idx is not None else None,
        'best_latent_objective_evaluation':best_true_idx+1,
        # Backward-compatible old names now explicitly point at the accepted-observed values.
        'best_dpa_db':float(dpa_ob[valid].max()) if valid.any() else None,
        'best_complex_db':float(comp_ob[valid].max()) if valid.any() else None,
        'warning':'All landscapes are reconstructions, not independently verified physical truth.'
    }
    (outdir/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    (outdir/'emulator_config.json').write_text(json.dumps(sim.provenance(),indent=2)+'\n',encoding='utf-8')
    with (outdir/'trajectory.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f)
        w.writerow(['evaluation','Ib_requested_uA','Phib_requested_uA','DPA_observed_dB','complex_observed_dB',
            'valid_for_comparison','DPA_latent_map_dB','complex_latent_map_dB','DPA_map_percentile','complex_map_percentile',
            'objective','rationale'])
        for h,t,dp,cp in zip(history,truth,dpa_p,comp_p):
            w.writerow([h['evaluation'],t['Ib_uA'],t['Phib_uA'],get_contrast(h['result'],'dpa'),get_contrast(h['result'],'complex'),
                        t['qc_valid'],t['dpa'],t['complex'],float(dp),float(cp),objective,h['decision']['rationale']])
    if plot:save_plot(sim,history,truth,outdir/'trajectory.png',objective)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,default=Path(__file__).with_name('level2_emulator_240_snapshot.csv'))
    p.add_argument('--policy',choices=['random','adaptive'],default='adaptive')
    p.add_argument('--objective',choices=['dpa','complex'],default='dpa')
    p.add_argument('--landscape',choices=list(LANDSCAPES),default='original')
    p.add_argument('--environment',choices=ENVIRONMENTS,default='clean')
    p.add_argument('--disturbance-profile',choices=['mild','moderate','severe'],default='moderate')
    p.add_argument('--noise-scale',type=float,default=1.0,help='Multiplier on local profile-fit interval scales (exploratory)')
    p.add_argument('--stress-hotspots',action='store_true',help='Optional uncalibrated hotspot-tail sensitivity test; not part of the three default environments')
    p.add_argument('--budget',type=int,default=50)
    p.add_argument('--repeats',type=int,default=1)
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--out',type=Path,default=Path('offline_results'))
    p.add_argument('--no-plots',action='store_true')
    a=p.parse_args()
    if a.budget<1 or a.repeats<1:p.error('budget and repeats must be positive')
    sim=OfflineSimulator(a.data,landscape=a.landscape,environment=a.environment,
                         noise_scale=a.noise_scale,hotspot_tails=a.stress_hotspots,disturbance_profile=a.disturbance_profile)
    print(f'Loaded {len(sim.lookup)} broad-map values; {sim.n_qc_valid} pass original QC. Simulator QC: {a.environment}.')
    print('Data SHA256:',sim.sha256)
    if a.landscape=='original':
        for coords,expected in sim.lookup.items():
            if not np.allclose(sim.predict(*coords),expected,atol=1e-8):
                raise RuntimeError('Failed exact reproduction of original broad-map values')
        print('Verified reconstruction of all 240 stored fitted values.')
    dist=sim.reference_distribution(objective=a.objective)
    other=sim.reference_distribution(objective=('complex' if a.objective=='dpa' else 'dpa'))
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    root=a.out/f'{stamp}_{a.policy}_{a.objective}_{a.landscape}_{a.environment}_{a.seed}'
    if root.exists():raise FileExistsError(f'Existing results path {root}; use another --out or wait a second')
    root.mkdir(parents=True,exist_ok=False)
    summaries=[]
    for i in range(a.repeats):
        summary=run_one(sim,a.policy,a.seed+i,a.budget,root/f'run_{i+1:03d}',dist,not a.no_plots,a.objective,other)
        summaries.append(summary)
        print(f'Completed {i+1}/{a.repeats}: best latent {a.objective} = {summary["best_latent_objective_db"]:.2f} dB; QC accepted {summary["qc_valid_evaluations"]}/{a.budget}; top-decile={summary["top_10pct_queries"]}/{a.budget}')
    with (root/'all_runs.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(summaries[0]));w.writeheader();w.writerows(summaries)
    agg={'repeats':a.repeats,'policy':a.policy,'objective':a.objective,'budget':a.budget,'starting_seed':a.seed,
         **sim.provenance(),
         'median_best_latent_objective_db':statistics.median(s['best_latent_objective_db'] for s in summaries),
         'median_best_map_percentile':statistics.median(s['best_map_percentile'] for s in summaries),
         'median_qc_valid_evaluations':statistics.median(s['qc_valid_evaluations'] for s in summaries),
         'fraction_runs_visited_top_decile':sum(s['first_top_10pct_evaluation'] is not None for s in summaries)/len(summaries),
         'warning':'Exploratory surrogate: uncertainty and QC statistics are NOT validated repeatability predictions.'}
    (root/'aggregate_summary.json').write_text(json.dumps(agg,indent=2)+'\n',encoding='utf-8')
    print('\nAll done. Results:',root.resolve())
    print('Aggregate:',json.dumps(agg,indent=2))

if __name__=='__main__':main()
