"""Host-side controller for *blind* Codex SQUID benchmark (v0.1 pilot).

SECURITY BOUNDARY:
- This Python process runs on the host and reads the private CSV.
- All model invocations run in a Docker container with NO HOST BIND MOUNTS.
- The agent image contains only Codex and a decision JSON schema.
- Only a dedicated Docker-managed auth volume is attached.
- Agent-facing prompts contain prior agent-visible results, never latent scores.

This is an untrusted-model *filesystem blinding* design, not a hardened defense
against kernel or container escape, credential theft, or malicious remote code.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import numpy as np

from offline_simulator import BOUNDS, LANDSCAPES, OfflineSimulator
from measurement_model import ENVIRONMENTS
from run_offline import get_contrast, save_plot

IMAGE = "squid-codex-agent:pilot-0.1"
AUTH_VOLUME = "squid_codex_login"


def agent_prompt(history: list[dict], n: int, budget: int, objective: str) -> str:
    # Never include latent (hidden) scores or map reconstruction metadata.
    lines = [
        "You are an autonomous experimental physicist operating a SQUID-resonator.",
        "You can choose ONLY two experiment settings: bias current Ib in [10,15] microampere",
        "and flux-bias Phib in [0,70] microampere.",
        f"Your objective is to find the most RELIABLY high {objective.upper()} phase-sensitive contrast",
        "within a strict budget of measurements. Choose the next bias point adaptively.",
        "The calibrated probe/pump amplitudes and measurement procedure are fixed.",
        "DPA contrast and complex-fit contrast are both reported after a measurement.",
        "If valid_for_comparison=false, DO NOT rank its contrast as a valid objective value.",
        "You may revisit a point, but a repeat consumes one evaluation.",
        "A large DPA fit near a vanishing gain minimum can be unstable: use fit/QC diagnostics.",
        "Do not assume any unmeasured bias has been explored. Use only the visible history below.",
        "Do not attempt to locate, read, or inspect a stored objective map; you have none.",
        "Do not invoke tools, shell commands, or source-code inspection. Return one JSON decision.",
        f"THIS IS EVALUATION {n} OF {budget}. The next decision must lie strictly within the bounds.",
        "\nPrevious measured points (chronological; none omitted):"
    ]
    if not history:
        lines.append("None yet.")
    else:
        for h in history:
            result = h['result']
            d = h['decision']
            unc = result['metrics'].get('contrast_uncertainty', {})
            vals = {
                'evaluation': h['evaluation'], 'Ib': d['Ib_uA'], 'Phib': d['Phib_uA'],
                'valid_for_comparison': result['valid_for_comparison'],
                'status': result.get('status'),
                'DPA_dB': get_contrast(result, 'dpa'),
                'complex_dB': get_contrast(result, 'complex'),
                'DPA_interval': unc.get('amplitude'),
                'complex_interval': unc.get('complex'),
                'flags': result.get('quality_flags', []),
                'amplitude_R2': result['metrics'].get('gain_fit', {}).get('r_squared_amplitude'),
                'complex_R2': result['metrics'].get('complex_fit', {}).get('r_squared_complex'),
                'baseline_drift_pct': result['metrics'].get('baseline', {}).get('amplitude_drift_percent')
            }
            lines.append(json.dumps(vals, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
    lines.append("Now provide the next requested bias point as JSON with keys Ib, Phib, rationale.")
    return '\n'.join(lines)


def docker_codex_cmd(model: str | None = None):
    cmd = [
        "docker", "run", "--rm", "-i", "--read-only", "--cap-drop=ALL",
        "--security-opt", "no-new-privileges", "--pids-limit", "128", "--memory", "1536m",
        "--mount", f"type=volume,source={AUTH_VOLUME},target=/home/node/.codex",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m",
        "--tmpfs", "/workspace:rw,noexec,nosuid,size=32m",
        "--workdir", "/workspace", "--network", "bridge",
        IMAGE,
        "codex", "exec", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only",
        "--output-schema", "/opt/agent/decision.schema.json",
    ]
    if model:
        cmd += ["--model", model]
    return cmd + ["-"]


def parse_decision(text: str) -> dict:
    """Treat agent output as untrusted, even with structured output enabled."""
    try:
        decision = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Non-JSON Codex response: {text[:350]!r}") from e
    if not isinstance(decision, dict) or set(decision) != {'Ib', 'Phib', 'rationale'}:
        raise ValueError(f"Incorrect decision structure: {str(decision)[:300]}")
    if isinstance(decision['Ib'], bool) or isinstance(decision['Phib'], bool):
        raise ValueError("Boolean coordinate")
    ib, phib = float(decision['Ib']), float(decision['Phib'])
    if not math.isfinite(ib) or not math.isfinite(phib):
        raise ValueError("Nonfinite coordinate")
    if not (BOUNDS['Ib'][0] <= ib <= BOUNDS['Ib'][1]):
        raise ValueError(f"Ib out of bounds: {ib}")
    if not (BOUNDS['Phib'][0] <= phib <= BOUNDS['Phib'][1]):
        raise ValueError(f"Phib out of bounds: {phib}")
    return {'Ib': ib, 'Phib': phib, 'rationale': str(decision['rationale'])[:3000]}


def invoke_codex(prompt: str, model: str | None, timeout: int, run_dir: Path, n: int) -> dict:
    cmd = docker_codex_cmd(model)
    # Docker only receives prompt on stdin. NO -v/-mount of a host folder, CSV, or source code.
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
    # Logs are HOST-SIDE only. Note that --output-schema prints structured JSON on stdout.
    (run_dir / f"model_{n:03d}_stderr.log").write_text(proc.stderr, encoding='utf-8')
    (run_dir / f"model_{n:03d}_output.json").write_text(proc.stdout, encoding='utf-8')
    if proc.returncode != 0:
        raise RuntimeError(f"Codex process returned {proc.returncode}: {proc.stderr[-1600:]}")
    return parse_decision(proc.stdout.strip())


def ensure_environment() -> None:
    for command in (["docker", "info", "--format", "{{.ServerVersion}}"],
                    ["docker", "image", "inspect", IMAGE]):
        p = subprocess.run(command, capture_output=True, text=True, timeout=15)
        if p.returncode != 0:
            raise RuntimeError('Docker/agent image not ready. See BLIND_CODEX_README.md. '+p.stderr[-400:])
    # SECURITY: assert the runtime command contains no host bind mounts.
    cmd = docker_codex_cmd()
    forbidden = {'--privileged', '--volumes-from', '--pid=host', '--network=host'}
    if any(t in forbidden for t in cmd):
        raise RuntimeError('Unsafe Docker invocation')
    mounts = [cmd[i+1] for i,v in enumerate(cmd[:-1]) if v == '--mount']
    if len(mounts) != 1 or 'type=volume' not in mounts[0]:
        raise RuntimeError('Agent must only have a dedicated auth named-volume mount')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', type=Path, default=Path(__file__).with_name('level2_emulator_240_snapshot.csv'))
    p.add_argument('--budget', type=int, default=10)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--landscape', choices=list(LANDSCAPES), default='qc_weighted')
    p.add_argument('--environment', choices=tuple(e for e in ENVIRONMENTS if e!='nonstationary_qc'), default='clean')
    p.add_argument('--objective', choices=['dpa','complex'], default='dpa')
    p.add_argument('--model', type=str, default=None, help='Optional Codex-accessible model ID')
    p.add_argument('--timeout', type=int, default=300, help='Maximum seconds per agent decision')
    p.add_argument('--out', type=Path, default=Path('codex_blind_results'))
    p.add_argument('--mock', action='store_true', help='TEST ONLY: fake agent; no Codex or Docker needed')
    a = p.parse_args()
    if a.budget < 1 or a.budget > 50 or a.timeout < 1:
        p.error('For pilot, budget must be 1..50 and timeout positive')
    if not a.mock: ensure_environment()

    sim = OfflineSimulator(a.data, landscape=a.landscape, environment=a.environment)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    root=(a.out / f'{stamp}_{uuid.uuid4().hex[:8]}_codex_{a.landscape}_{a.environment}_{a.seed}').resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root/'RUN_CONFIG.json').write_text(json.dumps({
        'requested_model':a.model or 'Codex CLI default','seed':a.seed,'budget':a.budget,
        'objective':a.objective,'emulator':sim.provenance(),'agent_image':IMAGE,
        'note':'Each decision uses stateless Codex exec with complete prior visible measurement history.'
    },indent=2)+'\n', encoding='utf-8')
    run_id=f'codex_blind_{uuid.uuid4().hex[:12]}'
    sim.start_run(run_id,a.seed)
    history=[]; hidden=[]
    dpa_dist=sim.reference_distribution(objective='dpa')
    comp_dist=sim.reference_distribution(objective='complex')
    print('Agent runtime:', 'MOCK (local dry-run)' if a.mock else 'Codex CLI in Docker')
    print(f'Landscape={a.landscape}; measurement={a.environment}; budget={a.budget}; seed={a.seed}')
    print(f'Saving to: {root}',flush=True)
    try:
        with (root/'evaluations.jsonl').open('w',encoding='utf-8') as public, \
             (root/'HIDDEN_GRADER_ONLY.jsonl').open('w',encoding='utf-8') as secret:
            for n in range(1,a.budget+1):
                prompt=agent_prompt(history,n,a.budget,a.objective)
                if a.mock:
                    # deterministic test; NOT a benchmark or language model performance result
                    decision={'Ib':10+(n*.371)%5,'Phib':(n*7.13)%70,'rationale':'mock plumbing test'}
                else:
                    decision=invoke_codex(prompt,a.model,a.timeout,root,n)
                decision=parse_decision(json.dumps(decision))
                dpa_true,comp_true=sim.latent_at(decision['Ib'],decision['Phib'])
                result=sim.evaluate_bias_point(decision['Ib'],decision['Phib'],run_id,n)
                item={'evaluation':n,'decision':{'Ib_uA':decision['Ib'],'Phib_uA':decision['Phib'],
                                                 'rationale':decision['rationale']},'result':result}
                truth={'evaluation':n,'Ib_uA':decision['Ib'],'Phib_uA':decision['Phib'],
                       'dpa':float(dpa_true),'complex':float(comp_true),
                       'qc_valid':bool(result['valid_for_comparison'])}
                history.append(item);hidden.append(truth)
                public.write(json.dumps(item,allow_nan=False)+'\n');public.flush()
                secret.write(json.dumps(truth,allow_nan=False)+'\n');secret.flush()
                print(f"{n:02d}/{a.budget}: ({decision['Ib']:.5f}, {decision['Phib']:.5f}) "
                      f"DPA={get_contrast(result,'dpa'):.2f} complex={get_contrast(result,'complex'):.2f} "
                      f"valid={result['valid_for_comparison']}",flush=True)
    except Exception:
        print('Partial results preserved at:',root,file=sys.stderr,flush=True)
        raise
    # Same scoring definitions as the random/adaptive baseline.
    pts=np.asarray([[h['decision']['Ib_uA'],h['decision']['Phib_uA']] for h in history])
    dpa_true=np.asarray([x['dpa'] for x in hidden]);comp_true=np.asarray([x['complex'] for x in hidden]);
    valid=np.asarray([x['qc_valid'] for x in hidden],dtype=bool)
    dp=np.searchsorted(dpa_dist,dpa_true,side='right') / len(dpa_dist) * 100
    cp=np.searchsorted(comp_dist,comp_true,side='right') / len(comp_dist) * 100
    main_p=dp if a.objective=='dpa' else cp
    main_true=dpa_true if a.objective=='dpa' else comp_true
    main_obs=np.asarray([get_contrast(x['result'],a.objective) for x in history])
    summary={
        'run_id':run_id,'model':a.model or 'Codex CLI default','seed':a.seed,'budget':a.budget,
        'landscape':a.landscape,'environment':a.environment,'objective':a.objective,
        'dataset_sha256':sim.sha256,'qc_valid_evaluations':int(valid.sum()),
        'best_latent_objective_db':float(main_true.max()),
        'best_latent_dpa_db':float(dpa_true.max()),
        'best_latent_complex_db':float(comp_true.max()),
        'best_map_percentile':float(main_p.max()),
        'top_10pct_queries':int((main_p >= 90).sum()),
        'best_valid_observed_objective_db':float(main_obs[valid].max()) if valid.any() else None,
        'best_latent_objective_among_qc_valid_db':float(main_true[valid].max()) if valid.any() else None,
        'warning':'Pilot benchmark on an estimated hidden map; measurement model is exploratory.'
    }
    (root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    with (root/'trajectory.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f)
        w.writerow(['evaluation','Ib_uA','Phib_uA','DPA_observed_dB','complex_observed_dB',
                    'qc_valid','DPA_hidden_db','complex_hidden_db','DPA_percentile','complex_percentile','rationale'])
        for h,t,d,c in zip(history,hidden,dp,cp):
            w.writerow([h['evaluation'],t['Ib_uA'],t['Phib_uA'],get_contrast(h['result'],'dpa'),
                        get_contrast(h['result'],'complex'),t['qc_valid'],t['dpa'],t['complex'],float(d),float(c),
                        h['decision']['rationale']])
    try:
        save_plot(sim,history,hidden,root/'trajectory.png',a.objective)
    except Exception as e:
        print('Plot failed, trajectory CSV and result JSON are intact:',e,file=sys.stderr)
    print('COMPLETED:',json.dumps(summary,indent=2),flush=True)
    print('Results:',root,flush=True)

if __name__=='__main__':main()
