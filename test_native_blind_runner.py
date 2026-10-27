import json
from pathlib import Path
import tempfile
import unittest
import tomllib
from unittest.mock import patch

from native_blind_runner import parse_decision, make_prompt, codex_cmd
from native_security import sandbox_cmd, PROFILE_OVERRIDES, FILESYSTEM_INLINE, assert_legacy_config_absent, is_permission_denial

class TestNativeBlind(unittest.TestCase):
    def test_parse_valid(self):
        x=parse_decision('{"Ib":11.5,"Phib":28.1,"rationale":"probe ridge"}')
        self.assertEqual(x['Ib'],11.5)
        self.assertEqual(x['Phib'],28.1)
    def test_invalid_points(self):
        for text in ('{"Ib":100,"Phib":2,"rationale":"no"}',
                     '{"Ib":11,"Phib":null,"rationale":"x"}',
                     '{"Ib":true,"Phib":5,"rationale":"x"}',
                     '{"Ib":11,"Phib":2,"rationale":"x","extra":1}'):
            with self.assertRaises(ValueError):parse_decision(text)
    def test_profile_overrides(self):
        # Verify the overrides form a valid TOML document rather than just
        # checking for strings. In particular, all filesystem rules are a
        # SINGLE inline map, avoiding the FilesystemPermissionToml bug.
        self.assertEqual(PROFILE_OVERRIDES.count('-c'), 3)
        arguments = [PROFILE_OVERRIDES[i + 1] for i, value in enumerate(PROFILE_OVERRIDES)
                     if value == '-c']
        parsed = tomllib.loads('\n'.join(arguments))
        self.assertEqual(parsed['default_permissions'], 'squid_blind')
        fs = parsed['permissions']['squid_blind']['filesystem']
        self.assertEqual(fs[':root'], 'deny')
        self.assertEqual(fs[':minimal'], 'read')
        self.assertEqual(fs[':workspace_roots']['.'], 'write')
        self.assertFalse(parsed['permissions']['squid_blind']['network']['enabled'])
        self.assertTrue(FILESYSTEM_INLINE.startswith('permissions.squid_blind.filesystem='))
        self.assertNotIn('sandbox_mode', ' '.join(PROFILE_OVERRIDES))
    def test_helper_explicit_profile(self):
        c=sandbox_cmd(Path('/tmp/agent'), ['/bin/cat','/tmp/secret'])
        self.assertEqual(c[:2],['codex','sandbox'])
        self.assertNotIn('macos', c[:3])
        self.assertIn('--permission-profile',c)
    def test_fail_closed_permission_detection(self):
        self.assertTrue(is_permission_denial('cat: foo: Operation not permitted'))
        self.assertTrue(is_permission_denial('ls: foo: Permission denied'))
        self.assertFalse(is_permission_denial('sandbox-exec: execvp() of macos failed: No such file or directory'))

    def test_codex_avoids_legacy_and_web(self):
        w=Path('/tmp/agent')
        c=codex_cmd(w,w/'decision.json','gpt-6-astra','medium')
        self.assertIn('features.shell_tool=false',c)
        self.assertIn('web_search="disabled"',c)
        self.assertNotIn('--sandbox',c)
        self.assertIn('default_permissions="squid_blind"',c)
        self.assertIn(str(w/'decision.schema.json'),c)
    def test_prompt_does_not_contain_hidden(self):
        pr=make_prompt([],1,3,'dpa')
        self.assertNotIn('DPA_hidden',pr)
        self.assertIn('Evaluation 1',pr)
    def test_legacy_user_config_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            c=Path(td)/'.codex'
            c.mkdir()
            (c/'config.toml').write_text('sandbox_mode="read-only"\n')
            with patch('native_security.Path.home',return_value=Path(td)):
                with self.assertRaises(RuntimeError):assert_legacy_config_absent()
    def test_mcp_user_config_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            c=Path(td)/'.codex'
            c.mkdir()
            (c/'config.toml').write_text('[mcp_servers.custom]\nurl="https://example.org"\n')
            with patch('native_security.Path.home',return_value=Path(td)):
                with self.assertRaises(RuntimeError):assert_legacy_config_absent()

if __name__=='__main__':unittest.main()

# Additional tests for strict one-session-per-campaign semantics.
import uuid
from types import SimpleNamespace
from native_blind_runner import (
    continuing_prompt, codex_cmd, invoke_codex, session_id_from_events,
)

