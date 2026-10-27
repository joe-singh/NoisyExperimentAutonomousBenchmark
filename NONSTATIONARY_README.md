> Historical development document. Start with [README.md](README.md) for the packaged release.

# Nonstationary measurement benchmark v1.1

This release adds `nonstationary_qc` to the native runner and offline simulator.
The hidden 240-point contrast landscape stays fixed. Measurement noise, bias,
baseline changes and QC reliability evolve during each campaign. This is a
summary-level, data-informed stress test, not a validated model of shielding,
resonator physics, or raw phase-scan fitting.


## v1.1 reproducibility fix

The nonstationary observation model now sorts all 240 candidate rows using scaled
squared distance rounded to 12 decimal places, then frozen CSV row index. This
resolves ties both inside the selected neighbours and at the selection boundary;
QC-template sampling no longer depends on cKDTree tie order. Original stationary
modes are unchanged. Minor floating-point differences across platforms may still
exist; this is not a guarantee of bitwise cross-platform equivalence for every
numerical operation.

Start a NEW batch under v1.1. Do not merge the v1 smoke trial into a v1.1 cohort.
The source/version checks intentionally reject resuming a v1 nonstationary batch.
The old trial remains valid as a v1 exploratory result. Environmental random
streams and difficulty parameters are unchanged, but observations and resulting
agent trajectories can change because template selection is now canonical.

For a harder first comparison, keep 50 measurements and use
`--disturbance-profile severe`. Compare matched seeds across profiles before
claiming increased difficulty. A separate 25-measurement-budget experiment tests
scarcity of measurements; it must not be pooled with the 50-measurement cohort.

## Installation and first campaign

Extract into a new folder; do not replace a folder running an active campaign.
Install the existing requirements in your Python environment. Keep `calibration`
next to the Python scripts. Use the same Codex setup as before. The macOS sandbox
preflight and tool audit remain. No model or hardware calls were made in development.

```bash
python native_blind_runner.py \
  --budget 50 --repeats 1 \
  --model gpt-6.1-sol --effort medium \
  --landscape qc_weighted --environment nonstationary_qc \
  --disturbance-profile moderate --objective dpa --seed 200 \
  --out codex_nonstationary_results
```

Use `--repeats 20` for a batch (seeds 200–219). Match profile, landscape, budget,
objective and seeds across models. Mild/moderate/severe are stress-test levels,
not established experimental regimes. Do not pool with the stationary leaderboard.

Offline checks, requiring no Codex:

```bash
python run_offline.py --policy adaptive --landscape qc_weighted \
  --environment nonstationary_qc --disturbance-profile moderate \
  --budget 50 --repeats 2 --seed 200 --out offline_nonstationary_results
python -m unittest discover -p 'test*.py' -v
python validate_nonstationary.py
```

The older Docker `blind_codex_runner.py` does not advertise this mode; use the
native runner for model campaigns.

## Evidence and assumptions

The supplied actions archive has 272 records and 27 readiness/control measurements
at requested Ib=10.5 uA, Phib=22.75 uA across five sessions. All 27 controls,
including QC rejections, contribute to descriptive scales. Two procedural failures
are excluded from acquisition-duration estimation. The input hash is retained in
`calibration/empirical_anchors.json`. Raw XY data are not required.

| Empirical quantity | Value |
|---|---:|
| DPA robust spread | 2.8731 dB |
| Complex robust spread | 1.1476 dB |
| Baseline-change robust spread | 14.2222 percentage points |
| Median completed non-retuning duration | 239.432 seconds |
| Observed control QC yield | 14/27 = 51.85% |

Robust spread is 1.4826 times median absolute deviation about the median. These
spreads mix fit error, drift, retuning and session changes; they do not identify
individual error components. Persistence, burst dynamics and global applicability
of this single-coordinate evidence remain assumptions.

The uploaded emulator already included the 243-coordinate archive and 245-attempt
CSV. We retain its frozen 240-point scoring map unchanged. Controls inform error
scales but are not inserted into the map. The smoothed map's value at the control
can differ substantially from the measured control median: this mode models
variability around the existing map, not absolute replay of the control signal.

## Generative model (all coefficients explicit)

A campaign starts quiet, with persistent states zero. A two-state Markov process
then has mean quiet/disturbed durations of 12/8 evaluations (about 48/32 minutes).
Two independent AR(1) bias states have coefficient 0.94; a signed baseline AR(1)
state has coefficient 0.65. Innovations give unit long-run variance. Initial
variance is consequently smaller. These dynamics are assumed, not fitted.

