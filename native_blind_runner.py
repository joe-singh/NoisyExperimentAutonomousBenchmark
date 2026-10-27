"""Native macOS Codex blind SQUID benchmark pilot.

Trusted controller reads the CSV and scores responses. The Codex subprocess is
launched from a separate workspace with a strict filesystem permission profile.
Native Seatbelt checks must pass before any model inference. This is a pilot
for a restricted agent, NOT a guarantee against all non-shell integrations.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

import numpy as np

from native_security import PROFILE_OVERRIDES, run_security_preflight, assert_legacy_config_absent
from offline_simulator import BOUNDS, LANDSCAPES, OfflineSimulator
from measurement_model import ENVIRONMENTS
from run_offline import get_contrast, save_plot

HERE = Path(__file__).resolve().parent
SCHEMA = HERE/'native_agent'/'decision.schema.json'
NOMINATION_SCHEMA = HERE/'native_agent'/'nomination.schema.json'


def parse_decision(text: str) -> dict:
    try:
        d = json.loads(text)
    except (ValueError, TypeError) as e:
        raise ValueError(f'Invalid model JSON: {text[:300]!r}') from e
    if not isinstance(d, dict) or set(d) != {'Ib', 'Phib', 'rationale'}:
        raise ValueError(f'Unexpected JSON keys: {list(d) if isinstance(d,dict) else type(d)}')
    if any(isinstance(d[k], bool) or not isinstance(d[k], (float,int)) for k in ('Ib','Phib')):
        raise ValueError('Coordinate must be a real JSON number')
    ib, phib = float(d['Ib']), float(d['Phib'])
    if not all(map(math.isfinite, [ib, phib])):
        raise ValueError('Nonfinite coordinate')
    if not (BOUNDS['Ib'][0] <= ib <= BOUNDS['Ib'][1] and BOUNDS['Phib'][0] <= phib <= BOUNDS['Phib'][1]):
        raise ValueError('Out-of-range bias point')
    if not isinstance(d['rationale'], str):
        raise ValueError('rationale must be string')
    return dict(Ib=ib, Phib=phib, rationale=d['rationale'][:3000])


def make_prompt(history: list[dict], number: int, budget: int, objective: str, environment: str = "clean") -> str:
    header = [
        'You are an autonomous experimental physicist choosing SQUID bias operating points.',
        'Only choose Ib (10 to 15 microamperes) and Phib (0 to 70 microamperes).',
        f'Your objective is the largest reliable phase-sensitive {objective.upper()} fit contrast.',
        'You have exactly the stated measurement budget; you may repeat bias points.',
        'DPA and complex contrasts are both reported. Reject measurements with valid_for_comparison=false for ranking.',
        'These are fixed-procedure measurements; probe/pump amplitudes and QC cannot be changed.',
        'Make your next decision based ONLY on the recorded observations below.',
        'Do not look for a hidden map, files outside your experiment workspace, or old experimental runs.',
        'Do not use web search, integrations, MCP tools, or shell commands; make your own scientific decisions.',
        f'Evaluation {number} of {budget}. Respond only with the requested JSON decision.',
        'Previous experimental results in chronological order:'
    ]
    if environment == 'nonstationary_qc':
        header.insert(3, 'Measurement conditions can change persistently during this campaign: noise, measurement bias and QC reliability may vary over time. The underlying bias landscape is fixed. Identify the best underlying operating point using the available evidence. Each measurement advances simulated time equally; repeats consume budget. There is no wait or recalibration action. Fit intervals do not include systematic drift.')
    if not history:
        header.append('None.')
    for h in history:
        r = h['result']; m = r['metrics']
        a = {
            'number':h['evaluation'],
            'Ib':h['decision']['Ib_uA'], 'Phib':h['decision']['Phib_uA'],
            'status':r.get('status'), 'valid':r.get('valid_for_comparison'),
            'DPA_dB':get_contrast(r,'dpa'), 'complex_dB':get_contrast(r,'complex'),
            'fit_intervals':m.get('contrast_uncertainty'),
            'qc_flags':r.get('quality_flags',[]),
            'amplitude_R2':m.get('gain_fit',{}).get('r_squared_amplitude'),
            'complex_R2':m.get('complex_fit',{}).get('r_squared_complex'),
            'baseline_drift_pct':m.get('baseline',{}).get('amplitude_drift_percent'),
        }
        header.append(json.dumps(a, separators=(',',':'), allow_nan=False))
    header.append('Return a JSON object with Ib, Phib and concise rationale.')
    return '\n'.join(header)


def codex_cmd(workspace: Path, answer_file: Path, model: str, effort: str,
              session_id: str | None = None, *, schema_name: str = 'decision.schema.json') -> list[str]:
    """New session on first call; resume the exact session UUID thereafter.

    No --ephemeral: Codex must retain the transcript for exec resume.
    The same filesystem restrictions are applied to both calls.
    """
    if schema_name not in ('decision.schema.json','nomination.schema.json'):
        raise RuntimeError('Unrecognized agent response schema')
    if not answer_file.is_relative_to(workspace):
        raise RuntimeError('Model answer file must be inside agent workspace')
    if '--sandbox' in PROFILE_OVERRIDES:
        raise RuntimeError('Legacy sandbox override is forbidden')
    if session_id is not None:
        try: uuid.UUID(session_id)
        except (ValueError, TypeError) as exc:
            raise ValueError('Invalid session UUID') from exc
    return [
        'codex', '--disable', 'apps', *PROFILE_OVERRIDES,
        '-c', 'web_search="disabled"',
        '-c', 'tools.web_search=false',
        '-c', 'features.shell_tool=false',
        '-c', 'approval_policy="never"',
        'exec', '--json', '--skip-git-repo-check',
        '--model', model,
        '--config', f'model_reasoning_effort={effort}',
        '--output-schema', str(workspace/schema_name),
        '--output-last-message', str(answer_file),
        *(['resume', session_id, '-'] if session_id is not None else ['-']),
    ]


def observation_for_agent(item: dict) -> dict:
    """Only public measurement fields, never latent values or scores."""
    r = item['result']; m = r['metrics']
    return {
        'number': item['evaluation'],
        **({'simulated_elapsed_s':r['simulated_elapsed_s']} if 'simulated_elapsed_s' in r else {}),
        'Ib': item['decision']['Ib_uA'], 'Phib': item['decision']['Phib_uA'],
        'status': r.get('status'), 'valid': r.get('valid_for_comparison'),
        'DPA_dB': get_contrast(r,'dpa'), 'complex_dB': get_contrast(r,'complex'),
        'fit_intervals': m.get('contrast_uncertainty'),
        'qc_flags': r.get('quality_flags',[]),
        'amplitude_R2': m.get('gain_fit',{}).get('r_squared_amplitude'),
        'complex_R2': m.get('complex_fit',{}).get('r_squared_complex'),
        'baseline_drift_pct': m.get('baseline',{}).get('amplitude_drift_percent'),
    }


def continuing_prompt(last_item: dict, number: int, budget: int, objective: str) -> str:
    """One experiment, one conversation. Only the newest observation is added.

    All previous decisions, rationales and observations are already in the
    saved Codex thread, so re-sending the entire transcript is unnecessary.
    """
    observed = observation_for_agent(last_item)
    return '\n'.join([
        f'Continue the SAME SQUID experiment, with the same {objective.upper()} objective.',
        'The trusted measurement controller has completed your previous request.',
        'New measurement result:',
        json.dumps(observed, separators=(',', ':'), allow_nan=False),
        f'Now choose evaluation {number} of {budget}. Remember your earlier strategy and reasoning.',
        'Treat valid=false results as invalid for objective ranking. You may repeat measurements.',
        'Respond only with a JSON object containing Ib, Phib, rationale.',
    ])


def session_id_from_events(jsonl: str, expected: str | None = None) -> tuple[str, dict]:
    """Fail closed if Codex didn't complete a turn on the expected thread.

    Also flag tool activity forbidden in the decision-only benchmark.
    """
    events = []
    for line in jsonl.splitlines():
        if not line.strip(): continue
        try: event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError('Codex --json output contains invalid JSONL') from exc
        if not isinstance(event, dict):
            raise RuntimeError('Unexpected Codex --json event')
        events.append(event)
    ids = [e.get('thread_id') for e in events if e.get('type') == 'thread.started']
    if len(ids) != 1 or not isinstance(ids[0],str):
        raise RuntimeError(f'Expected exactly one Codex thread.started event, got {ids!r}')
    sid = ids[0]
    try: uuid.UUID(sid)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f'Invalid session id in Codex event stream: {sid!r}') from exc
    if expected is not None and sid != expected:
        raise RuntimeError(f'SESSION ISOLATION FAILURE: resumed {sid}, expected {expected}')
    if any(e.get('type') in ('turn.failed','error') for e in events):
        raise RuntimeError('Codex JSONL reports an incomplete or failed turn')
    if sum(e.get('type') == 'turn.completed' for e in events) != 1:
        raise RuntimeError('Codex did not report exactly one completed turn')
    forbidden = {'command_execution','file_change','mcp_tool_call','web_search'}
    activities = sorted({e.get('item',{}).get('type') for e in events
                         if isinstance(e.get('item'),dict) and e['item'].get('type') in forbidden})
    if activities:
        raise RuntimeError(f'Forbidden agent tool activity observed: {activities}')
    usage = next((e.get('usage',{}) for e in events if e.get('type')=='turn.completed'), {})
    return sid, usage


def invoke_codex(workspace: Path, history: list[dict], number: int, budget: int,
                 objective: str, model: str, effort: str, timeout: int, results: Path,
                 session_id: str | None = None, environment: str = "clean") -> tuple[dict, str, dict]:
    """Call Codex once and continue the same durable thread after evaluation 1."""
    if (number == 1) != (session_id is None):
        raise RuntimeError('First evaluation must start a session; all later evaluations must resume it')
    answer_file = workspace / f'decision_{number:03d}.json'
    if answer_file.exists():
        raise RuntimeError('Decision path collision')
    prompt = (make_prompt([], number, budget, objective, environment) if number==1 else
              continuing_prompt(history[-1], number, budget, objective))
    proc = subprocess.run(codex_cmd(workspace,answer_file,model,effort,session_id),
                          cwd=workspace, input=prompt, capture_output=True, text=True,
                          timeout=timeout, check=False)
    (results/f'codex_{number:03d}_stdout.jsonl').write_text(proc.stdout,encoding='utf-8')
    (results/f'codex_{number:03d}_stderr.log').write_text(proc.stderr,encoding='utf-8')
    if proc.returncode != 0:
        raise RuntimeError(f'Codex exit code {proc.returncode}; tail: {proc.stderr[-800:]}')
    sid, usage = session_id_from_events(proc.stdout, session_id)
    if not answer_file.is_file():
        raise RuntimeError('Codex returned without writing structured answer file')
    return parse_decision(answer_file.read_text(encoding='utf-8')), sid, usage



def parse_nomination(text: str, budget: int) -> dict:
    """Nominate an evaluation number, never unconstrained novel coordinates."""
    try:
        d = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ValueError('Final nomination was not valid JSON') from exc
    if not isinstance(d, dict) or set(d) != {'selected_evaluation','rationale'}:
        raise ValueError('Final nomination keys must be selected_evaluation and rationale')
    n = d['selected_evaluation']
    if type(n) is not int or not 1 <= n <= budget:
        raise ValueError('Final nomination must identify a previously completed evaluation')
    if not isinstance(d['rationale'], str) or not d['rationale'].strip():
        raise ValueError('Final nomination requires a nonempty rationale')
    return {'selected_evaluation':n,'rationale':d['rationale'][:5000]}


def final_nomination_prompt(last_item: dict, budget: int, objective: str) -> str:
    """One extra decision turn, NO new physical/simulated measurement."""
    return '\n'.join([
        'The measurement budget is now exhausted. DO NOT request or suggest another measurement.',
        f'The {budget}th (final) measurement has just completed. Here is its result:',
        json.dumps(observation_for_agent(last_item),separators=(',',':'),allow_nan=False),
        f'Your original optimization objective was the largest reliable {objective.upper()} fit contrast.',
        'You must now make ONE FINAL operating-point nomination from points that you actually measured.',
        'Choose a single previous EVALUATION NUMBER (1 through the experiment budget), not a new coordinate.',
        'If a coordinate was measured repeatedly, you may select any one of its evaluation numbers.',
        'Consider QC flags, valid measurements, repeatability, DPA/complex agreement, and fit uncertainty.',
        'A rejected fit must not be presented as validated evidence. You may nominate a point without QC-valid evidence',
        'if scientifically justified, but explicitly disclose the uncertainty in your rationale.',
        'Your answer must be JSON with exactly selected_evaluation (integer) and rationale (string).',
        'This is a NOMINATION turn only: it DOES NOT consume an evaluation or return additional data.',
    ])


def invoke_final_nomination(workspace: Path, last_item: dict, budget: int,
                            objective: str, model: str, effort: str,
                            timeout: int, results: Path, session_id: str) -> tuple[dict, dict]:
    """Continue the measurement session once, with a *different* structured schema."""
    if not session_id:
        raise RuntimeError('Cannot nominate without a persistent Codex session')
    answer_file=workspace/'final_nomination.json'
    if answer_file.exists():
        raise RuntimeError('Nomination path collision')
    prompt=final_nomination_prompt(last_item,budget,objective)
    cmd=codex_cmd(workspace, answer_file, model, effort, session_id,
                  schema_name='nomination.schema.json')
    proc=subprocess.run(cmd, cwd=workspace, input=prompt,
                        capture_output=True,text=True,timeout=timeout,check=False)
    (results/'codex_nomination_stdout.jsonl').write_text(proc.stdout,encoding='utf-8')
    (results/'codex_nomination_stderr.log').write_text(proc.stderr,encoding='utf-8')
    if proc.returncode != 0:
        raise RuntimeError(f'Codex nomination exit code {proc.returncode}: {proc.stderr[-800:]}')
    sid,usage=session_id_from_events(proc.stdout,session_id)
    if sid!=session_id or not answer_file.is_file():
        raise RuntimeError('Nomination did not complete in the expected session')
    return parse_nomination(answer_file.read_text(encoding='utf-8'),budget), usage


def grade_nomination(nomination: dict, history: list[dict], truth: list[dict],
                     objective: str, dpd, cod) -> dict:
    """Trusted host-only scoring, never passed back to the agent."""
    n=nomination['selected_evaluation']
    if n > len(history) or n < 1 or len(history)!=len(truth):
        raise RuntimeError('Nomination does not refer to completed observations')
    chosen=truth[n-1]
    ib,phib=chosen['Ib_uA'],chosen['Phib_uA']
    # Repeats at identical requested coordinates are counted together.
    matched=[i for i,t in enumerate(truth) if t['Ib_uA']==ib and t['Phib_uA']==phib]
    valid=[i for i in matched if truth[i]['qc_valid']]
    accepted_observed=[get_contrast(history[i]['result'],objective) for i in valid]
    dpa=chosen['dpa']; comp=chosen['complex']
    assert objective in ('dpa','complex')
    tru=chosen[objective]
    best=max(t[objective] for t in truth)
    return {
        'selected_evaluation':n,'Ib_uA':ib,'Phib_uA':phib,
        'rationale':nomination['rationale'],
        'latent_dpa_db':float(dpa),'latent_complex_db':float(comp),
        'latent_dpa_percentile':float(np.searchsorted(dpd,dpa,side='right')/len(dpd)*100),
        'latent_complex_percentile':float(np.searchsorted(cod,comp,side='right')/len(cod)*100),
        'nominated_objective':objective,
        'nominated_objective_latent_db':float(tru),
        'selection_gap_db':float(best-tru),
        'same_coordinate_attempts':len(matched),
        'same_coordinate_qc_passing':len(valid),
        'valid_observed_mean_db':float(np.mean(accepted_observed)) if accepted_observed else None,
        'validated_by_at_least_one_qc_pass':bool(valid),
    }


def session_usage_snapshot(turns: list[dict]) -> dict:
    """Codex CLI 0.162.1 reports *cumulative* token counters per session.

    The final turn's counters are the campaign totals. DO NOT add snapshots.
    Preserve all individual Codex JSONL events for auditing version changes.
    """
    keys=('input_tokens','cached_input_tokens','output_tokens','total_tokens',
          'reasoning_output_tokens')
    final = turns[-1].get('usage',{}) if turns else {}
    return {k:float(final[k]) for k in keys if final.get(k) is not None} | {
        'accounting':'last_codex_turn_cumulative_session_counters',
        'includes_nomination_turn':bool(turns and turns[-1].get('evaluation')=='final_nomination'),
    }


def atomic_json(path: Path, value: dict) -> None:
    """Save a crash-resilient batch manifest, replacing the prior version."""
    pending = path.with_suffix(path.suffix+'.pending')
    pending.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    pending.replace(path)


def batch_main(a):
    """Sequential independent campaigns with resumable *between-campaign* manifest.

    A failed partial campaign is kept for forensics. Resumption starts that
    trial afresh with the same simulator seed but a new Codex conversation.
    """
    keys=('data','agent_root','out','budget','landscape','environment','objective',
          'model','effort','timeout','seed','repeats','mock','disturbance_profile')
    if a.resume_batch:
        path=a.resume_batch.expanduser().resolve()
        m=json.loads(path.read_text(encoding='utf-8'))
        if m.get('schema_version')!=2 or m.get('status')=='completed':
            raise RuntimeError('Batch is not a resumable version-2, incomplete manifest')
        cfg=m['config']
        for key in keys:
            if key == 'disturbance_profile' and key not in cfg and cfg.get('environment') != 'nonstationary_qc': cfg[key]='moderate'
            if key not in cfg: raise RuntimeError('Incomplete batch manifest')
            value=cfg[key]
            if key in ('data','agent_root','out'):
                value=Path(value)
            setattr(a,key,value)
        if a.environment == 'nonstationary_qc':
            from environment_model import EnvironmentProcess, EnvironmentSettings
            expected=EnvironmentProcess(0,EnvironmentSettings(profile=a.disturbance_profile)).provenance()
            if m.get('environment_provenance') != expected: raise RuntimeError('Environment version/settings/anchors changed; start a new batch')
        if a.repeats<=1: raise RuntimeError('Resume manifest requires a multi-campaign batch')
        print(f'Resuming batch from manifest: {path}',flush=True)
    else:
        if a.repeats<=1: raise RuntimeError('Batch must contain more than one campaign')
        batch_stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        batch_label=f'{batch_stamp}_batch_{uuid.uuid4().hex[:8]}'
        path = a.out.expanduser().resolve()/f'{batch_label}.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        cfg={k:(str(getattr(a,k).expanduser().resolve()) if k in ('data','agent_root','out')
                else getattr(a,k)) for k in keys}
        m={'schema_version':2,'status':'running','config':cfg,'target':a.repeats,
           'completed':[],'attempts':[]}
        if a.environment == 'nonstationary_qc':
            from environment_model import EnvironmentProcess, EnvironmentSettings
            m['environment_provenance']=EnvironmentProcess(0,EnvironmentSettings(profile=a.disturbance_profile)).provenance()
        atomic_json(path,m)
        print('Batch manifest:',path,flush=True)
    root=a.out.expanduser().resolve()
    root.mkdir(parents=True,exist_ok=True)
    seen=set()
    # Validate existing completed records before making further model calls.
    for record in m['completed']:
        d=Path(record['result_dir'])
        if not (d/'summary.json').is_file():
            raise RuntimeError(f'Previously completed trial missing summary: {d}')
        sm=json.loads((d/'summary.json').read_text(encoding='utf-8'))
        if not (d/'FINAL_NOMINATION.json').exists():
            raise RuntimeError(f'Previously completed trial has no final nomination: {d}')
        if sm.get('codex_session_id')!=record.get('codex_session_id'):
            raise RuntimeError('Completed session record mismatch')
        if not a.mock:
            if not record['codex_session_id'] or record['codex_session_id'] in seen:
                raise RuntimeError('Duplicate/missing Codex session in prior trials')
            seen.add(record['codex_session_id'])
    remaining=a.repeats-len(m['completed'])
    if remaining<0:
        raise RuntimeError('More completed records than configured trials')
    to_run=min(remaining,a.max_new_trials) if a.max_new_trials>0 else remaining
    common=['--data',str(a.data),'--agent-root',str(a.agent_root),
            '--out',str(a.out),'--budget',str(a.budget),
            '--landscape',a.landscape,'--environment',a.environment,
            '--objective',a.objective,'--model',a.model,'--effort',a.effort,
            '--timeout',str(a.timeout),'--repeats','1','--disturbance-profile',a.disturbance_profile]
    if a.mock: common.append('--mock')
    for _ in range(to_run):
        rep=len(m['completed'])
        seed=a.seed+rep
        print(f'\n=== Independent trial {rep+1}/{a.repeats}: seed {seed} ===',flush=True)
        before={d.name for d in root.iterdir() if d.is_dir()}
        try:
            proc=subprocess.run([sys.executable,str(HERE/'native_blind_runner.py'),
                                 *common,'--seed',str(seed)],check=False)
        except KeyboardInterrupt:
            m['status']='interrupted';m['failure']='Interrupted by user during campaign'
            atomic_json(path,m)
            raise
        fresh=[d for d in root.iterdir() if d.is_dir() and d.name not in before]
        attempt={'trial':rep+1,'seed':seed,'created_dirs':[str(d) for d in fresh],
                 'exit_code':proc.returncode}
        m['attempts'].append(attempt)
        if proc.returncode!=0 or len(fresh)!=1 or not (fresh[0]/'summary.json').is_file():
            m['status']='interrupted';m['failure']=f'Trial {rep+1} failed or incomplete'
            atomic_json(path,m)
            raise RuntimeError(f'Trial {rep+1} failed. Existing results preserved. '
                               f'Resume with --resume-batch {path}')
        result_dir=fresh[0]
        sm=json.loads((result_dir/'summary.json').read_text(encoding='utf-8'))
        sid=sm.get('codex_session_id')
        turns=json.loads((result_dir/'CODEX_TURNS.json').read_text(encoding='utf-8')) if not a.mock else []
        if (sm.get('seed')!=seed or sm.get('budget')!=a.budget or
            not (result_dir/'FINAL_NOMINATION.json').is_file() or
            not (result_dir/'HIDDEN_NOMINATION_SCORE.json').is_file() or
            'nomination' not in sm or
            (not a.mock and (not sid or sid in seen or len(turns)!=a.budget+1 or
                             any(t.get('session_id')!=sid for t in turns)))):
            m['status']='interrupted';m['failure']='Campaign completeness/session verification failed'
            atomic_json(path,m)
            raise RuntimeError(f'Trial {rep+1} integrity check failed. STOP and inspect {result_dir}')
        if not a.mock: seen.add(sid)
        m['completed'].append({
            'trial':rep+1,'seed':seed,'result_dir':str(result_dir),
            'codex_session_id':sid,'valid_count':sm['valid_count'],
            'best_underlying_percentile':sm['best_underlying_percentile'],
            'nomination':sm['nomination'],
            'inference_usage_reported':sm['inference_usage_reported'],
            'wall_time_seconds':sm.get('wall_time_seconds')})
        m.pop('failure',None)
        m['status']='running'
        atomic_json(path,m)
    m['status']='completed' if len(m['completed'])==a.repeats else 'paused'
    m['unique_codex_sessions']=len(seen)
    atomic_json(path,m)
    print(f'Batch status: {m["status"]}; {len(m["completed"])}/{a.repeats} campaigns.',flush=True)
    print('Manifest:',path,flush=True)
    if m['status']=='paused': print(f'Continue using: python native_blind_runner.py --resume-batch "{path}"',flush=True)


def assert_resume_cli_supported() -> None:
    """Catch unsupported Codex CLI versions before using any inference."""
    proc = subprocess.run(['codex','exec','resume','--help'],
                          capture_output=True,text=True,timeout=20,check=False)
    help_text = (proc.stdout or '') + (proc.stderr or '')
    if proc.returncode != 0:
        raise RuntimeError(f'Codex resume command unavailable: {help_text[-600:]}')
    missing = [flag for flag in ('--output-schema','--output-last-message','--json')
               if flag not in help_text]
    if missing:
        raise RuntimeError('Your Codex CLI resume command does not advertise required flags: '
                           + ', '.join(missing) + '. Upgrade Codex CLI before testing.')

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,default=HERE/'level2_emulator_240_snapshot.csv')
    p.add_argument('--agent-root',type=Path,default=Path.home()/'Desktop'/'DPA-Agent-Workspace')
    p.add_argument('--out',type=Path,default=Path('codex_native_results'))
    p.add_argument('--budget',type=int,default=3)
    p.add_argument('--repeats',type=int,default=1,help='Independent campaigns; each creates a fresh Codex session')
    p.add_argument('--max-new-trials',type=int,default=0,help='For a big batch, run only N more full campaigns then pause (0=all)')
    p.add_argument('--resume-batch',type=Path,default=None,help='Resume a paused/interrupted batch manifest; no campaign is resumed mid-run')
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--landscape',choices=list(LANDSCAPES),default='qc_weighted')
    p.add_argument('--environment',choices=ENVIRONMENTS,default='clean')
    p.add_argument('--disturbance-profile',choices=['mild','moderate','severe'],default='moderate')
    p.add_argument('--objective',choices=['dpa','complex'],default='dpa')
    p.add_argument('--model',default='gpt-6-astra')
    p.add_argument('--effort',choices=['low','medium','high','xhigh'],default='medium')
    p.add_argument('--timeout',type=int,default=300)
    p.add_argument('--preflight-only',action='store_true')
    p.add_argument('--mock',action='store_true',help='Test harness only; not a model run')
    a = p.parse_args(argv)
    if a.budget not in range(1,51) or a.timeout<1 or not (1 <= a.repeats <= 1000):
        p.error('Budget must be 1–50; timeout must be positive; repeats must be 1–1000')
    if a.max_new_trials<0:
        p.error('--max-new-trials must be nonnegative')
    if a.resume_batch or a.repeats>1:
        if a.preflight_only: raise RuntimeError('Run preflight separately before batches')
        batch_main(a)
        return
    private = a.data.expanduser().resolve()
    agent_root = a.agent_root.expanduser().resolve()
    results_root = a.out.expanduser().resolve()
    if not private.is_file():
        raise FileNotFoundError(f'Missing emulator data: {private}')
    if results_root == agent_root or results_root in agent_root.parents or agent_root in results_root.parents:
        raise RuntimeError('Agent and private results directories must not overlap')
    if agent_root == private.parent or agent_root in private.parents or private in agent_root.parents:
        raise RuntimeError('Agent workspace cannot contain the hidden map')
    if (agent_root/'.codex').exists() or (agent_root/'AGENTS.md').exists():
        raise RuntimeError('Agent root must not contain .codex or AGENTS.md')
    if not SCHEMA.is_file() or not NOMINATION_SCHEMA.is_file():
        raise FileNotFoundError('Missing decision or nomination schema; extract native_agent/*.json')

    # Always perform same OS-level probes before running the model; no flag skips this.
    workspace = agent_root/'security_probe'
    if not a.mock:
        run_security_preflight(workspace,private)
        assert_resume_cli_supported()
    if a.preflight_only:
        print('Preflight complete; no model called.'); return

    sim = OfflineSimulator(private, landscape=a.landscape, environment=a.environment, disturbance_profile=a.disturbance_profile)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    token=uuid.uuid4().hex[:10]
    run_id=f'native_{token}'
    run_out=results_root/f'{stamp}_{token}_{a.model}_{a.seed}'
    run_out.mkdir(parents=True,exist_ok=False)
    agent_space=agent_root/f'run_{token}'
    agent_space.mkdir(parents=True,exist_ok=False)
    if any(x.exists() for x in (agent_space/'.codex',agent_space/'AGENTS.md')):
        raise RuntimeError('Unclean agent workspace')
    shutil.copyfile(SCHEMA, agent_space/'decision.schema.json')
    shutil.copyfile(NOMINATION_SCHEMA, agent_space/'nomination.schema.json')
    if not a.mock:
        # Check the actual run's workspace as well as the generic preflight directory.
        run_security_preflight(agent_space, private)
    config = {
        'runtime':'native_macOS_seatbelt', 'model':a.model, 'reasoning_effort':a.effort,
        'budget':a.budget, 'seed':a.seed, 'landscape':a.landscape,
        'environment':a.environment, 'objective':a.objective, 'emulator':sim.provenance(),
        'dataset_hash':sim.sha256,'codex_command_config':PROFILE_OVERRIDES,
        'agent_workspace':str(agent_space),'note':'one durable Codex session per campaign, resumed by exact UUID for each new measurement; only newest observation supplied',
        'codex_session_policy':'new session at evaluation 1; same session at evaluations 2..budget AND nomination; fresh new session for each repeat',
        'final_nomination_required':True,'nomination_consumes_evaluation':False,
        'limitations':'Seatbelt profile applies to local commands; separately audit built-in apps, MCP and non-shell paths.'
    }
    (run_out/'RUN_CONFIG.json').write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
    sim.start_run(run_id,a.seed)
    run_start=time.monotonic()
    history=[];truth=[]
    session_id=None
    session_usage=[]
    print('Native sandbox preflight PASSED.' if not a.mock else 'MOCK software test (Seatbelt not tested).',flush=True)
    print('Results:',run_out,flush=True)
    try:
        with (run_out/'evaluations.jsonl').open('w',encoding='utf-8') as public, \
             (run_out/'HIDDEN_GRADER_ONLY.jsonl').open('w',encoding='utf-8') as hidden:
            for n in range(1,a.budget+1):
                if a.mock:
                    decision={'Ib':10+(n*.371)%5,'Phib':(n*7.13)%70,'rationale':'MOCK test only'}
                else:
                    decision, session_id, usage=invoke_codex(
                        agent_space,history,n,a.budget,a.objective,a.model,a.effort,
                        a.timeout,run_out,session_id=session_id,environment=a.environment)
                    session_usage.append({'evaluation':n,'session_id':session_id,'usage':usage})
                    # Record the session ID after the first decision, so a failed
                    # campaign still exposes an unambiguous partial thread record.
                    (run_out/'CODEX_SESSION_ID.txt').write_text(session_id+'\n',encoding='utf-8')
                    (run_out/'CODEX_TURNS.json').write_text(json.dumps(session_usage,indent=2)+'\n',encoding='utf-8')
                decision=parse_decision(json.dumps(decision))
                latent_dpa,latent_complex=sim.latent_at(decision['Ib'],decision['Phib'])
                result=sim.evaluate_bias_point(decision['Ib'],decision['Phib'],run_id,n)
                item={'evaluation':n,'decision':{'Ib_uA':decision['Ib'],'Phib_uA':decision['Phib'],
                                                 'rationale':decision['rationale']},'result':result}
                t={'evaluation':n,'Ib_uA':decision['Ib'],'Phib_uA':decision['Phib'],
                   'dpa':float(latent_dpa),'complex':float(latent_complex),
                   'qc_valid':bool(result['valid_for_comparison'])}
                if a.environment == 'nonstationary_qc': t['environment_state']=sim.hidden_environment_state(run_id)
                history.append(item);truth.append(t)
                public.write(json.dumps(item,allow_nan=False)+'\n');public.flush()
                hidden.write(json.dumps(t,allow_nan=False)+'\n');hidden.flush()
                print(f'{n:02d}/{a.budget}: Ib={decision["Ib"]:.5f} Phib={decision["Phib"]:.5f} '
                      f'DPA={get_contrast(result,"dpa"):.2f} complex={get_contrast(result,"complex"):.2f} '
                      f'QC={result["valid_for_comparison"]}',flush=True)
    except Exception:
        print('Partial outputs saved:',run_out, file=sys.stderr,flush=True)
        raise
    # Final nomination is mandatory for a completed campaign. It is an extra
    # Codex turn but *never* calls sim.evaluate_bias_point or consumes budget.
    try:
        if a.mock:
            final_nomination = {'selected_evaluation':a.budget,
                                'rationale':'MOCK: last point; no inference.'}
            nomination_usage={}
        else:
            final_nomination,nomination_usage=invoke_final_nomination(
                agent_space,history[-1],a.budget,a.objective,a.model,a.effort,
                a.timeout,run_out,session_id)
            session_usage.append({'evaluation':'final_nomination','session_id':session_id,
                                  'usage':nomination_usage})
            (run_out/'CODEX_TURNS.json').write_text(json.dumps(session_usage,indent=2)+'\n',encoding='utf-8')
        (run_out/'FINAL_NOMINATION.json').write_text(json.dumps(final_nomination,indent=2)+'\n',encoding='utf-8')
    except Exception:
        print('Nomination failed; completed measurements preserved at:',run_out,
              file=sys.stderr,flush=True)
        raise
    dpd=sim.reference_distribution(objective='dpa'); cod=sim.reference_distribution(objective='complex')
    dp=np.searchsorted(dpd,[r['dpa'] for r in truth],side='right')/len(dpd)*100
    cp=np.searchsorted(cod,[r['complex'] for r in truth],side='right')/len(cod)*100
    valid=np.asarray([r['qc_valid'] for r in truth],dtype=bool)
    obs=np.array([get_contrast(x['result'],a.objective) for x in history])
    tru=np.array([x[a.objective] for x in truth])
    percent=dp if a.objective=='dpa' else cp
    nomination_grade=grade_nomination(final_nomination,history,truth,a.objective,dpd,cod)
    (run_out/'HIDDEN_NOMINATION_SCORE.json').write_text(json.dumps(nomination_grade,indent=2)+'\n',encoding='utf-8')
    summary={'run_id':run_id,'model':a.model,'effort':a.effort,'budget':a.budget,'seed':a.seed,
             'codex_session_id':session_id, 'emulator':sim.provenance(),
             'nomination':nomination_grade, 'inference_usage_reported':session_usage_snapshot(session_usage),
             'wall_time_seconds':float(time.monotonic()-run_start),
             'valid_count':int(valid.sum()),'best_latent_dpa_db':float(max(t['dpa'] for t in truth)),
             'best_latent_complex_db':float(max(t['complex'] for t in truth)),
             'best_underlying_percentile':float(percent.max()),
             'top_decile_queries':int((percent>=90).sum()),
             'best_valid_observed':float(obs[valid].max()) if valid.any() else None,
             'best_latent_on_valid':float(tru[valid].max()) if valid.any() else None,
             'disclaimer':'Exploratory reconstructed map / simulated QC, not physical truth'}
    (run_out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    with (run_out/'trajectory.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['evaluation','Ib','Phib','DPA_obs','complex_obs','QC_valid',
                                   'DPA_latent','complex_latent','DPA_percentile','complex_percentile','rationale'])
        for h,t,d,c in zip(history,truth,dp,cp):
            w.writerow([h['evaluation'],t['Ib_uA'],t['Phib_uA'],get_contrast(h['result'],'dpa'),
                        get_contrast(h['result'],'complex'),t['qc_valid'],t['dpa'],t['complex'],float(d),float(c),
                        h['decision']['rationale']])
    try:save_plot(sim,history,truth,run_out/'trajectory.png',a.objective)
    except Exception as ex:print('Plotting failed; underlying files intact:',ex,file=sys.stderr)
    print('COMPLETED:',json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':
    main()
