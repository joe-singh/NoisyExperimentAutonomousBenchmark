> Historical development document. Start with [README.md](README.md) for the packaged release.

# SQUID Autonomous-Agent Benchmark — Methodology and Simulation Modes

**Methodology record — 16 October 2026**  
**Scope:** retrospective, fully software-based SQUID bias-point optimization, developed after the original live cryogenic experiments.  
**Status:** working research benchmark; the simulated measurement and QC distributions are *exploratory*, not a validated digital twin.

## 1. What the agents are asked to do

An autonomous agent searches for a SQUID operating point that maximizes reliable phase-sensitive gain contrast in a fixed SQUID–resonator experiment. Its only controllable variables are

\[
10\le I_b\le15\;\mu\mathrm A, \qquad 0\le\Phi_b\le70\;\mu\mathrm A.
\]

Each campaign has **50 candidate measurement evaluations**. The agent can choose new points or repeat previously queried coordinates. A repeat is a *new measurement*: it consumes one evaluation and, in a stochastic environment, receives a new simulated observation. Failed-QC measurements also consume an evaluation. All other experimental settings and measurement procedures are fixed; the decision-only agent cannot change pump/probe parameters, redefine fitting or QC, or operate physical instruments.

The primary objective, inherited from the original Level-1 experiment, is **DPA amplitude-fit contrast**:

\[
C_{\mathrm{DPA}}=20\log_{10}\left(G_{\max}/G_{\min}\right)\quad\mathrm{dB}.
\]

A separate fit to the complex phase response produces a **complex-fit contrast**, which is always reported alongside DPA and is used as a secondary diagnostic. The offline runner also offers `--objective complex` for deliberately separate experiments, but **all the Codex model-comparison batches described below used `--objective dpa`**. The two fits come from the same underlying experimental procedure; their agreement is not independent experimental validation.

After the 50th observation, the agent gets **one final nomination turn in the same conversation**. It must select an *existing evaluation number*, corresponding to a previously measured coordinate, and provide a scientific rationale. The nomination requires no new measurement and does not count against the 50-point budget.

## 2. Where the experimental data come from

The main source is `level2_emulator_240_snapshot.csv`, a fixed snapshot of **240 nonadaptively scheduled broad-sweep bias points** acquired after the original physical agent searches. The dataset contains requested and actual bias coordinates, both fitted contrasts, fit confidence intervals, quality-control flags, fit diagnostics, baseline drift, timing, and run provenance.

- **240** broad-sweep measurement points have fitted DPA and complex values.
- **91/240** passed the canonical experimental QC checks; **149/240** did not.
- The primary simulated landscapes use **requested** bias setpoints as coordinates.
- **68 local follow-up measurements** near the original agents' discoveries are deliberately **excluded** from the primary broad-map reconstructions. Those patches were adaptively selected and would favor already discovered regions if incorporated directly into the benchmark's primary map.
- The extra post-snapshot broad points, raw phase-sweep `X/Y` traces, and the real-time apparatus are not part of the offline inference loop.

**Frozen CSV SHA-256:** `a36bf48a12e6fa18c860e9c221fb6fffd5cd479eb3a9618ddd68ad7ffc1e7bc8`.

This CSV contains observed fits, including QC-rejected fits; it does **not** give an independently verified physical contrast everywhere in continuous bias space. Every map described below is a *reconstruction*.

## 3. Two separate layers: landscape and measurement

The simulator deliberately separates

1. a **fixed reconstructed landscape**, \(C_{\mathrm{latent}}(I_b,\Phi_b)\), giving DPA and complex contrast predicted at any allowed coordinate; and
2. a **measurement model**, which returns the contrast values, uncertainties, diagnostics, and QC outcomes visible to the agent on each query.

Conceptually,

\[
\boldsymbol C_{\mathrm{obs},t}=\max\!\left(\boldsymbol 0,\;\boldsymbol C_{\mathrm{latent}}(I_{b,t},\Phi_{b,t})+\boldsymbol\epsilon_t\right),
\]

where the error term vanishes in `clean` mode and is resampled for each evaluation in stochastic modes. The **latent** map is fixed within and across campaigns of a given landscape configuration. The agent never receives the latent values or the true-map percentile. These are kept by the trusted scoring controller.

### 3.1 `--landscape`: three possible underlying maps

