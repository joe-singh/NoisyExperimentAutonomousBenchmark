"""Offline-only emulator of SQUID bias-point evaluation; never touches hardware."""
from __future__ import annotations
import json
import math
from pathlib import Path
import numpy as np
from scipy.interpolate import LinearNDInterpolator

from landscape_model import BroadMapData, FrozenLandscape, MODEL_NAMES
from measurement_model import MeasurementModel, ModelSettings, ENVIRONMENTS
from environment_model import EnvironmentSettings, EnvironmentProcess
from nonstationary_measurement import NonstationaryMeasurement

BOUNDS = {'Ib':(10.,15.), 'Phib':(0.,70.)}
LANDSCAPES = {'original':'linear_all', 'qc_weighted':'qc_weighted_smooth', 'qc_only':'qc_only_smooth'}


class OfflineSimulator:
    """Original signature, synthetic output. A hidden latent map is used for scoring.

    evaluate_bias_point returns only agent-visible information; callers must not
    expose `latent_at` or `reference_distribution` to the agent/model.
    """
    def __init__(self, csv_path, landscape='original', environment='clean', noise_scale=1.0, hotspot_tails=False, disturbance_profile="moderate", environment_settings=None):
        self.path = Path(csv_path).expanduser().resolve()
        self.data = BroadMapData(self.path)
        self.sha256 = self.data.sha256
        if landscape not in LANDSCAPES: raise ValueError('Invalid landscape: '+str(landscape))
        if environment not in ENVIRONMENTS: raise ValueError('Invalid environment: '+str(environment))
        self.landscape_name = landscape
        self.environment = environment
        self.model = FrozenLandscape(self.data, LANDSCAPES[landscape])
        self.settings = ModelSettings(noise_scale=float(noise_scale),hotspot_tails=bool(hotspot_tails))
        if not math.isfinite(float(noise_scale)) or float(noise_scale)<0: raise ValueError('noise_scale must be nonnegative and finite')
        self.measurement = MeasurementModel(self.data, self.settings)
        self.environment_settings = environment_settings or EnvironmentSettings(profile=disturbance_profile)
        self.nonstationary = NonstationaryMeasurement(self.measurement, self.environment_settings)
        if environment == "nonstationary_qc" and hotspot_tails:
            raise ValueError("Do not combine hotspot tails and nonstationary_qc")
        self.lookup = {tuple(map(float,p)):tuple(map(float,z)) for p,z in zip(self.data.xy, self.data.z)}
        self.n_qc_valid = int(self.data.valid.sum())
        self.coords = self.data.xy.copy()
        self.dpa_values = self.data.z[:,0].copy()
        self.complex_values = self.data.z[:,1].copy()
        # Backward-compatible map objects for clean demo plotting.
        self.dpa_interp = LinearNDInterpolator(self.coords,self.dpa_values)
        self.complex_interp = LinearNDInterpolator(self.coords,self.complex_values)
        self.next_number = {}
        self.started = set()

    def _check_bias(self, Ib, Phib):
        ib,phi = float(Ib),float(Phib)
        if not math.isfinite(ib) or not math.isfinite(phi) or not (10<=ib<=15 and 0<=phi<=70):
            raise ValueError('Requested biases outside Level-1 bounds or nonfinite')
        return ib,phi

    def predict(self, ib, phib):
        ib, phib = self._check_bias(ib,phib)
        # Preserve exact stored values at nodes of the original map.
        if self.landscape_name == 'original' and (ib,phib) in self.lookup:
            return self.lookup[(ib,phib)]
        return self.model.predict(ib,phib)

    latent_at = predict

    def start_run(self, run_id, seed):
        if run_id in self.started: raise ValueError('Run ID already started: '+run_id)
        self.measurement.start(seed, run_id)
        if self.environment == "nonstationary_qc": self.nonstationary.start(seed, run_id)
        self.started.add(run_id)
        self.next_number[run_id]=1

    def evaluate_bias_point(self, Ib, Phib, run_id, bias_point_number):
        if not isinstance(run_id,str) or not run_id or any(c in run_id for c in '/\\'):
            raise ValueError('run_id must be a nonempty simple string')
        if not isinstance(bias_point_number,int) or isinstance(bias_point_number,bool):
            raise ValueError('bias_point_number must be an integer')
        ib,phi = self._check_bias(Ib,Phib)
        if run_id not in self.started:
            # Compatible with direct single-point calls used in V0 examples.
            self.start_run(run_id, 0)
        expected = self.next_number[run_id]
        if bias_point_number!=expected:
            raise ValueError(f'Expected evaluation #{expected} for {run_id}, got #{bias_point_number}')
        latent = self.predict(ib,phi)
        if self.environment == "nonstationary_qc":
            obs,valid,flags,diagnostics,cis,statuses,info = self.nonstationary.draw(ib,phi,latent,run_id)
        else:
            obs,valid,flags,diagnostics,cis,statuses,info = self.measurement.draw(ib,phi,latent,self.environment,run_id)
        self.next_number[run_id]=expected+1
        dpa,comp = map(float,obs)
        gain = {'contrast_db':dpa,'gmax':1.0,'gmin':10**(-dpa/20),
                'r_squared_amplitude': diagnostics.get('amplitude_R2'),
                'amplitude_residual_rms':None,'solver_success':None}
        complex_fit = {'implied_gmax':1.0,'implied_gmin':10**(-comp/20),
                       'r_squared_complex':diagnostics.get('complex_R2'),
                       'complex_residual_rms':None}
        def uncertainty(k, value):
            if cis[k] is None:
                return {'estimate_db':value,'status':statuses[k]}
            return {'estimate_db':value, 'status':statuses[k], 'lower_db':cis[k][0],
                    'upper_db':cis[k][1], 'upper_unbounded':False}
        return {
            'schema_version':1,'procedure_version':('offline_nonstationary_v1.1' if self.environment=='nonstationary_qc' else 'offline_stage_b_v1'),
            **({'simulated_elapsed_s':info['elapsed_s']} if self.environment=='nonstationary_qc' else {}),
            'run_id':run_id,'bias_point_number':bias_point_number,
            'requested_bias_uA':{'Ib':ib,'Phib':phi},
            'actual_bias_uA':{'Ib':ib,'Phib':phi},
            'status':'completed' if valid else 'review_required',
            'valid_for_comparison':bool(valid),'quality_flags':flags,'errors':[],
            'metrics':{
                'gain_fit':gain,'complex_fit':complex_fit,
                'contrast_uncertainty':{'amplitude':uncertainty(0,dpa),'complex':uncertainty(1,comp)},
                'baseline':{'amplitude_drift_percent':diagnostics.get('baseline_amplitude_drift_percent')},
            },
            'emulator':{
                'kind':'offline_reconstructed_map','schema':'synthetic_not_physical',
                # NO latent scores or hidden seed in agent-visible result.
                'fit_diagnostics':('synthetic_environment_conditioned_summary_not_a_refit' if self.environment=='nonstationary_qc' else 'borrowed_nearby_empirical_QC_templates' if self.environment=='noisy_qc' else 'not_simulated'),
                'uncertainties':'illustrative_local_profile_interval_scales' if self.environment!='clean' else 'not_simulated',
                'warning':'Emulator output, not independent physical measurement.'},
        }

    def reference_distribution(self, ni=110, nf=250, objective='dpa'):
        if objective not in ('dpa','complex'): raise ValueError('objective must be dpa or complex')
        ibs=np.linspace(10,15,ni);ph=np.linspace(0,70,nf)
        x,y=np.meshgrid(ibs,ph,indexing='ij')
        z=self.model.predict_many(np.c_[x.ravel(),y.ravel()])[:,0 if objective=='dpa' else 1]
        if not np.isfinite(z).all(): raise RuntimeError('Unspecified modeled values')
        return np.sort(z)

    def hidden_environment_state(self, run_id):
        """Trusted host only. Never pass to the agent."""
        import copy
        return copy.deepcopy(self.nonstationary.last.get(run_id, {}))

    def provenance(self):
        return {**({'nonstationary':EnvironmentProcess(0,self.environment_settings).provenance()} if self.environment=='nonstationary_qc' else {}),
                'dataset_sha256':self.sha256,'landscape':self.landscape_name,
                'landscape_method':LANDSCAPES[self.landscape_name],
                'environment':self.environment,
                'noise_scale':self.settings.noise_scale,
                'hotspot_tails':self.settings.hotspot_tails,
                'qc_model':('thresholds on synthetic baseline and environment-degraded local R2 templates' if self.environment=='nonstationary_qc' else 'local empirical QC labels blended with global pass prior'),
                'noise_model':('persistent environmental bias, changing Gaussian scale and burst episodes' if self.environment=='nonstationary_qc' else 'independent Gaussian perturbations scaled by nearby profile CI widths'),
                'caveat':'No landscape is verified physical truth; noise and QC models are exploratory.'}
