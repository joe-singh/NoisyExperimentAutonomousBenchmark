> Historical development document. Start with [README.md](README.md) for the packaged release.

# SQUID benchmark: one Codex session per campaign

This update replaces only `native_blind_runner.py` and `test_native_blind_runner.py` in your existing `DPA-Emulator` directory. **Keep your working `native_security.py` unchanged** (the inline TOML profile that passed the macOS Seatbelt preflight). The update does not alter the experiment CSV or simulator modules.

## Why this change matters

The previous pilot started `codex exec --ephemeral` afresh for every measurement. That did not preserve Astra's original strategy and rationale. This update:

- Evaluation 1: begins **one durable Codex session** via `codex exec --json ...`.
- Evaluations 2–50: use `codex exec resume <session UUID> ...`, retaining previous decisions, scientific rationales, and observation history.
- The controller sends **only the new measurement observation** when continuing. It does not insert latent DPA/complex scores, map percentiles, or hidden information.
- Each independent campaign creates its own clean workspace and starts a **new session**. A 20-run batch requires 20 distinct session UUIDs. If a resume returns the wrong session UUID, the controller stops.
- Codex is restarted as an operating-system process between queries; the **conversation/session stays the same**.

## Installation

Unzip this package into `~/Desktop/DPA-Emulator`, replacing the two Python files.

```bash
cd ~/Desktop/DPA-Emulator
source .venv/bin/activate
python -m unittest test_native_blind_runner -v
python native_blind_runner.py --preflight-only
```

The preflight checks the same local Seatbelt filesystem boundary as before **and** tests that your installed Codex CLI supports `exec resume --output-schema`, `--output-last-message`, and `--json`. It performs no model inference. On 0.162.1 these are expected to be available; if the help output does not advertise them, the script fails before an experimental run.

## First real test (three evaluations in one session)

```bash
python native_blind_runner.py \
  --budget 3 \
  --model gpt-6-astra \
  --effort medium \
  --landscape qc_weighted \
  --environment clean \
  --seed 42
```

Look for `CODEX_SESSION_ID.txt` and `CODEX_TURNS.json` in the new output directory. `CODEX_TURNS.json` must have three entries with **exactly the same session UUID**. The per-evaluation `codex_001_stdout.jsonl` etc. preserve the Codex `thread.started` and `turn.completed` events, and `summary.json` contains the same UUID.

Only after inspecting this smoke test, try `--budget 10` and eventually a full `--budget 50`.

## Multiple independent trials (when the single campaign has been verified)

```bash
python native_blind_runner.py \
  --budget 50 \
  --repeats 20 \
  --model gpt-6-astra \
  --effort medium \
  --landscape qc_weighted \
  --environment noisy_qc \
  --seed 42
```

This schedules seeds 42–61 as twenty sequential, independent campaigns. Within each campaign, every evaluation resumes that campaign's session. Between campaigns, no session is resumed; a brand-new session and agent workspace are created. The runner also saves a `*_batch_*.json` manifest that records one session UUID per campaign and checks uniqueness. Stop immediately if a trial fails (prior results are retained).

**Important:** `--seed` controls the emulator RNG, **not** Codex's model sampling RNG. In `clean` mode, changing seeds does not change the ground-truth function. Repeated trials are separate sessions, but not guaranteed to be statistically independent samples of model behavior if the model is effectively deterministic. Report this limitation.

## What was tested here

- All 14 local Python unit tests passed (including mocked first-call and resumed-call transcript checks).
- A 2-campaign, 3-evaluation-per-campaign **mock** completed and wrote a batch manifest.
- We could not call the user's ChatGPT-authenticated Codex installation or macOS Seatbelt in this environment. **The actual Codex CLI continuation and native preflight still need to be verified on your Mac** before any scored 50-point campaign.

## Security and reporting caveats

The original sandbox protections are kept unchanged; this patch does not broaden shell access or expose the map. As before, the macOS preflight tests only the documented local command boundary, not every possible external integration. Do not enable MCP servers, shell tools, Apps or hooks for this benchmark. Logs and session UUIDs are generated separately for each campaign. Inference usage may be substantial for 20 × 50 decisions; verify the 3-step smoke test before scaling.
