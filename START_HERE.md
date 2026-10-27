> Historical development document. Start with [README.md](README.md) for the packaged release.

# New: nonstationary measurement mode

Read `NONSTATIONARY_README.md` for commands, assumptions and validation. Existing stationary commands retain their original behaviour.

# SQUID autonomous-search benchmark: offline starter (no API key)

This is a **software-infrastructure smoke test** using your exact 240-point fitted broad map.
It is **NOT an LLM agent**, and the all-point interpolation is **NOT a validated physical ground truth**:
149/240 original fits failed QC. For now no uncertainty, fit QC, drift, or failures are simulated.

## Setup (Mac or Linux)

1. Unzip this starter into the **same folder** as your existing `level2_emulator_240_snapshot.csv` file, so that `offline_simulator.py`, `run_offline.py`, and the CSV are together. No need to modify your existing extraction files.
2. Open Terminal. Type `cd ` (with a space) and drag that folder from Finder into Terminal. Press Return.
3. Check Python: `python3 --version` (3.10+ recommended).
4. Create an isolated environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   ```
5. Run **one 50-evaluation adaptive search**:
   ```bash
   python run_offline.py --policy adaptive --seed 42 --budget 50
   ```
6. Look under `offline_results/` for a timestamped folder with `run_001/trajectory.png`, `run_001/trajectory.csv`, `run_001/evaluations.jsonl`, `run_001/summary.json` and `aggregate_summary.json`.

To run a random-search comparison:
```bash
python run_offline.py --policy random --seed 42 --budget 50
```

To run 20 reproducible adaptive *baseline* campaigns:
```bash
python run_offline.py --policy adaptive --repeats 20 --seed 100 --budget 50
```

## Windows PowerShell

Run these commands from the folder containing the files:
```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run_offline.py --policy adaptive --seed 42 --budget 50
```

## What it does

- Loads `level2_emulator_240_snapshot.csv` and checks for 240 measurements / 91 QC valid.
- Uses SciPy's **piecewise linear 2D interpolation**, the same method family as the previous heatmaps, with no extrapolation.
- Returns synthetic results via `OfflineSimulator.evaluate_bias_point(Ib, Phib, run_id, bias_point_number)`.
- Runs a minimal adaptive policy, which only sees its own previous simulator observations. It sometimes explores randomly and otherwise probes near its best observed **chosen objective** (`dpa` by default or `complex`).
- Logs every synthetic evaluation, plots an overlaid trajectory and best-so-far curve, and computes area-weighted interpolated percentiles.
- Records the original dataset SHA256 and tags all results as **offline** and **simulated**, with no instrument interaction.

## Limitations / next version

- Does **not** launch an OpenAI, Anthropic, or other language model.
- Does **not** simulate measurement fit errors, invalid QCs, or time-dependent drift.
- Returns only an agent-relevant **subset** of the original live wrapper's output schema; generated `gmax/gmin` are placeholders consistent with contrast, not independent fits.
- The visual/reference landscape includes QC-invalid fitted values and is for wiring/diagnostics only.
- In the next version we'll validate alternative landscapes, add QC and noise models, and connect a model-agnostic tool-calling agent runner.
- The full CSV/JSON and original archives should remain untouched for provenance.

## Dual-metric version: DPA and complex fit

Both contrasts have always been present in your canonical dataset. This update makes them
**separate selectable search objectives** while logging/scoring **both** for every evaluation.
It does not combine them into one arbitrary scalar.

The original preregistered experimental search target was the amplitude/DPA fit; use `dpa`
for direct continuity with the physical runs. Treat `complex`-optimized search as an explicitly
separate, exploratory objective, not a retrospective change to the physical benchmark.

```bash
# Optimizes the original DPA metric but saves and scores complex contrast too:
python run_offline.py --policy adaptive --objective dpa --seed 42 --budget 50

# Optimizes complex contrast, but still saves DPA values and DPA percentile for every query:
python run_offline.py --policy adaptive --objective complex --seed 42 --budget 50

# 20 repeat simulations under each objective:
python run_offline.py --policy adaptive --objective dpa --repeats 20 --seed 100 --budget 50
python run_offline.py --policy adaptive --objective complex --repeats 20 --seed 100 --budget 50
```

For either objective, `trajectory.csv` contains DPA contrast, complex contrast, and both
map percentiles. `summary.json` and `all_runs.csv` contain independent best values and
ranking summaries for each fit, plus values at the best point for the selected objective.
`trajectory.png` has two learning curves, one for each fit.

**No synthetic QC/uncertainty yet:** this remains the all-240-fit deterministic interpolation,
which includes 149 originally QC-rejected measurements. DPA and complex fits are **two
analyses of the same phase sweeps**, not independent physical repeat measurements.
Fit disagreement at extreme contrasts is itself interesting and should be analyzed,
but a high score on one fit must not be represented as verified physical gain.
