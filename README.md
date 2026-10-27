# DPA emulator: noisy experimental search

Supporting emulator code for **The Autonomous Lab**, by Jyotirmai Singh.
Agents search a two-dimensional SQUID bias landscape reconstructed from experimental
measurements. The scored landscape is fixed; observations have synthetic noise,
persistent offsets, disturbed periods, bursts, and quality-control rejection.
This is an offline simulation: it does not connect to laboratory instruments.

## Install

Python **3.11 or newer** is required (the native runner imports `tomllib`).
From this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -v
```

## Run without an AI account

This reproduces the random-search policy used in the blog: 50 uniform independent
locations, nominate the highest QC-valid observed DPA, then score its underlying
contrast. If no measurement passes QC, nominate the first location.

```bash
python random_baseline.py --repeats 20 --seed 200 --out random_results
```

For a quick software check, use `--repeats 1`. `results/` contains the supplied
random-search and uncertainty-aware Bayesian-optimization results; it is not a
complete archive of the LLM benchmark.

The older `run_offline.py` provides additional illustrative policies and plots.
Its summaries are not substitutes for the blog's final-nomination benchmark.

```bash
python run_offline.py --policy adaptive --budget 50 --repeats 1 \
  --seed 200 --landscape qc_weighted --environment nonstationary_qc \
  --disturbance-profile severe --out offline_results
```

## Bayesian optimization

```bash
python -m pip install -r requirements-bo.txt
python bo_baseline.py --repeats 20 --seed 200 --out bo_results_uncertainty
```

Uses 10 Latin-hypercube initial locations, a scaled Matern-5/2 ARD GP,
reported measurement variances plus a fitted shared noise term, and log noisy
expected improvement. Only QC-valid observations train the GP. Final nomination
maximizes posterior mean among visited locations. It has no explicit drift model.
The supplied results record their original dependency versions; installing newer
versions may change numerical optimization and trajectories. See VALIDATION.md
for what was actually executed for this release, and VALIDATION_ENVIRONMENT.txt
for the tested package versions (the CPU Torch build uses the PyTorch CPU index).

## Native Codex agent campaigns (macOS)

Requires an authenticated Codex CLI compatible with the original runner (developed
against CLI 0.162.1). The native filesystem sandbox uses macOS Seatbelt. Do not
disable a failing preflight to obtain benchmark results. Model identifiers and
available reasoning settings depend on your account and CLI.

```bash
python native_blind_runner.py --model YOUR_MODEL_ID --effort medium \
  --budget 50 --repeats 20 --seed 200 --objective dpa \
  --landscape qc_weighted --environment nonstationary_qc \
  --disturbance-profile severe --out codex_native_results
```

For an account-free software test (not an agent benchmark or sandbox test):

```bash
python native_blind_runner.py --mock --budget 50 --repeats 2 --seed 200 \
  --landscape qc_weighted --environment nonstationary_qc \
  --disturbance-profile severe --out mock_results
```

The package does not contain the Claude runner or live instrument harness.

## Experimental definition

The blog's severe cohort uses `qc_weighted`, `nonstationary_qc`, `severe`, DPA,
50 measurements including repeats and QC failures, and seeds 200–219. Each agent
then nominates a coordinate. Its score is the noise-free map contrast at that
coordinate, not its largest observed measurement. Report means over campaigns.
The 240-point snapshot drives this simulation; agent-informed zoom-in points are
not used. Other included CSVs document the extraction history.

The 17.08 dB reference is an approximate grid maximum of the reconstructed map,
not a physical bound on the laboratory experiment. Noise parameters are informed
by controls but are not a calibrated generative model of the apparatus.
See NONSTATIONARY_README.md for equations and parameters, and
SQUID_Agent_Benchmark_Methodology.md for the protocol. Other Markdown files are
historical development notes and can describe earlier modes.

## Release scope and reproducibility

Core simulator, runner, calibration and scoring data are preserved from the
provided archive. This packaging adds this README, random-baseline reproduction,
dependency guidance, ignore rules and validation notes. Two personal Windows
log paths were removed from the optional 245-attempt archive. The canonical
240-point CSV and simulator Python sources were not changed.

Large agent logs, duplicate ZIPs, caches and Mac filesystem metadata are omitted.
Publishing a landscape allows future systems to learn it; this release supports
inspection and reproduction, not a permanently secret evaluation set.

No license is selected in this bundle. The author can choose one when publishing;
public visibility alone does not grant an open-source license.
