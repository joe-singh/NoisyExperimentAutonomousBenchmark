import json
import unittest
from blind_codex_runner import parse_decision, docker_codex_cmd, agent_prompt

class SecurityAndParsing(unittest.TestCase):
    def test_accept(self):
        x = parse_decision('{"Ib":11.1,"Phib":55,"rationale":"candidate"}')
        self.assertEqual(x['Ib'],11.1)
    def test_reject(self):
        for obj in [
          {'Ib':9,'Phib':5,'rationale':'invalid'},
          {'Ib':11,'Phib':90,'rationale':'invalid'},
          {'Ib':float('nan'),'Phib':15,'rationale':'invalid'},
          {'Ib':11,'Phib':20,'rationale':'fine','latent_map':999},
        ]:
            with self.assertRaises(ValueError): parse_decision(json.dumps(obj))
    def test_docker(self):
        cmd=docker_codex_cmd()
        self.assertNotIn('--privileged',cmd)
        self.assertNotIn('--network=host',cmd)
        self.assertNotIn('DPA-Emulator',' '.join(cmd))
        self.assertNotIn('--volume',cmd)
        mounts=[cmd[i+1] for i,c in enumerate(cmd[:-1]) if c=='--mount']
        self.assertEqual(len(mounts),1)
        self.assertIn('type=volume',mounts[0])
    def test_prompt(self):
        t=agent_prompt([],1,10,'dpa')
        self.assertIn('evaluation 1'.upper(),t.upper())
        self.assertNotIn('HIDDEN_GRADER_ONLY',t)

if __name__=='__main__': unittest.main()
