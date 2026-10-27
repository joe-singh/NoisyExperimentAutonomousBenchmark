"""Exploratory offline observation model for the 240-point SQUID benchmark.

Fit-interval noise is *not* measured repeatability. QC behavior is resampled from
broad-sweep diagnostics and is *not* a validated conditional physical failure model.
Never import hardware modules, or expose latent values to an agent.
"""
from __future__ import annotations
import json
import math
from dataclasses import dataclass
import numpy as np
from scipy.spatial import cKDTree

ENVIRONMENTS = ('clean', 'noisy', 'noisy_qc', 'nonstationary_qc')


@dataclass(frozen=True)
class ModelSettings:
    noise_scale: float = 1.0
    # Global QC prior and a local nearest-neighbor smoother. Their 50/50 blend
    # prevents extreme zero/one failure probabilities at sparse sites.
    qc_global_prior_weight: float = .50
    n_neighbors: int = 16
    # Optional sensitivity-only rare event mode (disabled in the three defaults).
    hotspot_tails: bool = False
    hotspot_threshold_db: float = 15.0
    hotspot_chance: float = 0.12


class MeasurementModel:
    def __init__(self, broad_data, settings=None):
        self.data = broad_data
        self.settings = settings or ModelSettings()
        self.rng_by_run = {}
        self.row_count = len(broad_data.rows)
        self.tree = cKDTree(broad_data.xy / np.array([.65, 6.0]))
        self.global_pass_rate = float(np.mean(broad_data.valid))
        self.sigmas = np.empty((self.row_count, 2), float)
        for k, prefix in enumerate(('DPA', 'complex')):
            vals = []
            for row in broad_data.rows:
                lo, hi = row.get(prefix+'_CI95_lower_dB'), row.get(prefix+'_CI95_upper_dB')
                try:
                    width = (float(hi)-float(lo))/3.92
                    vals.append(width if np.isfinite(width) and width>0 else np.nan)
                except (ValueError, TypeError):
                    vals.append(np.nan)
            a = np.array(vals)
            fallback = float(np.nanmedian(a))
            self.sigmas[:, k] = np.clip(np.where(np.isfinite(a), a, fallback), .25, 5.0)
        self.valid_indices = np.flatnonzero(broad_data.valid)
        self.invalid_indices = np.flatnonzero(~broad_data.valid)

    def start(self, seed, run_id):
        if run_id in self.rng_by_run:
            raise ValueError('Repeated simulator run id')
        self.rng_by_run[run_id] = np.random.default_rng(int(seed))

    def _neighbors(self, ib, phib):
        dd, ii = self.tree.query([ib/.65, phib/6.0], k=min(self.settings.n_neighbors, self.row_count))
        dd = np.atleast_1d(dd)
        ii = np.atleast_1d(ii)
        weights = np.exp(-.5 * np.minimum(dd, 10)**2)
        if weights.sum() < 1e-10:
            weights = np.ones_like(dd)
        return ii, weights/weights.sum()

    def draw(self, ib, phib, latent, environment, run_id):
        if environment == 'nonstationary_qc':
            raise ValueError('Use OfflineSimulator for stateful nonstationary_qc')
        if environment not in ENVIRONMENTS:
            raise ValueError('Unknown environment: '+str(environment))
        if run_id not in self.rng_by_run:
            raise RuntimeError('Call start(seed, run_id) before simulation')
        rng = self.rng_by_run[run_id]
        z = np.asarray(latent, dtype=float)
        if environment == 'clean':
            return z.tolist(), True, [], {}, (None, None), ('not_simulated', 'not_simulated'), {'sigma_db':[0.,0.], 'event':'none', 'qc_pass_probability':1.0}
        inds, weights = self._neighbors(ib, phib)
        local_sig = np.sum(self.sigmas[inds] * weights[:, None], axis=0) * self.settings.noise_scale
        # Correlation is deliberately zero: limited and hotspot-selected repeats
        # do not establish a credible global DPA/complex covariance.
        observed = np.maximum(z + rng.normal(0.0, local_sig), 0.0)
        event = 'none'
        if self.settings.hotspot_tails and max(z)>self.settings.hotspot_threshold_db and rng.random()<self.settings.hotspot_chance:
            # Sensitivity analysis only. Not inferred globally from hotspot repeats.
            observed[0] = max(0., observed[0] + float(rng.choice([-1.,1.]))*abs(rng.normal(45., 12.)))
            event = 'hotspot_heavy_tail_stress'
        valid = True
        flags = []
        diag = {}
        p_valid = 1.0
        if environment == 'noisy_qc':
            local_rate = float(np.dot(weights, self.data.valid[inds].astype(float)))
            w = self.settings.qc_global_prior_weight
            p_valid = float(np.clip(w*self.global_pass_rate + (1-w)*local_rate, .05, .95))
            valid = bool(rng.random()<p_valid)
            # Empirical neighboring QC template supplies internally consistent
            # quality flags, baseline drift, R2 values. Diagnostics are synthetic,
            # *not* obtained by fitting the noisy synthetic contrast.
            eligible = inds[self.data.valid[inds] == valid]
            elig_weights = weights[self.data.valid[inds] == valid]
            if len(eligible)==0:
                eligible = self.valid_indices if valid else self.invalid_indices
                elig_weights = np.full(len(eligible), 1/len(eligible))
            else:
                elig_weights = elig_weights/elig_weights.sum()
            selected = self.data.rows[int(rng.choice(eligible, p=elig_weights))]
            if not valid:
                flags = json.loads(selected['quality_flags'])
                if not flags:
                    raise RuntimeError('Invalid template must have QC flags')
            def maybe_float(key):
                try:
                    return float(selected[key])
                except (ValueError, TypeError, KeyError):
                    return None
            diag = {'amplitude_R2':maybe_float('amplitude_R2'),
                    'complex_R2':maybe_float('complex_R2'),
                    'baseline_amplitude_drift_percent':maybe_float('baseline_amplitude_drift_percent'),
                    'diagnostics_source':'nearby_broad_QC_template_not_a_refit'}
        # Symmetric illustrative intervals: based on nearby stored profile-CI scale.
        # These are *not* 95% calibrated predictive intervals for repeated acquisition.
        ci = [(max(0., float(observed[k]-1.96*local_sig[k])), float(observed[k]+1.96*local_sig[k])) for k in range(2)]
        return observed.tolist(), valid, flags, diag, ci, ('illustrative_ci_scale','illustrative_ci_scale'), {
            'sigma_db':[float(i) for i in local_sig], 'event':event, 'qc_pass_probability':p_valid}
