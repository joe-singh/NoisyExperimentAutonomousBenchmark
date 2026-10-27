> Historical development document. Start with [README.md](README.md) for the packaged release.

# Level-2 reference map: emulator-data audit

Source archive: `drive-download-20260930T002024Z-1-001.zip`

Snapshot timestamp (local): `2026-09-28T21:29:44-07:00`

## Extraction counts

- Scheduled grid/cell-centre points in the **archive**: **243** unique positions.
- Scheduled grid/cell-centre points in the **frozen map snapshot**: **240** positions.
- Additional positions completed after the frozen snapshot: **3**.
- Physical grid/cell-centre attempts in the archive (including replaced operational failures): **245**.
- Frozen-snapshot measurements passing canonical QC: **91 (37.9%)**.
- Frozen-snapshot measurements not passing canonical QC: **149 (62.1%)**.
- Original 240-point heatmap table reconciliation: **all 240 coordinates and both three-decimal contrast columns matched**.

| Population | Selected positions | QC passing | QC failing |
|---|---:|---:|---:|
| grid | 150 | 66 | 84 |
| cell_centres | 90 | 25 | 65 |

## Field availability and confidence intervals

Null CSV cells / JSON null indicate missing or unbounded quantities; they are not zero.

| Field | Present / 240 | QC passing subset present / 91 |
|---|---:|---:|
| Ib_actual_uA | 240 | 91 |
| Phib_actual_uA | 240 | 91 |
| DPA_dB | 240 | 91 |
| complex_dB | 240 | 91 |
| Gmax | 240 | 91 |
| Gmin | 240 | 91 |
| complex_Gmax | 240 | 91 |
| complex_Gmin | 240 | 91 |
| amplitude_R2 | 240 | 91 |
| complex_R2 | 240 | 91 |
| amplitude_residual_RMS | 240 | 91 |
| complex_residual_RMS | 240 | 91 |
| DPA_CI95_lower_dB | 240 | 91 |
| DPA_CI95_upper_dB | 217 | 83 |
| complex_CI95_lower_dB | 240 | 91 |
| complex_CI95_upper_dB | 234 | 88 |
| baseline_amplitude_drift_percent | 240 | 91 |
| baseline_phase_drift_deg | 240 | 91 |
| tuning_age_at_acquisition_s | 240 | 91 |
| probe_hz | 240 | 91 |
| pump_hz | 240 | 91 |

### CI status

The intervals are *approximate profile-fit 95% confidence sets*, not calibration/systematic error bars and not directly usable as independent per-query Gaussian noise standard deviations.

| Metric | Bounded | Upper-unbounded | Lower missing | Median bounded interval width (dB) |
|---|---:|---:|---:|---:|
| DPA | 217 | 23 | 0 | 3.174 |
| complex | 234 | 6 | 0 | 2.115 |

### QC failure reasons (non-exclusive)

- 101: Absolute baseline amplitude drift must be at most 10%.
- 77: Complex-fit R2 must be strictly greater than 0.6.
- 70: Amplitude-fit R2 must be strictly greater than 0.6.

## Recommendations for using these files

1. **Reproducibility baseline:** use the 240-point snapshot CSV to recreate the original heatmap. The original map used all fitted contrasts, including QC-invalid points. This visual baseline is not equivalent to a validated ground-truth physical landscape.
2. **Replay benchmark:** use the snapshot for historical anchoring, but do not treat QC-invalid contrast estimates as accurate truth. Model validity and missingness explicitly; compare against a QC-passing-only interpolation and alternative reconstructions as sensitivity checks.
3. **No spurious precision:** do not convert profile confidence interval half-width to Gaussian standard deviation without a defensible model, and do not assume pointwise errors are independent. The CI method fixes normalized baselines and omits slow drift/systematics.
4. **Bias-space weights:** account for nonuniform original sampling; evaluating percentiles over a dense uniform interpolation grid weights by physical bias-space area, not by raw measured point count.
5. **Avoid leakage:** do not use the 68 agent-targeted local-patch points as the *primary* replay surface. They can be used for sensitivity analysis or physical validation, with selection bias clearly stated.
6. **Temporal realism:** the file records timestamps and drift proxies, but a collection of one-shot bias measurements cannot identify a fully realistic stochastic noise/drift simulator. For claims about noisy-loop robustness, calibrate multiple plausible noise/dropout models and report sensitivity.
7. **Exact experiment replication:** keep the original zip. Its `actions/######/wrapper_result.json` files retain the full original schema; the extracted JSON intentionally keeps only the agent-relevant observation fields.

## File definitions

- `level2_emulator_240_snapshot.csv`: exactly the 240 scheduled broad-grid/midpoint points at the historical snapshot, flattened columns.
- `level2_emulator_91_qc_passing.csv`: the 91 QC-accepted rows from the historical 240-point snapshot, for a stricter sensitivity analysis.
- `level2_emulator_240_snapshot.json`: same 240 points in a typed, structured native JSON envelope, preserving nested original `metrics` and QC/timing fields useful for a wrapper emulator.
- `level2_emulator_243_archive.csv`: all 243 unique broad-sweep positions contained in this later archive; three rows are marked `snapshot_240_included=false`.
- `level2_emulator_attempts_245.csv`: all 245 original grid/midpoint attempts, including two superseded operational failures, so a future dropout model need not erase failure histories.
- `extract_level2_emulator.py`: reproducible extraction script, with source-location pointers and cross-check against the 240-point text snapshot.

## Additional archive measurements

- action 270, (14.722222, 32.500000) µA, finished 2026-09-29T04:29:45.847177+00:00
- action 271, (11.944444, 42.500000) µA, finished 2026-09-29T04:33:54.288493+00:00
- action 272, (10.277778, 12.500000) µA, finished 2026-09-29T04:37:58.972863+00:00
