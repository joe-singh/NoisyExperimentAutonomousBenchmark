"""Exploratory Stage-A frozen landscapes for the SQUID offline benchmark.

OFFLINE ONLY. No instrument integration; no fitted model is physical ground truth.
Models: linear_all (V0), qc_weighted_smooth, qc_only_smooth.

All coordinates in microamps, outputs in contrast dB. No random numbers.
"""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import numpy as np
from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator

MODEL_NAMES = ('linear_all', 'qc_weighted_smooth', 'qc_only_smooth')
# Fixed *exploratory* smoothing scales, not optimized using the held-out scores.
BANDWIDTH_IB_UA = 0.65
BANDWIDTH_PHIB_UA = 6.0
REJECTED_FIT_WEIGHT = 0.20


class BroadMapData:
    def __init__(self, csv_path):
        self.path = Path(csv_path).expanduser().resolve()
        self.sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.path.open('r', encoding='utf-8-sig', newline='') as f:
            self.rows = list(csv.DictReader(f))
        if len(self.rows) != 240:
            raise ValueError('Expected the 240-point frozen snapshot, got %s rows' % len(self.rows))
        self.xy = np.array([(float(r['Ib_requested_uA']), float(r['Phib_requested_uA'])) for r in self.rows])
        self.z = np.array([(float(r['DPA_dB']), float(r['complex_dB'])) for r in self.rows])
        self.valid = np.array([r['valid_for_comparison'].strip().lower() == 'true' for r in self.rows])
        if len(np.unique(self.xy, axis=0)) != len(self.xy):
            raise ValueError('Duplicate coordinates found in snapshot')
        if not np.isfinite(self.xy).all() or not np.isfinite(self.z).all():
            raise ValueError('Nonfinite coordinate / contrast')
        if self.valid.sum() != 91:
            raise ValueError('QC-valid count changed: %d (expected 91)' % self.valid.sum())


class FrozenLandscape:
    """Predicts two contrasts. Each model's training set can be restricted by train_idx."""

    def __init__(self, data: BroadMapData, kind: str, train_idx=None):
        if kind not in MODEL_NAMES:
            raise ValueError('Unknown model %s' % kind)
        self.kind = kind
        self.data = data
        indices = np.arange(len(data.xy)) if train_idx is None else np.asarray(train_idx, dtype=int)
        if kind == 'qc_only_smooth':
            indices = indices[data.valid[indices]]
        if len(indices) < 3:
            raise ValueError('Insufficient training samples')
        self.xy = data.xy[indices]
        self.z = data.z[indices]
        self.valid = data.valid[indices]
        self.train_idx = indices
        self.fallback_count = 0
        self.query_count = 0
        if kind == 'linear_all':
            self.linear = LinearNDInterpolator(self.xy, self.z)
            self.nearest = NearestNDInterpolator(self.xy, self.z)
        else:
            self.fit_weights = np.where(self.valid, 1.0, REJECTED_FIT_WEIGHT)

    def predict_many(self, coords):
        x = np.asarray(coords, dtype=float).reshape(-1, 2)
        if not np.isfinite(x).all():
            raise ValueError('Non-finite query coordinate')
        if ((x[:, 0] < 10-1e-9) | (x[:, 0] > 15+1e-9) |
            (x[:, 1] < -1e-9) | (x[:, 1] > 70+1e-9)).any():
            raise ValueError('Query outside original bias bounds')
        self.query_count += len(x)
        if self.kind == 'linear_all':
            out = np.asarray(self.linear(x), float).reshape(-1, 2)
            nan = ~np.isfinite(out).all(axis=1)
            if nan.any():
                # CV only: a held-out boundary block can be outside its training hull.
                # Explicitly count these nearest-neighbor fallbacks.
                out[nan] = np.asarray(self.nearest(x[nan])).reshape(-1, 2)
                self.fallback_count += int(nan.sum())
            return np.maximum(out, 0.0)
        out = np.empty((len(x), 2), dtype=float)
        # Bounded-memory local kernel averaging. Never extrapolates in dB beyond
        # training min/max. This smooths real narrow resonances as well as bad fits!
        for start in range(0, len(x), 1500):
            q = x[start:start + 1500]
            di = (q[:, None, 0] - self.xy[None, :, 0]) / BANDWIDTH_IB_UA
            dp = (q[:, None, 1] - self.xy[None, :, 1]) / BANDWIDTH_PHIB_UA
            logk = -0.5 * (di ** 2 + dp ** 2)
            # subtract row max for numerical safety in sparse regions
            weights = np.exp(logk - np.max(logk, axis=1, keepdims=True)) * self.fit_weights[None, :]
            out[start:start + len(q)] = (weights @ self.z) / weights.sum(axis=1, keepdims=True)
        return np.maximum(out, 0.0)

    def predict(self, ib, phib):
        return tuple(self.predict_many([[ib, phib]])[0].tolist())

    def nearest_qc_distance(self, coords):
        """Distance in units of broad-grid resolution; not calibrated uncertainty."""
        from scipy.spatial import cKDTree
        q = np.asarray(coords).reshape(-1, 2)
        scale = np.array([5.0 / 9.0, 5.0])
        tree = cKDTree(self.data.xy[self.data.valid] / scale)
        return tree.query(q / scale)[0]
