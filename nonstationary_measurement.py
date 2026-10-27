"""Summary-level synthetic measurements, not phase-scan refits."""
import math
import numpy as np
from environment_model import EnvironmentProcess

def deterministic_neighbors(xy, ib, phib, count):
    """Full sort avoids arbitrary kNN tie ordering, including the kth boundary.

    Rounded scaled squared distances define ties at 12 decimal places. Frozen
    CSV row index breaks ties. Sorting only a tree's returned k rows is NOT enough.
    """
    delta=(np.asarray(xy,dtype=float)-np.array([ib,phib]))/np.array([.65,6.])
    distance2=np.round(delta[:,0]**2+delta[:,1]**2,12)
    indices=np.arange(len(distance2))
    selected=np.lexsort((indices,distance2))[:min(count,len(indices))]
    weights=np.exp(-.5*np.minimum(distance2[selected],100.))
    if weights.sum()<1e-10:weights=np.ones(len(selected))
    return selected,weights/weights.sum()

class NonstationaryMeasurement:
    def __init__(self,base,settings):
        self.base=base;self.settings=settings;self.runs={};self.last={}
    def start(self,seed,run_id):
        if run_id in self.runs:raise ValueError('Repeated run id')
        streams=np.random.SeedSequence([int(seed),91039]).spawn(3)
        self.runs[run_id]=(EnvironmentProcess(seed,self.settings),*[np.random.default_rng(s) for s in streams])
    def draw(self,ib,phib,latent,run_id):
        env,noise,qc,diagnostic=self.runs[run_id];state=env.advance()
        inds,weights=deterministic_neighbors(self.base.data.xy,ib,phib,self.base.settings.n_neighbors)
        local=np.sum(self.base.sigmas[inds]*weights[:,None],axis=0)*self.base.settings.noise_scale
        # Retain the original floor; do not add full empirical spread a second time.
        sigma=np.maximum(local,np.asarray(state['extra_sigma_db']))
        error=noise.normal(size=2)*sigma
        observed=np.maximum(np.asarray(latent)+state['bias_db']+error,0.)
        # R2 templates carry spatial dependence. Environment degrades them, with noisy diagnostics.
        template_index=int(qc.choice(inds,p=weights))
        row=self.base.data.rows[template_index]
        def finite(key,fallback):
            try:v=float(row[key]);return v if math.isfinite(v) else fallback
            except (ValueError,TypeError,KeyError):return fallback
        severity=state['severity']
        r2=np.array([finite('amplitude_R2',.5),finite('complex_R2',.5)])
        r2=np.clip(r2-.12*severity+diagnostic.normal(0,.025,size=2),-1.,1.)
        baseline=state['baseline_component_pct']+float(diagnostic.normal(0,2.))
        flags=[]
        if abs(baseline)>10:flags.append('Absolute baseline amplitude drift must be at most 10%.')
        if r2[0]<=.6:flags.append('Amplitude-fit R2 must be strictly greater than 0.6.')
        if r2[1]<=.6:flags.append('Complex-fit R2 must be strictly greater than 0.6.')
        valid=not flags
        ci=[(max(0.,float(v-1.96*s)),float(v+1.96*s)) for v,s in zip(observed,sigma)]
        # Systematic bias is deliberately not included in illustrative fit intervals.
        diag=dict(amplitude_R2=float(r2[0]),complex_R2=float(r2[1]),baseline_amplitude_drift_percent=baseline,
                  diagnostics_source='synthetic_environment_conditioned_summary_not_a_refit')
        self.last[run_id]={**state,'sigma_db':sigma.tolist(),'measurement_error_db':error.tolist(),
                           'baseline_observed_pct':baseline,'qc_valid':valid,'template_index':template_index}
        return observed.tolist(),valid,flags,diag,ci,('illustrative_ci_scale','illustrative_ci_scale'),self.last[run_id]