class TestPersistentCodexSession(unittest.TestCase):
    def test_new_session_then_resume_same_id(self):
        w = Path('/agent')
        sid = '12345678-1234-4234-8234-123456789abc'
        first = codex_cmd(w, w/'decision_001.json','gpt-6-astra','medium')
        later = codex_cmd(w, w/'decision_002.json','gpt-6-astra','medium',sid)
        self.assertNotIn('--ephemeral',first)
        self.assertNotIn('--ephemeral',later)
        self.assertNotIn('resume',first)
        self.assertEqual(later[later.index('resume')+1],sid)
        self.assertIn('--json',first)
        self.assertIn('--output-schema',later)
        self.assertIn('default_permissions="squid_blind"',later)
        self.assertIn('features.shell_tool=false',later)

    def test_session_event_validation(self):
        sid = str(uuid.uuid4())
        msg = '\n'.join([
            json.dumps({'type':'thread.started','thread_id':sid}),
            json.dumps({'type':'turn.started'}),
            json.dumps({'type':'turn.completed','usage':{'input_tokens':100}}),
        ])
        self.assertEqual(session_id_from_events(msg,expected=sid),(sid,{'input_tokens':100}))
        with self.assertRaisesRegex(RuntimeError,'SESSION ISOLATION FAILURE'):
            session_id_from_events(msg,expected=str(uuid.uuid4()))
        with self.assertRaisesRegex(RuntimeError,'Forbidden agent tool activity'):
            session_id_from_events(msg+'\n'+json.dumps({'type':'item.completed','item':{'type':'command_execution'}}))
        with self.assertRaisesRegex(RuntimeError,'did not report exactly one completed'):
            session_id_from_events(json.dumps({'type':'thread.started','thread_id':sid}))

    def test_continuation_only_latest_public_measurement(self):
        old = {'evaluation':1,'decision':{'Ib_uA':12.5,'Phib_uA':35.0},
               'result':{'status':'completed','valid_for_comparison':True,
                         'quality_flags':[],
                         'metrics':{'gain_fit':{'contrast_db':5.62},
                                    'complex_fit':{'contrast_db':5.95}}}}
        # Use a function mock to avoid coupling this security test to the
        # emulator's implementation of the fit-result schema.
        with patch('native_blind_runner.get_contrast',side_effect=lambda result,which:5.62 if which=='dpa' else 5.95):
            prompt=continuing_prompt(old,2,50,'dpa')
        self.assertIn('evaluation 2 of 50',prompt.lower())
        self.assertIn('5.62',prompt)
        self.assertIn('5.95',prompt)
        self.assertNotIn('latent',prompt.lower())
        self.assertNotIn('percentile',prompt.lower())

    def test_same_uuid_across_two_invocations_and_no_history_replay(self):
        with tempfile.TemporaryDirectory() as td:
            w = Path(td)/'agent'; w.mkdir()
            r = Path(td)/'private'; r.mkdir()
            (w/'decision.schema.json').write_text('{}')
            sid = str(uuid.uuid4())
            calls=[]
            def fake_run(cmd,**kw):
                calls.append((cmd,kw['input']))
                n=len(calls)
                (w/f'decision_{n:03d}.json').write_text(
                    json.dumps({'Ib':12.5,'Phib':float(35+7*n),'rationale':f'test-{n}'})
                )
                events=[{'type':'thread.started','thread_id':sid},
                        {'type':'turn.started'},
                        {'type':'turn.completed','usage':{'output_tokens':20}}]
                return SimpleNamespace(returncode=0,stdout='\n'.join(map(json.dumps,events)),stderr='')
            with patch('native_blind_runner.subprocess.run',side_effect=fake_run):
                first,s1,_=invoke_codex(w,[],1,3,'dpa','gpt-6-astra','medium',20,r,None)
                hist=[{'evaluation':1,'decision':{'Ib_uA':first['Ib'],'Phib_uA':first['Phib']},
                       'result':{'status':'completed','valid_for_comparison':True,
                                 'quality_flags':[], 'metrics':{}}}]
                with patch('native_blind_runner.get_contrast',return_value=6.1):
                    second,s2,_=invoke_codex(w,hist,2,3,'dpa','gpt-6-astra','medium',20,r,s1)
            self.assertEqual(s1,s2)
            self.assertEqual(len(calls),2)
            self.assertNotIn('resume',calls[0][0])
            self.assertIn('resume',calls[1][0])
            self.assertEqual(calls[1][0][calls[1][0].index('resume')+1],sid)
            self.assertIn('test-2',second['rationale'])
            self.assertTrue((r/'codex_002_stdout.jsonl').is_file())
