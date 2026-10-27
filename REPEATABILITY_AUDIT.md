> Historical development document. Start with [README.md](README.md) for the packaged release.

# Why the default noise model is provisional

Source: the three previously uploaded Level-1 experimental run archives (Astra Medium, Sol Medium, Astra Ultra), each with 50 `wrapper_result.json` measurements. Repeated groups are defined by identical **requested** `(Ib, Phib)` coordinates within each run; repeats across different run conditions are not pooled as identical conditions.

| Archive | Repeated coordinate groups | Number of observations in those groups |
|---|---:|---:|
| Astra Medium | 6 | 15 |
| Sol Medium | 1 | 3 |
| Astra Ultra | 4 | 15 |
| **Total** | **11** | **33** |

Across these selected repeat groups, the median absolute difference for all within-group pairs was **approximately 55.6 dB for DPA and 4.0 dB for complex contrast** (42 pairs total). These pairs are **not independent**, and are heavily concentrated around anomalously high-contrast hotspots. One should **not apply those variability figures globally**, particularly at ordinary bias points.

The default `noisy` and `noisy_qc` modes therefore use the broad-map profile-fit uncertainty scale (typical `sigma` ~0.81 dB DPA, ~0.54 dB complex across bounded estimates) as a **controlled, mild perturbation**, not as a realistic model of repeated measurements. The default also assumes uncorrelated DPA and complex errors because the available repeats do not identify a stable global joint error distribution.

The `--stress-hotspots` switch optionally introduces **uncalibrated** extreme DPA excursions for sensitivity analysis only; it is *not* fitted from the above repeat differences. This deliberately separates an interpretable base case from uncertain tail behavior.

The `noisy_qc` environment uses a position-dependent pass probability based on the broad-sweep QC labels: a 50/50 blend of the overall QC acceptance fraction and weighted nearby labels (up to 16 neighbors with scales 0.65 µA and 6 µA). That is a **design assumption**, not fitted sequential dependence. Given a pass/fail outcome, QC flags and diagnostic values are resampled from broadly nearby observed records. No drift state or correlated failure streaks are simulated at this stage.

## What remains unknown

- Between-run and time-dependent physical drift at fixed bias settings.
- Whether profile confidence bounds predict cross-acquisition fluctuations.
- Error correlation of DPA versus complex fit away from selected hotspots.
- Position- and time-dependent probability of failed measurements with correlated errors.
- Physical contrast at failed broad-map points; all three candidate maps are uncertain reconstructions.

No benchmark leaderboard should be treated as a definitive physical ranking until sensitivity to these assumptions has been quantified.
