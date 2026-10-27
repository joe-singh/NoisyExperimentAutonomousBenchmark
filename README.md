# Noisy Autonomous Experimental Search LLM Benchmark

Date Updated: 27 Oct 2026 

Supporting emulator code for [The Autonomous Lab](https://scholar.google.com/citations?user=C7_px7QAAAAJ&hl=en&authuser=3) Noisy Experiment Benchmark.
Agents search a two-dimensional SQUID bias landscape reconstructed from experimental
measurements. The scored landscape is fixed, based on real measurements, and observations have synthetic noise,
persistent offsets, disturbed periods, bursts, and quality-control rejection.
This is an offline simulation: it doesn't connect to live laboratory instruments.

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
random-search and uncertainty-aware Bayesian-optimisation results.

The older `run_offline.py` provides additional illustrative policies and plots.
Its summaries are not substitutes for the blog's final-nomination benchmark.

```bash
python run_offline.py --policy adaptive --budget 50 --repeats 1 \
  --seed 200 --landscape qc_weighted --environment nonstationary_qc \
  --disturbance-profile severe --out offline_results
```

## Bayesian optimisation

```bash
python -m pip install -r requirements-bo.txt
python bo_baseline.py --repeats 20 --seed 200 --out bo_results_uncertainty
```

Uses 10 Latin-hypercube initial locations, a scaled Matern-5/2 ARD GP,
reported measurement variances plus a fitted shared noise term, and log noisy
expected improvement. Only QC-valid observations train the GP. Final nomination
maximizes posterior mean among visited locations. It has no explicit drift model.
The supplied results record their original dependency versions. Installing newer
versions may change numerical optimisation and trajectories. See VALIDATION.md
for what was actually executed for this release, and VALIDATION_ENVIRONMENT.txt
for the tested package versions (the CPU Torch build uses the PyTorch CPU index).

## Native Codex agent campaigns (macOS)

Requires an authenticated Codex CLI compatible with the original runner (developed
against CLI 0.162.1). The native filesystem sandbox uses macOS Seatbelt. Do not
disable a failing preflight to obtain benchmark results. Model identifiers and
available reasoning settings depend on your account and CLI.

### Disable external tool servers before running

The benchmark preflight rejects enabled MCP servers (such as `node_repl`)
because they are not constrained by the benchmark’s local Seatbelt sandbox.
This is an intentional isolation check.

If preflight reports an enabled server, back up `~/.codex/config.toml`,
then set `enabled = false` in the config.toml's mcp server’s section:

    [mcp_servers.node_repl]
    enabled = false

If an `enabled` setting already exists, edit it rather than adding a
duplicate. Leave the other settings unchanged. Repeat for any other
servers reported by preflight, then rerun the benchmark.

You can restore the original settings after the benchmark finishes.
This temporarily affects your normal Codex configuration.
Do not bypass the preflight check.

### Benchmark Campaign Command

```bash
python native_blind_runner.py --model YOUR_MODEL_ID --effort medium \
  --budget 50 --repeats 20 --seed 200 --objective dpa \
  --landscape qc_weighted --environment nonstationary_qc \
  --disturbance-profile severe --out codex_native_results
```
### Command-line options

| Flag | Accepted values / meaning |
|---|---|
| `--model` | Codex model ID. Examples used in this study: `gpt-6-luna`, `gpt-6-astra`, `gpt-6.1-sol`. Availability depends on your account and Codex CLI. |
| `--effort` | `low`, `medium`, `high`, or `xhigh`. Not every model supports every setting. `max` and `ultra` are not accepted by this runner. |
| `--budget` | Measurements per campaign, from 1 to 50. Repeats and QC failures consume this budget. Final nomination is separate. |
| `--repeats` | Independent campaigns, from 1 to 1000. Each starts a fresh agent session. |
| `--seed` | First simulation seed. For example, `--seed 200 --repeats 20` uses seeds 200–219. |
| `--objective` | `dpa` for amplitude-fit contrast, or `complex` for complex-fit contrast. |
| `--landscape` | `original`, `qc_weighted`, or `qc_only`. These select different reconstructions of the reference measurements. |
| `--environment` | `clean`, `noisy`, `noisy_qc`, or `nonstationary_qc`. |
| `--disturbance-profile` | `mild`, `moderate`, or `severe`; applies to the nonstationary environment. |
| `--out` | Directory for run outputs. |

The blog benchmark uses `--budget 50 --repeats 20 --seed 200`,
`--objective dpa`, `--landscape qc_weighted`,
`--environment nonstationary_qc`, and `--disturbance-profile severe`.

For a single trial campaign, change `--repeats 20` to `--repeats 1`.
The runner does not automatically substitute another model if the requested
model or reasoning effort is unavailable.

Run `python native_blind_runner.py --help` for all options, including
timeouts, batch resumption, preflight checks, and mock runs.

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
The 240-point snapshot drives this simulation and agent-informed zoom-in points are
not used to prevent biasing the experiment. Other included CSVs document the extraction history.

The 17.08 dB reference is the grid maximum of the reconstructed simulated map. Noise parameters are informed
by experimental control measurements.
See NONSTATIONARY_README.md for equations and parameters, and
SQUID_Agent_Benchmark_Methodology.md for the protocol. Other Markdown files are
historical development notes and can describe earlier modes.

## Release scope and reproducibility

Core simulator, runner, calibration and scoring data are preserved from the
provided archive. This packaging adds this README, random-baseline reproduction,
dependency guidance, ignore rules and validation notes. Two personal Windows
log paths were removed from the optional 245-attempt archive. The canonical
240-point CSV and simulator Python sources were not changed.

Large agent logs, duplicate ZIPs, caches and filesystem metadata are omitted.
Publishing a landscape allows future systems to learn it. This release supports
inspection and reproduction, not a permanently secret evaluation set.
