> Historical development document. Start with [README.md](README.md) for the packaged release.

# Blind Codex pilot: first LLM-driven SQUID benchmark

This is a **small, deliberately conservative pilot** that uses your existing Stage B emulator on the host and Codex CLI in a data-blind Colima/Docker container. **No separate API key is needed**, but signing in to Codex inside the container is a separate one-time step from your Mac Codex login.

## The important security boundary

Your host-side trusted controller runs `blind_codex_runner.py` *in* `DPA-Emulator`, where your experimental CSV and Python interpolation files remain. It uses these privately. **The Codex process does not run in that host directory.**

The agent container:
- has a clean `/workspace` temporary filesystem;
- does **not** mount `~/Desktop/DPA-Emulator` or any host folder;
- does **not** mount the Docker socket;
- only mounts a dedicated Docker **named volume** for its separate Codex login;
- runs Codex with read-only sandbox commands and a restrictive output JSON schema;
- receives the chronological list of previous *agent-visible* measurements on stdin, never hidden map scores.

The agent image contains only the Codex CLI and a decision schema. The CSV is **not** in this update ZIP's agent image directory and is never copied into the image. Model output is independently range-checked by the controller. Container isolation protects *filesystem access to the map*; it is not a cryptographic guarantee against container escape or credential compromise. Treat the Codex auth volume as sensitive. Don't publish it or mount your Mac's `~/.codex` inside an agent container.

## Install into your existing DPA-Emulator folder

Unzip `squid_blind_codex_pilot.zip` directly into `~/Desktop/DPA-Emulator`.

You should have at least these pre-existing Stage B files:

- `level2_emulator_240_snapshot.csv`
- `offline_simulator.py`
- `landscape_model.py`
- `measurement_model.py`
- `run_offline.py`

The ZIP adds **only** `blind_codex_runner.py`, `test_blind_codex_runner.py`, `agent_image/`, and this README. None of your existing working simulator files or data need to be replaced.

Open Terminal:

```bash
cd ~/Desktop/DPA-Emulator
source .venv/bin/activate
python -m unittest test_blind_codex_runner -v
```

## Step 1: build the isolated image

Colima is already running if `docker run --rm hello-world` succeeded.

```bash
docker build -t squid-codex-agent:pilot-0.1 ./agent_image
docker volume create squid_codex_login
```

The first command downloads and installs the Linux/ARM64-compatible Codex CLI inside the agent image. Build time depends on network speed.

## Step 2: authenticate *inside the container*

```bash
docker run --rm -it \
  --mount type=volume,source=squid_codex_login,target=/home/node/.codex \
  squid-codex-agent:pilot-0.1 codex login --device-auth
```

Follow the device authentication instructions shown in Terminal. These are separate from the earlier `codex login` on macOS; nothing is copied out of your Mac's `~/.codex` directory. If device-code login is restricted or fails, stop and share the error message (not credentials) so we can choose a supported login method.

Verify:

```bash
docker run --rm \
  --mount type=volume,source=squid_codex_login,target=/home/node/.codex \
  squid-codex-agent:pilot-0.1 codex login status
```

It should report that you're signed in with ChatGPT.

## Step 3: quick local mock test (no inference or Docker calls)

```bash
python blind_codex_runner.py --mock --budget 3 --landscape qc_weighted --environment clean
```

This checks host-side output creation. It is **not** an LLM run.

## Step 4: first real blind Codex search, only 3 evaluations

```bash
python blind_codex_runner.py --budget 3 --landscape qc_weighted --environment clean --seed 42
```

After the above works, try 10:

```bash
python blind_codex_runner.py --budget 10 --landscape qc_weighted --environment noisy_qc --seed 42
```

Note: these steps invoke the ChatGPT-authenticated Codex CLI and count against your account's Codex usage limits. Each evaluation invokes a **fresh, ephemeral** Codex session with the complete history so far. This is simple and auditable but inefficient in tokens; we should change to persistent sessions for large-scale experiments after verifying the pilot.

On each step you should see a requested bias, simulated observed DPA/complex contrast, and validity status. Results are saved automatically in `codex_blind_results/<timestamp>_<id>.../`.

Files in each result directory:

- `RUN_CONFIG.json`: selected model, landscape, seed, settings and dataset hash
- `evaluations.jsonl`: agent-visible decisions and returned measurements
- `model_001_output.json`: untrusted structured model output at each step
- `model_001_stderr.log`: Codex CLI processing diagnostics
- `HIDDEN_GRADER_ONLY.jsonl`: **trusted host-side** latent contrasts at visited points
- `trajectory.csv`, `trajectory.png`, `summary.json`: score and plot after completion

**Never mount the results folder or hidden grader files into the agent container.**

## First-pilot limitations

- This is a **decision-only agent**. Unlike an open-ended coding-agent benchmark, it cannot create its own optimizer scripts. That can be a separate track later.
- This uses the existing experimental-map reconstructions. They are provisional surrogate landscapes, not independently verified physical ground truth.
- The noisy/QC observation model is exploratory.
- Codex's default model may vary over time. For comparisons, pass `--model <actual-supported-Codex-model-id>` and log the exact version.
- Agent-generated invalid coordinates currently stop the pilot, rather than consuming budget. We'll define an invalid-decision policy before full-scale benchmarks.
- The CLI is invoked separately for each step, not a true uninterrupted 50-step agent conversation. We deliberately provide the complete prior **measurement** history on every invocation.
- A failed Codex invocation preserves all previously completed measurements so you can inspect the failure without losing the record. Automatic resumption is not yet implemented.
- This v0.1 prototype does not include a credential-theft hardening policy for agents that can execute arbitrary shell commands, and should not be treated as a production sandbox for adversarial agents.

## Reproducibility and fairness

Keep fixed for all compared models: landscape, environment, budget, objective, agent instruction, observation schema, and simulator seed. Use multiple independent runs. Do not give any model the hidden map, source code, or previous-run results. Results from this pilot are for pipeline validation, not a research leaderboard.
