"""Host-only persistent environment; empirical scales, assumed dynamics.
Each run has a private RNG independent of measurement/QC and coordinate choices.
"""
from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib,json,math
import numpy as np

VERSION='nonstationary_v1.1'
PROFILE_FACTORS={'mild':.5,'moderate':1.,'severe':1.5}

@dataclass(frozen=True)
class EnvironmentSettings:
    profile: str = 'moderate'
    quiet_mean_steps: float = 12.
    disturbed_mean_steps: float = 8.
    bias_rho: float = .94
    baseline_rho: float = .65
    burst_probability: float = .04
    burst_decay: float = .55
    def __post_init__(self):
        if self.profile not in PROFILE_FACTORS: raise ValueError('Unknown disturbance profile')
        for value in (self.quiet_mean_steps,self.disturbed_mean_steps):
            if not math.isfinite(value) or value<1:raise ValueError('Mean durations must be finite and >=1')
        for value in (self.bias_rho,self.baseline_rho,self.burst_decay):
            if not math.isfinite(value) or not 0<=value<1:raise ValueError('Persistence must be in [0,1)')
        if not 0<=self.burst_probability<=1:raise ValueError('Invalid burst probability')

class EnvironmentProcess:
    def __init__(self,seed,settings=None):
        self.settings=settings or EnvironmentSettings()
        self.rng=np.random.default_rng(np.random.SeedSequence([int(seed),71031]))
        p=Path(__file__).with_name('calibration')/'empirical_anchors.json'
        self.anchors=json.loads(p.read_text());self.anchor_hash=hashlib.sha256(p.read_bytes()).hexdigest()
        self.step=0;self.disturbed=False;self.bias=np.zeros(2);self.baseline=0.;self.burst=0.
    def advance(self):
        s=self.settings;r=self.rng;self.step+=1
        # Initial quiet condition and subsequent regime changes are declared assumptions.
        if self.step>1 and r.random()<1/(s.disturbed_mean_steps if self.disturbed else s.quiet_mean_steps):self.disturbed=not self.disturbed
        self.bias=s.bias_rho*self.bias+math.sqrt(1-s.bias_rho**2)*r.normal(size=2)
        self.baseline=s.baseline_rho*self.baseline+math.sqrt(1-s.baseline_rho**2)*r.normal()
        self.burst*=s.burst_decay
        if r.random()<s.burst_probability:self.burst+=float(r.uniform(1,2))
        level=PROFILE_FACTORS[s.profile]
        severity=level*((1. if self.disturbed else .25)+self.burst)
        scales=np.array([self.anchors[k]['robust_sigma'] for k in ('dpa','complex')])
        # Split observed spread into slow/fast components by assumption, not a fitted decomposition.
        bias_db=.65*level*(1+.5*self.disturbed)*scales*self.bias
        extra_sigma=.65*severity*scales
        baseline_pct=self.anchors['baseline_change_pct']['robust_sigma']*severity*self.baseline
        return dict(version=VERSION,step=self.step,elapsed_s=self.step*self.anchors['measurement_duration_s'],
                    disturbed=self.disturbed,severity=float(severity),burst=float(self.burst),
                    bias_db=bias_db.tolist(),extra_sigma_db=extra_sigma.tolist(),baseline_component_pct=float(baseline_pct))
    def provenance(self):
        source_hashes={n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in ('environment_model.py','nonstationary_measurement.py','measurement_model.py','offline_simulator.py')}
        return dict(version=VERSION,source_hashes=source_hashes,settings=asdict(self.settings),profile_factor=PROFILE_FACTORS[self.settings.profile],
                    empirical_anchor_sha256=self.anchor_hash,empirical_anchors=self.anchors,
                    assumptions='Geometric regime durations, AR(1) bias/baseline, decaying bursts; coefficients not fitted to temporal controls.',
                    clock='Fixed empirical median acquisition duration per evaluation; no API latency or explicit retuning cost.')