| Value | How the latent DPA and complex maps are constructed | Main caveat |
|---|---|---|
| `original` | Piecewise-linear interpolation (`LinearNDInterpolator`) of **all 240** fitted points, including QC-invalid fits; exact stored values at measured nodes. | Can preserve sharp features and pathological/singular fitted extremes. Not verified physical truth. |
| `qc_weighted` | Smooth local Gaussian-kernel average of all 240 fits, with **weight 1.0** for QC-passing points and **0.20** for QC-rejected points. Kernel widths: **0.65 µA in** \(I_b\) **and 6.0 µA in** \(\Phi_b\). | Downweights unreliable fits, but can erase narrow real features and makes a broad favorable region easier to locate. |
| `qc_only` | Same Gaussian smoothing approach, but trains on only the **91 QC-passing points**. | Sparse coverage and potentially unreliable interpolation/extrapolation between accepted points. |

These choices were introduced in **Stage A**. Spatially blocked cross-validation on held-out QC-accepted measurements gave illustrative mean absolute errors (DPA/complex): `original` **3.72/3.63 dB**, `qc_weighted` **4.69/4.68 dB**, and `qc_only` **5.29/5.34 dB**. These are tests of predictive behavior under the chosen folds and should not be read as proof that including QC failures is physically correct.

**All completed 20-run Codex model-comparison batches so far used `--landscape qc_weighted`.** The original and QC-only maps remain available for robustness/sensitivity studies; they were not the primary environment for the model-comparison results.

### 3.2 `--environment`: three measurement modes

| Value | Reported DPA/complex on a repeat query | QC behavior | Intended purpose |
|---|---|---|---|
| `clean` | Returns the **same exact latent value** every time a coordinate is queried. | **Every** measurement marked valid; fit/R²/drift are not simulated. | Verify optimizer and landscape behavior without measurement uncertainty. |
| `noisy` | Adds **fresh random DPA and complex fluctuations** at each query. | Every measurement still passes synthetic QC. | Isolate sensitivity to noisy fitted contrast. |
| `noisy_qc` | Uses the **same noise mechanism as `noisy`**, drawing anew on every query. | Also draws a **new pass/fail QC outcome** and returns matching synthetic diagnostic fields and flags. | Test how agents navigate missing/rejected feedback while balancing exploration and replication. |

**Yes: the changing DPA readings you noticed in Luna are caused by `--environment noisy_qc`.** If Luna queries `(Ib, Phib) = (12.5, 52.5)` 30 times, the underlying map prediction at that coordinate stays fixed; the emulator generates **30 distinct observations** and potentially different QC outcomes.

#### How the provisional observational noise is generated

The code (`measurement_model.py`) uses the historical **95% profile-fit contrast intervals** in the broad-sweep CSV as a *noise-scale proxy*:

\[
\hat\sigma_j \approx \frac{C_{j,\mathrm{upper95}}-C_{j,\mathrm{lower95}}}{3.92},
\qquad j\in\{\mathrm{DPA},\mathrm{complex}\}.
\]

For missing, unbounded or unsuitable intervals it substitutes the median usable scale; individual pointwise scales are clipped to **0.25–5.0 dB**. At a requested coordinate, it Gaussian-weights the scales from up to **16 neighboring broad-sweep points**, using distances normalized by **0.65 µA** and **6.0 µA**. Then it draws independent zero-mean Gaussian perturbations for DPA and complex (and clips negative contrast to zero).

The default `--noise-scale` is **1.0**. The two fit noises have **zero imposed correlation** in the implemented model; this is a simplifying assumption, not evidence that the physical errors are uncorrelated.

The model also returns **illustrative intervals** around the simulated fitted contrasts using approximately \(\pm1.96\hat\sigma\). These are **not calibrated 95% intervals for repeat acquisitions**. The actual profile-fit intervals describe within-sweep fit uncertainty, not cross-acquisition reproducibility.

An optional `--stress-hotspots` sensitivity mode can add rare, much larger DPA excursions at high-contrast sites. **It is off in the default `clean`, `noisy`, and `noisy_qc` settings and was not used in the completed model-comparison batches.** Its tail amplitude/frequency is deliberately uncalibrated.

#### How synthetic QC is generated in `noisy_qc`

