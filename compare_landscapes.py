"""Compare spatially-held-out 240-point DPA/complex landscape reconstructions.

No instrument access, no new raw-data fits, no LLM/API use. Use from DPA-Emulator:
    python compare_landscapes.py
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
import numpy as np
from scipy.spatial import cKDTree

from landscape_model import (BroadMapData, FrozenLandscape, MODEL_NAMES,
                             BANDWIDTH_IB_UA, BANDWIDTH_PHIB_UA,
                             REJECTED_FIT_WEIGHT)


def spatial_groups(xy):
    # Fixed physical rectangles: four Ib bands x five Phib bands = 20 blocks.
    a = np.clip(np.floor((xy[:, 0] - 10.0) / 1.25).astype(int), 0, 3)
    b = np.clip(np.floor(xy[:, 1] / 14.0).astype(int), 0, 4)
    return a * 5 + b


def spatial_fold_indices(data, seed=113, nfold=5):
    # Shuffle whole geographical blocks into balanced folds by point count.
    groups = spatial_groups(data.xy)
    sizes = {int(g): int(np.sum(groups == g)) for g in np.unique(groups)}
    rng = np.random.default_rng(seed)
    order = list(rng.permutation(sorted(sizes)))
    buckets = [[] for _ in range(nfold)]
    counts = [0] * nfold
    for g in order:
        j = int(np.argmin(counts))
        buckets[j].append(g)
        counts[j] += sizes[g]
    for fold, ids in enumerate(buckets):
        test = np.flatnonzero(np.isin(groups, ids))
        train = np.flatnonzero(~np.isin(groups, ids))
        yield fold, train, test, ids


def cv_predictions(data):
    records = []
    fold_details = []
    for fold, train, test, group_ids in spatial_fold_indices(data):
        test_valid = test[data.valid[test]]
        fold_details.append({'fold': fold, 'test_samples': len(test),
                             'test_qc_valid': len(test_valid), 'blocks': [int(g) for g in group_ids]})
        if len(test_valid) == 0:
            continue
        for name in MODEL_NAMES:
            model = FrozenLandscape(data, name, train_idx=train)
            pred = model.predict_many(data.xy[test_valid])
            for idx, pair in zip(test_valid, pred):
                for col, metric in enumerate(('dpa', 'complex')):
                    actual = float(data.z[idx, col])
                    records.append({'fold': fold, 'model': name, 'metric': metric,
                                    'row_index': int(idx), 'Ib_uA': float(data.xy[idx, 0]),
                                    'Phib_uA': float(data.xy[idx, 1]),
                                    'measured_db': actual, 'predicted_db': float(pair[col]),
                                    'error_db': float(pair[col] - actual)})
            if name == 'linear_all':
                fold_details[-1]['linear_fallbacks_qc_valid'] = model.fallback_count
    return records, fold_details


def summarize_cv(records):
    stats = {}
    for name in MODEL_NAMES:
        stats[name] = {}
        for metric in ('dpa', 'complex'):
            r = [q for q in records if q['model'] == name and q['metric'] == metric]
            err = np.array([q['error_db'] for q in r])
            stats[name][metric] = {'n_valid_held_out': int(len(err)),
                                   'mae_db': float(np.mean(np.abs(err))),
                                   'median_abs_error_db': float(np.median(np.abs(err))),
                                   'rmse_db': float(np.sqrt(np.mean(err**2))),
                                   'p90_abs_error_db': float(np.percentile(np.abs(err), 90))}
    return stats



def paired_spatial_bootstrap(records, reps=2500, seed=321):
    """Exploratory 20-block paired bootstrap on differences in absolute error."""
    result = {}
    rng = np.random.default_rng(seed)
    for metric in ('dpa', 'complex'):
        subset = [r for r in records if r['metric'] == metric]
        e = {(r['row_index'], r['model']): abs(r['error_db']) for r in subset}
        example = {r['row_index']: r for r in subset}
        indices = sorted(example)
        reference = np.array([e[(i, 'linear_all')] for i in indices])
        blocks = spatial_groups(np.array([[example[i]['Ib_uA'], example[i]['Phib_uA']] for i in indices]))
        unique_blocks = np.unique(blocks)
        result[metric] = {}
        for model in ('qc_weighted_smooth', 'qc_only_smooth'):
            other = np.array([e[(i, model)] for i in indices])
            diff = other - reference  # positive means model did worse than V0
            sampled = []
            for _ in range(reps):
                sel = rng.choice(unique_blocks, len(unique_blocks), replace=True)
                idx = np.concatenate([np.flatnonzero(blocks == group) for group in sel])
                sampled.append(float(np.mean(diff[idx])))
            lo, hi = np.percentile(sampled, [2.5, 97.5])
            result[metric][model] = {
                'mean_excess_MAE_over_linear_db': float(np.mean(diff)),
                'paired_20block_bootstrap_95pct_interval_db': [float(lo), float(hi)],
                'bootstrap_resamples': reps,
            }
    return result


def draw_qc_distance(data, out):
    from scipy.spatial import cKDTree
    ib, ph = np.meshgrid(np.linspace(10, 15, 260), np.linspace(0, 70, 400), indexing='ij')
    g = np.column_stack([ib.ravel(), ph.ravel()])
    # Measured in coarse-grid spacing units; this is coverage, NOT fit error or sigma.
    scale = np.array([5/9, 5.0])
    tree = cKDTree(data.xy[data.valid] / scale)
    d = tree.query(g / scale)[0].reshape(ib.shape)
    fig, ax = plt.subplots(figsize=(9.3, 5.8))
    m = ax.pcolormesh(ph, ib, d, shading='auto', cmap='viridis', rasterized=True)
    ax.scatter(data.xy[data.valid, 1], data.xy[data.valid, 0],
               marker='.', s=14, color='black', label='QC-passing samples')
    ax.set(xlabel='SQUID flux bias $\\Phi_b$ (µA)', ylabel='SQUID current bias $I_b$ (µA)',
           title='Distance to nearest QC-passing measurement (support proxy)',
           xlim=(0, 70), ylim=(10, 15))
    fig.colorbar(m, ax=ax, label='Distance (coarse-grid spacing units)')
    ax.legend(loc='lower right')
    fig.savefig(out, dpi=200, bbox_inches='tight')
    plt.close(fig)


def write_csv(path, records):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)


def draw_maps(data, out):
    ib, phib = np.meshgrid(np.linspace(10, 15, 200), np.linspace(0, 70, 320), indexing='ij')
    grid = np.column_stack((ib.ravel(), phib.ravel()))
    fig, axes = plt.subplots(2, 3, figsize=(17.2, 9.5), sharex=True, sharey=True)
    fig.suptitle('Frozen reference landscape candidates · 240 broad points · exploratory models', fontsize=15)
    for j, name in enumerate(MODEL_NAMES):
        model = FrozenLandscape(data, name)
        values = model.predict_many(grid).reshape(200, 320, 2)
        for k, metric in enumerate(('DPA contrast', 'Complex contrast')):
            ax = axes[k, j]
            raw = data.z[:, k]
            lo = max(0.2, float(raw.min()))
            hi = float(raw.max())
            mesh = ax.pcolormesh(phib, ib, values[:, :, k], shading='auto',
                                 cmap='viridis', norm=LogNorm(vmin=lo, vmax=hi), rasterized=True)
            if j == 0:
                ax.set_ylabel('SQUID current bias $I_b$ (µA)')
            if k == 1:
                ax.set_xlabel('SQUID flux bias $\\Phi_b$ (µA)')
            if k == 0:
                ax.set_title({'linear_all':'V0: all 240, linear',
                              'qc_weighted_smooth':'QC-weighted kernel',
                              'qc_only_smooth':'91 QC-pass kernel'}[name])
            # Same row-specific color normalization across all three methods.
            cb = fig.colorbar(mesh, ax=ax, shrink=.8, pad=.015)
            cb.set_label(metric+' (dB; logarithmic colors)', fontsize=8)
            ax.set_ylim(10, 15)
            ax.set_xlim(0, 70)
            ax.grid(alpha=.16)
    fig.subplots_adjust(top=.89, wspace=.34, hspace=.23)
    fig.savefig(out, dpi=180, bbox_inches='tight')
    plt.close(fig)


def draw_coverage(data, out):
    fig, ax = plt.subplots(figsize=(9.2, 5.8))
    rejected = ~data.valid
    ax.scatter(data.xy[rejected, 1], data.xy[rejected, 0], marker='x', s=30,
               linewidths=.9, alpha=.65, label='QC-rejected fit (%d)' % rejected.sum())
    ax.scatter(data.xy[data.valid, 1], data.xy[data.valid, 0], facecolors='none',
               edgecolors='black', s=35, linewidths=1.0,
               label='QC-passing fit (%d)' % data.valid.sum())
    for y in np.linspace(10, 15, 5)[1:-1]: ax.axhline(y, ls=':', lw=.65, alpha=.4)
    for x in np.linspace(0, 70, 6)[1:-1]: ax.axvline(x, ls=':', lw=.65, alpha=.4)
    ax.set(xlabel='SQUID flux bias $\\Phi_b$ (µA)', ylabel='SQUID current bias $I_b$ (µA)',
           title='Broad-map QC coverage and cross-validation spatial blocks',
           xlim=(-1, 71), ylim=(9.9, 15.1))
    ax.legend(loc='upper center', ncol=2)
    fig.savefig(out, dpi=200, bbox_inches='tight')
    plt.close(fig)


def draw_cv(records, out):
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.7), sharey=True)
    labels = ['V0 all-linear', 'QC-weighted', 'QC-only']
    for ax, metric in zip(axes, ('dpa', 'complex')):
        vals = [np.abs(np.array([r['error_db'] for r in records if r['metric'] == metric and r['model'] == model]))
                for model in MODEL_NAMES]
        ax.boxplot(vals, tick_labels=labels, showfliers=True, whis=(5, 95))
        ax.set_title(metric.upper() + ' · held-out QC-passing points')
        ax.set_ylabel('Absolute prediction error (dB)')
        ax.grid(axis='y', alpha=.25)
    fig.suptitle('Spatially blocked out-of-sample prediction errors (5 folds)')
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches='tight')
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--csv', default='level2_emulator_240_snapshot.csv')
    p.add_argument('--out', default='landscape_results')
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    data = BroadMapData(args.csv)
    rows, fold_info = cv_predictions(data)
    write_csv(out/'heldout_predictions.csv', rows)
    scores = summarize_cv(rows)
    bootstrap = paired_spatial_bootstrap(rows)
    meta = {'csv_sha256': data.sha256, 'n_total':len(data.rows),
            'n_qc_passing':int(data.valid.sum()), 'n_qc_rejected':int((~data.valid).sum()),
            'model_names':MODEL_NAMES,
            'bandwidth_Ib_uA':BANDWIDTH_IB_UA,
            'bandwidth_Phib_uA':BANDWIDTH_PHIB_UA,
            'rejected_fit_weight':REJECTED_FIT_WEIGHT,
            'heldout_scores':scores, 'paired_block_bootstrap': bootstrap, 'folds':fold_info,
            'score_population':'only QC-passing held-out records',
            'caveat':'QC validity is not independent of contrast, drift, or bias; model is not ground truth.'}
    (out/'validation_metrics.json').write_text(json.dumps(meta, indent=2)+'\n')
    print('Loaded %d broad points: %d QC pass, %d QC reject.' %
          (len(data.rows), data.valid.sum(), (~data.valid).sum()))
    print('Original CSV SHA256: '+data.sha256)
    print('Spatially blocked CV: test blocks held out entirely; evaluate only their QC-passing measurements.')
    for metric in ('dpa', 'complex'):
        print('\n%-23s %-13s %-12s %-12s' % (metric.upper(), 'MAE (dB)', 'RMSE (dB)', 'P90 AE (dB)'))
        for name in MODEL_NAMES:
            s = scores[name][metric]
            print('%-23s %-13.2f %-12.2f %-12.2f' %
                  (name, s['mae_db'], s['rmse_db'], s['p90_abs_error_db']))
    draw_maps(data, out/'landscape_comparison.png')
    draw_coverage(data, out/'qc_coverage.png')
    draw_qc_distance(data, out/'qc_support_distance.png')
    draw_cv(rows, out/'heldout_errors.png')
    report = ['# Stage A: landscape reconstruction and held-out validation', '',
              '**Exploratory models — none is established physical truth.**', '',
              '- Original input: `level2_emulator_240_snapshot.csv`',
              '- SHA256: `%s`' % data.sha256,
              '- 240 spatial samples; 91 QC-pass, 149 QC-rejected.',
              '- DPA and complex contrasts are both modeled; never refitted from raw traces.',
              '- Models: linear interpolation over all points (V0); Gaussian kernel smoothing with rejected weight 0.20; Gaussian kernel smoothing of 91 QC-pass points only.',
              '- Fixed smoothing widths: Ib %.2f µA and flux %.2f µA. These are **assumptions**, not measured correlation lengths.' % (BANDWIDTH_IB_UA,BANDWIDTH_PHIB_UA),
              '- Five-fold **spatially blocked** cross-validation using 4 x 5 physical rectangles. The entire held-out block, including QC-invalid measurements, is removed from training.',
              '- Metrics computed ONLY on held-out QC-passing fits. Since QC is conditional on signal characteristics, these scores are not a model of all physical settings.',
              '- For V0, nearest-neighbor fallback is used outside the training convex hull **during blocked cross-validation**; this is counted below. The production V0 with all 240 points needs no fallback.',
              '- Kernel smoothers are bounded weighted averages in dB and can wash out narrow real resonances. QC-only leaves large parts of the domain underconstrained.',
              '', '## Results', '',
              '| Model | DPA MAE (dB) | DPA RMSE | Complex MAE | Complex RMSE |',
              '|---|---:|---:|---:|---:|']
    for name in MODEL_NAMES:
        a, b = scores[name]['dpa'], scores[name]['complex']
        report.append('| %s | %.2f | %.2f | %.2f | %.2f |' % (name, a['mae_db'], a['rmse_db'], b['mae_db'], b['rmse_db']))
    report += ['', '## Exploratory spatial-block bootstrap', '',
               'This resamples 20 physical blocks (not individual points), with the original fixed 5-fold predictions. Excess MAE is positive when a smoother is worse than V0. It is a sensitivity interval, not an unbiased confidence interval for the physical system.', '',
               '| Metric | Smoother | Excess MAE over V0 (dB) | 95% block-bootstrap interval (dB) |',
               '|---|---|---:|---:|']
    for metric in ('dpa', 'complex'):
        for model in ('qc_weighted_smooth', 'qc_only_smooth'):
            b = bootstrap[metric][model]
            lo, hi = b['paired_20block_bootstrap_95pct_interval_db']
            report.append('| %s | %s | %.2f | [%.2f, %.2f] |' % (metric, model, b['mean_excess_MAE_over_linear_db'], lo, hi))
    report += ['', '## Fold diagnostics', '',
               '| Fold | Held-out points | Held-out QC-pass | V0 outside-hull fallback | Spatial blocks |',
               '|---|---:|---:|---:|---|']
    for fold in fold_info:
        report.append('| %d | %d | %d | %d | %s |' %
                      (fold['fold'],fold['test_samples'],fold['test_qc_valid'],
                       fold.get('linear_fallbacks_qc_valid',0),','.join(map(str,fold['blocks']))))
    report += ['', '## Interpretation and next decisions', '',
               '1. Check whether the ranking of methods is similar for BOTH DPA and complex. If a model is excellent only for one, beware fit-specific artifacts.',
               '2. Inspect `qc_coverage.png` and `qc_support_distance.png`. A smooth map in regions without accepted data is **not evidence that the map is correct there**.',
               '3. Inspect per-point errors `heldout_predictions.csv`; averages can be dominated by a few real or anomalous high-contrast peaks.',
               '4. Never use this diagnostic comparison as an unbiased final benchmark of optimization agents; choosing a map using these scores creates model-selection uncertainty.',
               '5. Before adding noise, consider fitting a **distribution over plausible maps** and calibrating it with repeated actual bias-point measurements. Hold out agent local-patch data from primary map reconstruction to avoid preferential sampling.',
               '', '## Recreate', '',
               '```bash', 'python compare_landscapes.py', '```', '']
    (out/'STAGE_A_REPORT.md').write_text('\n'.join(report), encoding='utf-8')
    print('\nWrote diagnostics to '+str(out.resolve()))


if __name__ == '__main__':
    main()
