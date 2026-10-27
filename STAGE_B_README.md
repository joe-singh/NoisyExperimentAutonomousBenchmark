> Historical development document. Start with [README.md](README.md) for the packaged release.

# SQUID Offline Benchmark — Stage B (no API, no instrument access)

This is a **drop-in code update** for the earlier `DPA-Emulator` folder.

It integrates Stage A's three *exploratory* reconstructed landscapes into the original offline runner and adds two stochastic measurement modes. It does **not** alter your experimental CSV/JSON archives. It never connects to instruments or requires API keys.

## Installation (Mac)

1. **Keep your original files**. Make a copy of your `DPA-Emulator` directory if you want an easy rollback.
2. Unzip this bundle **into your existing `DPA-Emulator` folder**, replacing matching `.py` and README files if asked. The bundle contains **no experimental CSV**. Your existing `level2_emulator_240_snapshot.csv` stays untouched. The `offline_results/` folder stays untouched.
3. In Terminal:

```bash
cd ~/Desktop/DPA-Emulator
source .venv/bin/activate
python -m unittest test_offline test_stage_a test_stage_b -v
```

The tests expect `level2_emulator_240_snapshot.csv` next to the scripts. The 13 tests cover exact original-map recovery, cross-validation code, all nine landscape/environment combinations, seed reproducibility, and QC-aware scoring.

## First experiments

**1. Old V0 experiment (should still give 17.41 dB with seed 42):**

```bash
python run_offline.py --policy adaptive --landscape original --environment clean --objective dpa --seed 42 --budget 50
```

**2. Same original landscape, now with fit-interval-scale noise:**

```bash
python run_offline.py --policy adaptive --landscape original --environment noisy --objective dpa --seed 42 --budget 50
```

**3. QC-weighted landscape and stochastic QC:**

```bash
python run_offline.py --policy adaptive --landscape qc_weighted --environment noisy_qc --objective dpa --seed 42 --budget 50
```

**4. Repeat 20 times, using complex contrast as the optimization objective:**

```bash
python run_offline.py --policy adaptive --landscape qc_weighted --environment noisy_qc --objective complex --repeats 20 --seed 100 --budget 50
```

**5. Random baseline under the same nominal conditions:**

```bash
python run_offline.py --policy random --landscape qc_weighted --environment noisy_qc --objective complex --repeats 20 --seed 100 --budget 50
```

For a faster initial test use `--no-plots` (the trajectories and CSV logs still save). `--noise-scale 1.5` multiplies local observational fluctuations. The optional `--stress-hotspots` introduces deliberately **uncalibrated** sporadic large DPA errors in noisy modes for sensitivity testing; it should not be described as an empirical reconstruction.

## Available choices

`--landscape`:

- `original` — exact 240-point linear interpolant, **including 149 QC-invalid fitted observations**. V0-compatible.
- `qc_weighted` — Stage A's Gaussian smoother: QC-pass weight 1, QC-reject weight 0.20, bandwidth 0.65 µA (Ib) and 6 µA (Phib).
- `qc_only` — the Stage A kernel smoother over the 91 QC-passing observations only. Very uncertain in sparsely sampled areas.

`--environment`:

- `clean` — deterministic landscape values, every query passes synthetic QC. Identical behavior to original V0 for `original` / seed 42.
- `noisy` — independently perturbs DPA/complex by Gaussian draws with locally weighted 95% **profile-fit** interval half-widths divided by 1.96; all measurements pass synthetic QC.
- `noisy_qc` — same noise, plus a pass/fail decision from a spatially smoothed broad-sweep QC probability. Failed results consume budget and are not ranked by the adaptive policy. Flags, drift and R² are resampled from nearby matching-validity *measured diagnostic templates*.

These are **first-pass exploratory models, NOT experimentally validated noise distributions**. The fit-CI widths are not acquisition repeatability; Gaussian errors neglect heavy tails seen at high-contrast hotspots. The QC model has no sequential drift process, so it does **not** reproduce temporal streaks or season/session changes. Real hardware can also have bias quantization/readback errors not included here.

## Output structure

Each launch writes a unique subfolder under `offline_results/`, including:

- `all_runs.csv` — one row per completed 50-evaluation search; includes best **hidden-map (latent)** values and QC-passing observed values separately.
- `aggregate_summary.json` — medians and run-wide acceptance statistics.
- `run_001/evaluations.jsonl` — **agent-visible observation log**: decisions, reported contrasts, QC flags. **No hidden truth**.
- `run_001/HIDDEN_GRADER_ONLY.jsonl` — reconstructed true map value at the chosen coordinates. **Never expose this to an LLM agent or give the agent read access to this folder**.
- `run_001/trajectory.csv`, `run_001/trajectory.png` — plotting/evaluation artifacts; they contain hidden truth for benchmarking, so keep separate from the agent's view.
- `run_001/summary.json` and `run_001/emulator_config.json` — scores and reproducible provenance.

The hidden-map contrast is a *model prediction*, not measured physical ground truth. Primary metrics use **latent-map percentile of visited points**; observed-best is computed **only from QC-passing simulated measurements**. An invalid visit can still score as visiting a promising coordinate, but cannot be used as an accepted experimental gain.

`--objective dpa` preserves the original optimization target. `--objective complex` changes what the handcrafted adaptive search maximizes, but both fits and both scores are always recorded. `--policy adaptive` remains a very simple handcrafted optimizer, **not** an LLM agent or BO.

## Scientific scope and next stages

The broad sweep is 240 fitted results with 91 QC pass (37.9%). Stage A's spatially blocked cross-validation gave lower MAE for the original map than for two smoothing variants, but this is not evidence that rejected fits are physically correct. Keep all three reconstructions in a robustness sweep.

The archive also contains **50-evaluation agent runs with repeated identical setpoints**, but repetitions are concentrated in deliberately selected high-contrast regions; they cannot establish a global noise law. See `REPEATABILITY_AUDIT.md`.

**Next:** Validate measured-versus-simulated QC by *location* and run-length; explore a sequential session-drift model, and separately tune a conservative high-contrast heavy-tail model. Only then use this environment for strong model-ranking claims.