Let L be 0.5/1/1.5 for mild/moderate/severe. A burst accumulator decays by 0.55
per step and receives a uniform [1,2] increment with probability 0.04 per step.
Severity S = L * ((0.25 if quiet else 1) + burst accumulator).
For empirical contrast spread s_k and original local noise scale sigma_local,k:

- Persistent bias b_k = 0.65 L (1 + 0.5 * disturbed) s_k * AR_bias,k.
- Observation sigma_k = max(sigma_local,k, 0.65 S s_k).
- Observed contrast_k = max(0, map_k + b_k + sigma_k * normal_draw_k).

The maximum avoids adding the full observed spread on top of the local floor.
The 0.65 allocation is provisional, not an identified variance decomposition.
Zero clipping can cause positive mean error near low contrast. DPA and complex
innovations are independent but share severity; no measured covariance is claimed.

Synthetic baseline change = 14.2222 S * AR_baseline + normal(0,2) percentage points.
A nearby broad-map row supplies paired empirical R2 templates, sampled without
conditioning on QC. Each R2 is degraded by 0.12 S, perturbed by normal noise with
sigma 0.025, then clipped to [-1,1]. These are summary proxies, not refitted
phase-scan diagnostics. Spatial dependence comes from the nearby templates.

QC passes iff |baseline change| <=10%, amplitude R2 >0.6 and complex R2 >0.6.
Flags follow these thresholds exactly. This replaces the old independent QC coin
flip in this mode. Persistent contrast bias can escape QC. Illustrative intervals
include observation sigma but omit bias and do not have calibrated 95% coverage.

Dwell times, persistence and burst parameters are configurable through Python
`EnvironmentSettings`. The CLI selects frozen profile strengths. Environment
source hashes, settings and anchors are saved and checked at batch resumption;
a changed environment requires a new batch.

## Fairness, information and scoring

Independent RNG streams govern environment, measurement noise, template sampling
and diagnostic noise. For the same seed, environmental histories are independent
of coordinates, QC outcomes, model and API timing. Profiles share regime schedules
with different strengths. Different coordinates still give different observations.

Every attempted measurement advances simulated time by 239.432 seconds, including
QC failures. No API latency, moving optimum, waiting or recalibration action is
modelled. The 20 real retuning records are retained in the calibration table but
not used to invent a detuning-to-contrast law. Retuning needs a separate physical
mechanism and budget/time accounting in a future version.

Agents receive observations, QC flags, synthetic diagnostics, illustrative
intervals and elapsed simulated time. The initial prompt discloses persistent
measurement instability, fixed underlying landscape and omission of drift from
fit intervals. Seeds, true state and scoring never enter the prompt. Hidden
states go into `HIDDEN_GRADER_ONLY.jsonl`, outside the agent workspace. Existing
sandbox protection remains.

Primary score remains underlying map contrast at the final nominated coordinate.
It measures identifying a good bias under unstable observations, not sustained
physical performance under a moving optimum. Repeats each consume one of the 50
measurements. The reference maximum is still the same discretized map maximum.

`RUN_CONFIG.json` and `summary.json` contain environment provenance. Batches
record and check it on resume. An interrupted campaign restarts with its original
seed and a fresh conversation; mid-campaign recovery remains unsupported.

## Validation

- 44 unit tests pass, including persistence, replay, public-field separation,
  diagnostics/QC consistency, and scenario matching across different coordinates.
- Old/new public JSON outputs match exactly for 150 measurements across the
  original clean/noisy/noisy_qc modes, with seed 216 and identical coordinates.
- Native mock batch: two five-measurement trials, paused after the first and
  resumed successfully. This does not test macOS Seatbelt or a live Codex call.
- Offline adaptive-policy smoke run: 50 measurements completed in the new mode.
- Fixed-control ensemble: 100 campaigns per profile, seeds 200–299, 50 samples each:

| Profile | QC pass fraction | Median longest QC-failure streak |
|---|---:|---:|
| Mild | 87.98% | 2 |
| Moderate | 72.52% | 4 |
| Severe | 60.38% | 6 |

The real controls passed 51.85%; these are not fitted reproductions. No profile
was adjusted based on agent rankings. Whether this environment lowers model
scores or changes rankings is not yet established.

`validation/measured_controls.pdf` shows real sparse controls with session gaps.
`validation/synthetic_example.pdf` shows predetermined fixed-control seed 200 and
host-only states. `ensemble_checks.json` contains the software checks.

Regenerate empirical anchors from the original supplied archive with:

```bash
python calibrate_nonstationary.py /path/to/actions-20261018T022004Z-1-001.zip
```

The package includes source, source summaries, docs and validation outputs.
Historical model outputs and virtual environments are not bundled.
