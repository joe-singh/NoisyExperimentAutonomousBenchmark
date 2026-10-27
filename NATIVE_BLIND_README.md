> Historical development document. Start with [README.md](README.md) for the packaged release.

# Native macOS Codex SQUID pilot — no Docker, no second account

This pilot uses your *existing working* macOS Codex CLI and ChatGPT login. The trusted Python controller remains in `DPA-Emulator`, while model invocations start in a separate workspace. Codex's macOS Seatbelt sandbox uses an explicitly restricted **permission profile**.

**Important:** This package has passed local Python unit tests and a three-query mock run, but **the Seatbelt preflight and real Codex inference must be verified on your Mac**. The controller refuses to make a real model call if the local preflight fails.

## Install

Unzip the contents **directly into `~/Desktop/DPA-Emulator`** (only adds files). It requires the working Stage B emulator already present:

- `offline_simulator.py`, `landscape_model.py`, `measurement_model.py`, `run_offline.py`
- `level2_emulator_240_snapshot.csv`
- `.venv/` from the previous setup

New files in this package:

- `native_blind_runner.py`: trusted emulator/model orchestrator
- `native_security.py`: fail-closed filesystem safety tests
- `native_agent/decision.schema.json`: agent-visible output format
- `test_native_blind_runner.py`: unit tests

From Terminal:

```bash
cd ~/Desktop/DPA-Emulator
source .venv/bin/activate
python -m unittest test_native_blind_runner -v
```

## 1. Check isolation **without making a model call**

```bash
python native_blind_runner.py --preflight-only
```

This creates `~/Desktop/DPA-Agent-Workspace/security_probe/` and runs real macOS Seatbelt commands using `codex sandbox macos --permission-profile squid_blind`:

1. Reading a marker **inside** the agent workspace must succeed.
2. Reading your actual private map CSV **outside** the agent workspace must be denied.
3. Reading `~/.codex/auth.json` from sandboxed shell code must be denied.
4. Listing the private emulator directory from sandboxed shell code must be denied.

All four are required. The preflight doesn't print any sensitive file content.

The named permission profile is supplied through the `-c` CLI arguments on each invocation. It combines `:root = deny`, `:minimal = read`, workspace-root write permissions, and disabled sandbox command networking. The agent model's own service traffic remains functional, separately from sandboxed command traffic.

If the test fails, **do not run the agent**. Send the failure message; don't change file permissions or disable security settings to make it pass.

The pilot also rejects user config with a legacy `sandbox_mode`/`sandbox_workspace_write` setting (which can disable the new profile), or enabled MCP servers or hooks. If detected, inspect your `~/.codex/config.toml` and back it up before making any changes. Do not upload its contents without checking for secrets. If your organization manages Codex settings, they may require additional review.

## 2. Run the first real 3-measurement Codex experiment

```bash
python native_blind_runner.py \
  --budget 3 \
  --model gpt-6-astra \
  --effort medium \
  --landscape qc_weighted \
  --environment clean \
  --seed 42
```

The command repeats the sandbox preflight and creates a fresh per-run workspace. It executes **one stateless `codex exec` per evaluation**, supplying the full prior visible measurement history. You don't need an API key or Docker. It prints each simulated result and produces:

- `codex_native_results/<timestamp>.../evaluations.jsonl`: only agent-visible measurements + decisions
- `.../HIDDEN_GRADER_ONLY.jsonl`: latent map values, retained on the trusted host
- `.../trajectory.csv`, `.../trajectory.png`: scored trajectory
- `.../RUN_CONFIG.json`: model, seed, configuration, hash and settings
- `.../codex_###_stderr.log`, `.../codex_###_stdout.log`: CLI logs

If anything fails midway, partial records remain. For this pilot, no automatic resume: re-run with a fresh run ID for clean provenance.

## 3. Expand only after first run succeeds

Try `--budget 10`, then `--budget 50`; then run the same model with `--environment noisy` or `--environment noisy_qc`. We can automate repetitions and more models after validating one 50-measurement run.

## Security and scientific caveats

- The Seatbelt profile is **not** a blanket restriction on *all* model capabilities. It governs local sandboxed commands. We additionally disable CLI Apps, web search, and the shell tool; the preflight rejects configured MCP servers and hooks in the user config. Before claiming formal blinding, we should audit any system/organization-managed integrations or extra tools your account provides.
- Avoid launching this project from `DPA-Emulator` *as Codex's working directory*. The trusted Python controller runs there, but it launches the Codex process from `DPA-Agent-Workspace`.
- **Never use `--sandbox danger-full-access`, `--yolo`, or `-c sandbox_mode=...`** for this benchmark.
- The environment returns *simulated* observations derived from finite experimental data; the QC/noise model is provisional. High reconstructed-map percentiles are not verified physical SQUID optima.
- This is the decision-only benchmark: the agent returns a structured bias point, and is not allowed to write an optimizer. That reproduces Astra's decision loop more closely than Sol's freeform-code implementation. A coding-agent benchmark is a separate experiment.

Official Codex documentation: https://learn.chatgpt.com/docs/permissions and https://learn.chatgpt.com/docs/cli/reference
