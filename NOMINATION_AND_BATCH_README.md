> Historical development document. Start with [README.md](README.md) for the packaged release.

# SQUID agent benchmark — final nomination + resumable 20×50 batch

This is a **drop-in update** to the *working native macOS* Codex benchmark. **Keep `native_security.py` exactly as it is**, because that is the Seatbelt profile that passed the security preflight on your Mac. The update does not change your experimental map, the simulator, or earlier results.

## What changed

1. **Exactly one Codex session per campaign.** All 50 measurement decisions and the final nomination are turns within that same session. Every new campaign starts a **fresh** session UUID.
2. **A mandatory extra final-nomination turn after the final measurement.** It does **not** call the simulator. The agent returns `selected_evaluation`, an integer pointing to one of the **already measured** points, and a scientific rationale. The final measurement result is passed to this turn, so the agent sees all 50 outcomes before choosing.
3. The host controller resolves the nominated evaluation number to the previously requested coordinates and records its hidden DPA/complex contrast and percentiles, selection gap to the best visited point, and number of successful QC measurements at that same requested coordinate. The agent **never receives these hidden scores**.
4. Token counters from Codex CLI 0.162.1 are **cumulative by session**. `inference_usage_reported` now uses only the **last** (nomination) turn's token counters, rather than incorrectly summing the per-turn snapshots. The complete original JSONL logs are retained for audit.
5. `--repeats 20 --budget 50` makes 20 sequential independent campaigns, 1,000 simulated measurement calls + 20 final-nomination turns. A batch manifest records all sessions and scores, and enforces distinct session UUIDs and 51 total turns per campaign.
6. The batch can be **paused between campaigns** with `--max-new-trials N` and **resumed** using `--resume-batch <manifest path>`. Already completed trials are not repeated. If an individual campaign fails, its partial artifacts are preserved; the next attempt for that trial starts **from scratch in a fresh Codex session**, with the same emulator seed. Partial conversations are not silently counted as completed campaigns.

## Install

From `~/Desktop/DPA-Emulator`, where your `.venv` is activated:

```bash
unzip -o ~/Downloads/squid_final_nomination_batch_update.zip -d .
python -m unittest test_native_blind_runner -v
python native_blind_runner.py --preflight-only
```

There should be **19 passing unit tests**. The native Seatbelt filesystem boundary must pass again before real calls. Do **not** replace or edit your working `native_security.py`.

## Required first test: 3 measurements + nomination

This tests the **new Codex response schema** using your actual ChatGPT login; it has not been exercised with real Codex inference here.

```bash
python native_blind_runner.py \
  --budget 3 --model gpt-6-astra --effort medium \
  --landscape qc_weighted --environment noisy_qc --objective dpa --seed 46
```

Check the newest directory under `codex_native_results/`:

- `CODEX_TURNS.json` contains **four** entries (3 measurements and `final_nomination`) with **one identical `session_id`**.
- `FINAL_NOMINATION.json` contains a `selected_evaluation` between 1 and 3 and rationale.
- `summary.json` has `nomination` and `inference_usage_reported` fields.
- `evaluations.jsonl` still has **exactly three** measurements, not four.
- `HIDDEN_NOMINATION_SCORE.json` is in the trusted host output, not in the agent workspace.

If this fails, **stop and share the error**; do not start the large batch.

## Run a 20×50 experiment in controlled stages

Start a batch intended for 20 campaigns but run **one full campaign first**:

```bash
python native_blind_runner.py \
  --budget 50 --repeats 20 --max-new-trials 1 \
  --model gpt-6-astra --effort medium \
  --landscape qc_weighted --environment noisy_qc \
  --objective dpa --seed 100
```

The runner prints a `..._batch_....json` **manifest path**. Save that path. At the end of the first full campaign, the manifest status should be `paused`, with `1/20` completed.

Continue two more campaigns to check operational stability:

```bash
python native_blind_runner.py \
  --resume-batch "/absolute/path/to/YOUR_batch_manifest.json" \
  --max-new-trials 2
```

When satisfied, run the rest (there is no `--max-new-trials`, so all remaining campaigns will run sequentially):

```bash
python native_blind_runner.py \
  --resume-batch "/absolute/path/to/YOUR_batch_manifest.json"
```

A interrupted batch can be resumed using that same command. **It only resumes between complete campaigns.** The same completed campaigns aren't rerun, and interrupted partial campaigns are preserved separately. Keep your Mac awake and Terminal available during the long batch. Model service rate/usage limits can still cause individual campaigns to fail; those trials are **not** counted as completed.

## Outcome data

- `summary.json`: best underlying visited DPA and complex, nomination's latent contrasts/percentiles, selection gap, QC support, session UUID, elapsed seconds, reported cumulative input/cached/output token counters.
- `FINAL_NOMINATION.json`: agent's final recommendation and **its own explanation**, with no hidden scores.
- `HIDDEN_NOMINATION_SCORE.json`: evaluator-only scoring for the nominated point.
- `CODEX_TURNS.json`: all decision turns **plus** final nomination, same UUID.
- The batch manifest: all completed campaign directories and session IDs; one entry per *successful* independent campaign.

## Scientific scope

This is a **reconstructed experimental map**, not independently established physical ground truth. The `qc_weighted` landscape and `noisy_qc` measurement model are provisional. Predefine DPA as primary and complex as secondary (or run separately under explicit preregistration), and compare against numerical and random baselines under matched seeds. Even 20 fresh Codex sessions may make very similar choices; `--seed` controls emulator randomness, not an exposed Codex sampling seed.

The native filesystem Seatbelt preflight checks local shell-access isolation but is not a comprehensive guarantee against all possible integrations. Keep Apps, MCP servers, and agent shell tools disabled, as in the previously audited pilot.

## Development validation

Here, **19/19 unit tests passed**. I additionally ran a **20 × 50 mock batch** (1,000 simulator measurements and 20 mock nomination records). I interrupted the mock batch, resumed it, and checked that the final manifest reached 20/20 completed. This **does not establish** whether the changed final-nomination response schema will work with your authenticated Codex CLI on macOS; the 3-measurement real smoke test above is required before scaling.
