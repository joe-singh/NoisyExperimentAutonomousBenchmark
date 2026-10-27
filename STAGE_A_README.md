> Historical development document. Start with [README.md](README.md) for the packaged release.

# Stage A: validated landscape candidates (no API needed)

This is a **non-destructive addition** to your existing `DPA-Emulator` folder. It does NOT modify `run_offline.py`, `offline_simulator.py`, your raw experiments or CSVs. We deliberately do **not** yet substitute one fitted landscape into the agents' benchmark.

## Run on macOS

1. Unzip the contents directly into your existing `DPA-Emulator` folder. It includes `landscape_model.py`, `compare_landscapes.py`, `test_stage_a.py`, and example diagnostics. It does **not** overwrite your existing 240-point CSV.
2. Open Terminal in your `DPA-Emulator` folder and activate the existing virtual environment: `source .venv/bin/activate`.
3. Run: `python compare_landscapes.py`.
4. Open the generated `landscape_results/` folder. Start with `landscape_comparison.png`, `qc_coverage.png`, `qc_support_distance.png`, and `STAGE_A_REPORT.md`.
5. Optional test: `python test_stage_a.py`.

This script uses only NumPy, SciPy and Matplotlib, already installed for the previous offline runner. It works offline on Mac, Windows, Linux. For different data locations use `--csv /path/to/file.csv` and `--out /path/to/folder`.

## What each model is

1. `linear_all`: exact V0 piecewise-linear DPA/complex surface over all 240 fitted values, **including 149 QC-invalid**. Exactly reproduces the measured contrast at all 240 nodes. A held-out block can become outside the training convex hull during CV; this script marks/quantifies nearest-neighbor fallback used only in that situation.
2. `qc_weighted_smooth`: Gaussian weighted smoother over all 240 fitted values with QC-pass point weight 1 and QC-reject weight 0.2. Two assumed bandwidths: 0.65 µA current and 6 µA flux.
3. `qc_only_smooth`: same Gaussian smoother using just 91 accepted fitted values. It may yield smooth but completely unsupported estimates where there are few accepted points.

The smoothing parameters are fixed **illustrative assumptions**. No claim is made that QC-invalid values are worthless or that the output is a physical ground truth. We use contrast dB as a target; neither fit has been reanalyzed at the raw trace level.

## Scientific validation

Five-fold **spatially blocked holdout**, 20 geographic groups divided into five folds. No points from a test block are used for training, including invalid measurements. Error scores are computed only at the QC-passing held-out points. The per-prediction error table and fold definitions are provided for audit.

This is deliberately harder than random K-fold on a smooth local interpolation, but the edge-block fallback and sparsity of QC-accepted points must be considered. With 91 accepted samples, these estimates can be unstable. We will **not** call a winning model validated physical ground truth without further checks.

## Next step after reviewing diagnostics

Choose a small **ensemble of plausible surfaces**, not a single winner, and then layer on a separate stochastic QC/noise model calibrated from the actual repeated agent measurements. Do not overwrite the old clean benchmark.
