"""Run: python -m unittest test_offline test_stage_a test_stage_b -v"""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from offline_simulator import OfflineSimulator, LANDSCAPES
from measurement_model import ENVIRONMENTS
from run_offline import run_one

DATA=Path(__file__).with_name('level2_emulator_240_snapshot.csv')

@unittest.skipUnless(DATA.exists(), 'Place 240 snapshot CSV next to the scripts')
class TestStageB(unittest.TestCase):
    def test_all_landscapes_environments_finite(self):
        for landscape in LANDSCAPES:
            for env in ENVIRONMENTS:
                s=OfflineSimulator(DATA,landscape,env)
                s.start_run('test',42)
                vals=[]
                for n in range(1,15):
                    out=s.evaluate_bias_point(10. + n/4, float(5*n)%70, 'test',n)
                    self.assertTrue(np.isfinite(out['metrics']['gain_fit']['contrast_db']))
                    self.assertTrue(np.isfinite(out['metrics']['contrast_uncertainty']['complex']['estimate_db']))
                    self.assertNotIn('latent',str(out).lower())
                    vals.append(out)
                if env=='clean':
                    self.assertTrue(all(x['valid_for_comparison'] for x in vals))
                    self.assertTrue(all(x['status']=='completed' for x in vals))

    def test_reproducibility_independent_across_runs(self):
        s=OfflineSimulator(DATA,landscape='qc_weighted',environment='noisy_qc')
        s.start_run('one',101)
        s.start_run('two',101)
        for n in range(1,12):
            o1=s.evaluate_bias_point(12.,20.,'one',n)
            o2=s.evaluate_bias_point(12.,20.,'two',n)
            for part in ['metrics','quality_flags','valid_for_comparison']:
                self.assertEqual(o1[part],o2[part])
        # Different seed yields at least some distinct observations
        s.start_run('three',102)
        o3=s.evaluate_bias_point(12.,20.,'three',1)
        self.assertNotEqual(o1['metrics']['gain_fit']['contrast_db'],o3['metrics']['gain_fit']['contrast_db'])

    def test_invalid_results_are_not_ranked_for_observed_best(self):
        s=OfflineSimulator(DATA,landscape='original',environment='noisy_qc')
        d=s.reference_distribution(22,34,'dpa')
        with tempfile.TemporaryDirectory() as tmp:
            summ=run_one(s,'adaptive',101,50,Path(tmp)/'r',d,False,'dpa')
            self.assertEqual(summ['qc_valid_evaluations']+summ['qc_rejected_evaluations'],50)
            observations=[json.loads(line) for line in (Path(tmp)/'r'/'evaluations.jsonl').read_text().splitlines()]
            scores=[o['result']['metrics']['gain_fit']['contrast_db'] for o in observations if o['result']['valid_for_comparison']]
            self.assertEqual(summ['best_valid_observed_dpa_db'],max(scores) if scores else None)
            self.assertTrue((Path(tmp)/'r'/'HIDDEN_GRADER_ONLY.jsonl').exists())
            self.assertNotIn('DPA_latent_map_dB',(Path(tmp)/'r'/'evaluations.jsonl').read_text())

    def test_clean_legacy_trajectory_exact(self):
        s=OfflineSimulator(DATA, 'original', 'clean')
        dist=s.reference_distribution(objective='dpa')
        with tempfile.TemporaryDirectory() as tmp:
            summ=run_one(s,'adaptive',42,50,Path(tmp)/'r',dist,False,'dpa')
            self.assertAlmostEqual(summ['best_latent_dpa_db'],17.410903072412307)
            self.assertEqual(summ['qc_valid_evaluations'],50)

if __name__=='__main__':unittest.main()