Let \(p_{\mathrm{global}}=91/240\approx0.379\) be the empirical QC-pass fraction, and let \(p_{\mathrm{local}}(I_b,\Phi_b)\) be the Gaussian-weighted pass fraction among up to 16 nearby broad-sweep points. Then the implemented passing probability is

\[
p_{\mathrm{pass}}(I_b,\Phi_b)
=\operatorname{clip}_{[0.05,\,0.95]}
\left(0.5\,p_{\mathrm{global}}+0.5\,p_{\mathrm{local}}(I_b,\Phi_b)\right).
\]

The simulator draws one Bernoulli pass/fail outcome **for each evaluation**. Conditional on that result, it borrows a nearby historical *QC template* of the same pass/fail class to populate fit \(R^2\), baseline-amplitude drift, and (for rejected measurements) quality flags. These diagnostics are **borrowed synthetic examples**, not statistics recalculated by refitting synthetic phase traces.

A QC-rejected query:

- **consumes one of the 50 evaluations**;
- still returns reported DPA and complex fits and the failure flags;
- must **not** be treated by the agent as a validated objective value;
- can still contribute to the host's hidden record that the agent *visited* a good latent-map coordinate.

**Important missing physics:** The current `noisy_qc` model has **no time-evolving drift state, no temporally correlated QC-failure streaks, and no calibrated heavy-tailed physical repeatability law**. A different sampled drift diagnostic on two repeats does **not** mean that the simulated apparatus underwent a physically modeled drift process. The original live experiment did experience real retuning, baseline drift and large hotspot variability; our offline QC model is a simplified proxy.

## 4. How a Codex agent campaign runs

The trusted host-side controller (`native_blind_runner.py`) can read the frozen CSV, reconstruct the hidden landscape, sample measurement noise/QC, and evaluate scores. The restricted Codex agent is asked only to select the next `(Ib, Phib)` and explain its rationale; it sees its own previous observations, not the map.

1. Start a **fresh Codex session** at evaluation 1 and provide the fixed task, variable bounds, objective, QC rule, and 50-evaluation budget.
2. Codex returns JSON containing `Ib`, `Phib`, and a brief `rationale`.
3. The host checks that coordinates are numeric, finite and in bounds, evaluates the simulator, and stores both the **agent-visible observation** and a separate **hidden latent score**.
4. For evaluation 2 onward, invoke `codex exec resume` with the **same session ID**, forwarding only the latest measurement observation. Previous decisions, rationale and feedback remain in the Codex conversation.
5. After evaluation 50, call the **same Codex session once more** for a final selection of a previously queried evaluation number and a rationale. This is **not** evaluation 51.
6. End the campaign; the next independent trial starts a **new Codex session and a fresh agent workspace**. A 20-run batch has 20 session IDs, each with 50 measurement turns and one final nomination turn.

### What the agent actually receives

Each result supplies the requested bias coordinates, `DPA_dB`, `complex_dB`, `valid_for_comparison`, QC flags, contrast intervals/status, amplitude and complex fit \(R^2\), and baseline drift where available. It is **not** given `C_latent`, latent percentiles, simulator random seeds, the experimental CSV, or results from other trials.

The simulated wrapper preserves the conceptual interface `evaluate_bias_point(Ib, Phib, run_id, bias_point_number)` but **does not run the physical instrument-control/fitting code or generate raw X/Y traces**. In the simulator the actual/read-back bias fields equal the requested coordinates, and certain reported gain extrema/diagnostics are synthetic placeholders.

### Filesystem blinding and scope of isolation

Codex runs natively on macOS in a separate per-trial workspace (`DPA-Agent-Workspace`), with a restrictive Seatbelt permission profile. Preflight probes have verified that the agent workspace can be read while reads of the private CSV, Codex credentials and enumeration of the private emulator directory are denied. The runner also disables shell, web search and Apps, and rejects configured MCP servers/hooks as part of its configuration checks.

This is a **tested local filesystem boundary**, not a formal proof against all possible information channels. Access to sibling trial folders was not initially tested explicitly; before a public benchmark release, record such a test and verify all enabled integration paths. Separately archiving earlier agent workspaces is an additional hygiene measure, not a substitute for technical isolation.

## 5. Which campaigns have been run so far?

The core **standardized Codex decision-only** campaigns used all the same substantive settings:

```text
--budget 50
--repeats 20
--landscape qc_weighted
--environment noisy_qc
--objective dpa
--seed 200            # trial seeds 200, 201, ..., 219
```