from native_blind_runner import assert_resume_cli_supported
class TestResumeCompatibility(unittest.TestCase):
    def test_resume_help_gate(self):
        helptext='--output-schema --output-last-message --json'
        with patch('native_blind_runner.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=helptext,stderr='')):
            assert_resume_cli_supported()
        with patch('native_blind_runner.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='--output-last-message',stderr='')):
            with self.assertRaisesRegex(RuntimeError,'required flags'):
                assert_resume_cli_supported()

# Added final-nomination and large-batch integrity tests.
from types import SimpleNamespace
import uuid
from native_blind_runner import (parse_nomination, final_nomination_prompt,
    invoke_final_nomination, grade_nomination, session_usage_snapshot,
    observation_for_agent)

class TestFinalNomination(unittest.TestCase):
    def test_parse_nomination_strict_and_existing(self):
        good=parse_nomination('{"selected_evaluation":2,"rationale":"Most repeatable."}',3)
        self.assertEqual(good['selected_evaluation'],2)
        for body in (
            '{"selected_evaluation":0,"rationale":"no"}',
            '{"selected_evaluation":4,"rationale":"no"}',
            '{"selected_evaluation":true,"rationale":"no"}',
            '{"selected_evaluation":2.0,"rationale":"no"}',
            '{"selected_evaluation":2,"rationale":""}',
            '{"selected_evaluation":2,"rationale":"yes","Ib":12.3}',
        ):
            with self.assertRaises(ValueError):parse_nomination(body,3)

    def test_nomination_prompt_gets_last_observation_not_hidden_score(self):
        last={
            'evaluation':3,'decision':{'Ib_uA':12.5,'Phib_uA':22.0},
            'result':{'status':'completed','valid_for_comparison':True,'quality_flags':[],
                      'metrics':{'contrast_uncertainty':{},'baseline':{},'gain_fit':{},'complex_fit':{}}}
        }
        with patch('native_blind_runner.get_contrast',side_effect=lambda r,k: 8.0 if k=='dpa' else 7.0):
            prompt=final_nomination_prompt(last,3,'dpa')
        self.assertIn('budget is now exhausted',prompt)
        self.assertIn('selected_evaluation',prompt)
        self.assertIn('8.0',prompt)
        self.assertNotIn('latent',prompt)
        self.assertNotIn('percentile',prompt)

    def test_nomination_resumes_same_codex_session_and_different_schema(self):
        with tempfile.TemporaryDirectory() as td:
            workspace=Path(td)/'agent';workspace.mkdir()
            results=Path(td)/'results';results.mkdir()
            sid=str(uuid.uuid4())
            last={'evaluation':3,'decision':{'Ib_uA':12.5,'Phib_uA':22.0},
                  'result':{'status':'completed','valid_for_comparison':True,
                            'quality_flags':[],'metrics':{}}}
            (workspace/'nomination.schema.json').write_text('{}')
            received=[]
            def fake_run(cmd,**kw):
                received.append((cmd,kw['input']))
                (workspace/'final_nomination.json').write_text(
                    json.dumps({'selected_evaluation':2,'rationale':'Two QC passes.'}))
                return SimpleNamespace(
                    returncode=0,
                    stdout='\n'.join(map(json.dumps,[
                        {'type':'thread.started','thread_id':sid},
                        {'type':'turn.completed','usage':{'input_tokens':8888}}
                    ])),stderr='')
            with patch('native_blind_runner.subprocess.run',side_effect=fake_run), \
                 patch('native_blind_runner.get_contrast',return_value=5.0):
                nomination,usage=invoke_final_nomination(
                    workspace,last,3,'dpa','gpt-6-astra','medium',30,results,sid)
            self.assertEqual(nomination['selected_evaluation'],2)
            self.assertEqual(usage['input_tokens'],8888)
            args,prompt=received[0]
            self.assertIn('resume',args)
            self.assertEqual(args[args.index('resume')+1],sid)
            self.assertIn(str(workspace/'nomination.schema.json'),args)
            self.assertNotIn('decision.schema.json',args)
            self.assertIn('budget is now exhausted',prompt)

    def test_nomination_scoring_requires_repeated_qc_validation(self):
        truth=[
            {'Ib_uA':12,'Phib_uA':30,'qc_valid':True,'dpa':9.,'complex':10.},
            {'Ib_uA':13,'Phib_uA':40,'qc_valid':False,'dpa':15.,'complex':14.},
            {'Ib_uA':12,'Phib_uA':30,'qc_valid':False,'dpa':9.,'complex':10.},
        ]
        history=[]
        for i,t in enumerate(truth):
            history.append({'evaluation':i+1,'result':{'metrics':{'gain_fit':{},'complex_fit':{}}}})
        with patch('native_blind_runner.get_contrast',return_value=9.5):
            scored=grade_nomination({'selected_evaluation':3,'rationale':'repeat'},
                                   history,truth,'dpa',
                                   [5,9,12,15], [6,10,12,14])
        self.assertEqual(scored['same_coordinate_attempts'],2)
        self.assertEqual(scored['same_coordinate_qc_passing'],1)
        self.assertTrue(scored['validated_by_at_least_one_qc_pass'])
        self.assertAlmostEqual(scored['selection_gap_db'],6)
        self.assertEqual(scored['valid_observed_mean_db'],9.5)

    def test_codex_usage_cumulative_not_summed(self):
        turns=[
            {'evaluation':1,'usage':{'input_tokens':100,'cached_input_tokens':0}},
            {'evaluation':2,'usage':{'input_tokens':240,'cached_input_tokens':100}},
            {'evaluation':'final_nomination',
             'usage':{'input_tokens':300,'cached_input_tokens':210}}
        ]
        u=session_usage_snapshot(turns)
        self.assertEqual(u['input_tokens'],300)
        self.assertEqual(u['cached_input_tokens'],210)
        self.assertTrue(u['includes_nomination_turn'])