The model or reasoning-effort setting was varied:

| Configuration | Model argument | Effort | Batch status as of this note |
|---|---|---|---|
| Astra Low | `gpt-6-astra` | `low` | 20 completed |
| Astra Medium | `gpt-6-astra` | `medium` | 20 completed |
| Astra High | `gpt-6-astra` | `high` | 20 completed |
| Sol Low | `gpt-6.1-sol` | `low` | 20 completed |
| Luna Low | `gpt-6-luna` | `low` | **In progress / restarted**; do not interpret as a completed 20-run batch until its manifest says `completed`. |

Before these campaigns, we tested the simulator with deterministic **Python adaptive** and **uniform random** searchers, plus shorter Codex smoke tests (3, 10, 20 evaluations) and one-off 50-evaluation pilots. Those were **engineering and exploratory checks**; they should not be silently pooled with the frozen 20-run model comparisons.

The original *live physical* Astra and Sol agents used a different experimental setting and, in Sol's case, a self-written numerical optimizer. The offline experiments intentionally standardize the action interface and thus **do not reproduce the live coding-agent methodology**. Differences between live and simulated results need not reflect model intelligence alone.

### Seeds, repeats, and independence

Each simulated campaign receives its own seeded NumPy random-number stream. The same seeds (200–219) are used for every compared configuration. This improves reproducibility, but **identical seeds do not ensure identical observation noise or QC outcomes across two agents that query different sequences of coordinates**: random draws are consumed sequentially, and their distributions depend on requested position. Thus the seed-matched comparison is not a strict point-by-point matched-noise experiment.

Repeating a coordinate **within one campaign** is not an independent search trial. Statistical uncertainty in model performance is evaluated across the **20 separate campaign sessions**, not across 1,000 individual measurement calls treated as independent agents.

## 6. What is scored, and what it means

The trusted host evaluates every proposed coordinate on the frozen **latent reconstructed landscape** and computes its rank in a fixed reference distribution made by evaluating a **110 × 250 grid (27,500 coordinates)** spanning the allowed bias domain.

| Metric | Definition / interpretation |
|---|---|
| **Best visited** | Highest *latent* DPA contrast over all 50 requested points, **including** points whose simulated observation failed QC. It measures discovery of good coordinates, not successful experimental confirmation. |
| **Best QC-supported visit** | Highest latent contrast among coordinates whose measurements passed QC. |
| **Final nominated contrast** | Latent DPA (and complex) at the agent's final selected coordinate, which it previously measured. This is the principal end-of-campaign decision score. |
| **Selection gap** | `best latent DPA visited − latent DPA at final nomination`. Lower means the final choice was closer to the best location it encountered. |
| **Map percentile** | Percentage of the dense reference-grid values less than or equal to the latent DPA or complex contrast at a chosen coordinate. It is a **modeled bias-space percentile**, not the empirical rank among the 240 measured points. |
| **QC support at nomination** | Number of repeat attempts, number passing QC, and mean observed contrast over passing attempts at the nominated coordinate. |
| **Sample efficiency** | Evolution of best latent and best QC-supported contrast/percentile with evaluation number; time to first top-decile or top-1% visit. |
| **Inference cost** | Reported token usage (including cache and output/reasoning tokens) and campaign wall time; optionally estimated API-equivalent cost using separately documented price assumptions. |

**Beware of repeat-heavy agents:** “Top-decile queries” counts *all* visits, including repeats at identical coordinates. An agent repeating one good coordinate 30 times can score 30 top-decile queries without discovering 30 distinct good points. For substantive comparisons, also report **number of unique high-performing coordinates** and how early good regions were first discovered.

For the final end-point comparison, use the **median across campaigns** and a bootstrap confidence interval, together with the distribution of failures and the selection gap. The benchmark measures performance *within the frozen surrogate*. It does not validate physical gains on the SQUID.

## 7. Results, logs, and reproducibility

Each individual completed Codex trial saves files under `codex_native_results/<run-folder>/`, including:

- `RUN_CONFIG.json` — model, effort, budget, environment, landscape, objective, seed, dataset hash, isolation policy.
- `CODEX_SESSION_ID.txt` / `CODEX_TURNS.json` — persistent session ID and inference usage reported per turn.
- `evaluations.jsonl` — proposed bias points, rationales and **agent-visible** simulated measurement results.
- `HIDDEN_GRADER_ONLY.jsonl` — latent true-map *model* values for scoring; **never expose this to the agent**.
- `trajectory.csv` / `trajectory.png` — observed and latent outcomes at all evaluations; the CSV **contains hidden scores**.
- `FINAL_NOMINATION.json` — the agent's selected evaluation number and justification.
- `HIDDEN_NOMINATION_SCORE.json` — host-scored nominated contrast, percentile, gap and QC-support statistics.
- `summary.json` — campaign-level outcomes, token usage, elapsed time and QC counts.
- Codex JSONL/stderr logs — decision and nomination tool/run audit artifacts.

A multi-trial `*_batch_*.json` manifest records configuration, completed trial records, result-directory pointers, seed assignments and unique session IDs. It supports pause/resume **between campaigns**. If one campaign is interrupted, its partial data are kept, but the trial is restarted in a *new* conversation on resume. Reorganizing saved folders can invalidate absolute `result_dir` paths in old manifests, so preserve relative directory mapping or update audit scripts accordingly.

For Codex CLI **0.162.1**, the usage counters emitted at the end of each turn are **cumulative within the session**. Campaign-level token totals should be obtained from the **final (nomination) turn's snapshot**, not by summing all 51 cumulative readings. Input, cached-input and output tokens have different accounting/economic implications; reasoning-output tokens are part of output usage, not an extra independent number to add to billed output.

## 8. Interpretation and limitations

The current benchmark is useful for testing whether models can **explore, exploit, handle rejected observations, repeat measurements intelligently and make an evidence-supported final choice**. It is *not yet* an empirical reproduction of the refrigerator's full time-dependent noise and QC behavior.

In particular:

1. The QC-weighted landscape **smooths narrow structure**, making one high-flux region unusually prominent; performance can saturate and differences between strong models become difficult to resolve.
2. Noise amplitudes are based on profile-fit CI widths, **not calibrated experimental repeatability**. Historical physical repeats at selected hotspots showed much larger and non-Gaussian variability, but are too selectively sampled to define a global error law.
3. QC failures are **new spatially conditioned draws**, not a persistent drifting experimental state. The simulator does not reproduce serial failure clustering or true resonance-retuning dynamics.
4. Synthetic fit diagnostics and uncertainty intervals are **illustrative**, not outputs of fitting simulated quadrature traces.
5. Comparison with the original physical agents is **not apples-to-apples**, because physical environmental conditions, feedback quality and permissible strategies differ.
6. A near-identical 50-point final score across models does not prove equal capability. Inspect **early sample efficiency, final-selection gaps, unique points, and lower-tail outcomes**, and test robustness on the other reconstructed maps.

**Suggested next validation:** analyze sample efficiency at 5–20 evaluations using archived trajectories; test rank stability on `original` and `qc_only` landscapes; check whether QC/time-correlation and heavy-tail stress settings change the conclusions; include strong non-LLM optimization baselines; and audit sibling-workspace isolation and exact agent-facing prompts before publication.

---

### Minimal command reference

Run a deterministic Codex benchmark:

```bash
python native_blind_runner.py --budget 50 --model gpt-6-astra --effort medium \
  --landscape qc_weighted --environment clean --objective dpa --seed 200
```

Run a single campaign with new noisy measurements but no QC rejection:

```bash
python native_blind_runner.py --budget 50 --model gpt-6-astra --effort medium \
  --landscape qc_weighted --environment noisy --objective dpa --seed 200
```

Run the **actual standard setting used for the 20-campaign model comparisons**:

```bash
python native_blind_runner.py --budget 50 --repeats 20 --model gpt-6-astra \
  --effort medium --landscape qc_weighted --environment noisy_qc \
  --objective dpa --seed 200
```

The **same run can be repeated in different landscape configurations** (`original`, `qc_weighted`, `qc_only`) without altering the original experimental CSV. To reproduce a previously completed model run exactly, retain the source code, data hash, simulation flags, seed, CLI/model version, and agent-facing prompt. A fixed simulator seed does **not** imply deterministic decisions from the remote model.

**Implementation files consulted for this note:** `landscape_model.py`, `measurement_model.py`, `offline_simulator.py`, `native_blind_runner.py`, `native_security.py`, the Stage B repeatability audit, and the saved 240-point dataset.
