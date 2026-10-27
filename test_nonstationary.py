import json,tempfile,unittest
from pathlib import Path
import numpy as np
from offline_simulator import OfflineSimulator
from environment_model import EnvironmentProcess,EnvironmentSettings
from native_blind_runner import observation_for_agent,make_prompt
DATA=Path(__file__).with_name('level2_emulator_240_snapshot.csv')
class TestNonstationary(unittest.TestCase):
    def test_neighbor_ties_at_selection_boundary(self):
        from nonstationary_measurement import deterministic_neighbors
        xy=np.array([[.65,0],[-.65,0],[0,6],[0,-6],[0,0]],float)
        ii,w=deterministic_neighbors(xy,0,0,3)
        self.assertEqual(ii.tolist(),[4,0,1])
        self.assertAlmostEqual(w[1],w[2])
        # Tiny roundoff cannot change the tie-breaking order.
        xy[0,0]+=1e-15
        jj,_=deterministic_neighbors(xy,0,0,3)
        self.assertEqual(ii.tolist(),jj.tolist())
    def test_real_tie_and_tree_independence(self):
        from nonstationary_measurement import deterministic_neighbors
        from unittest.mock import patch
        s=OfflineSimulator(DATA,'qc_weighted','nonstationary_qc')
        with patch.object(s.measurement,'_neighbors',side_effect=AssertionError('Tree path used')):
            s.start_run('a',200)
            s.evaluate_bias_point(12.5,56.875,'a',1)
        ii,_=deterministic_neighbors(s.data.xy,12.5,56.875,16)
        self.assertEqual(len(ii),16)

    def test_scenario_independent_of_coordinates_and_qc(self):
        s=OfflineSimulator(DATA,'qc_weighted','nonstationary_qc');s.start_run('a',200);s.start_run('b',200)
        for n in range(1,51):
            s.evaluate_bias_point(10.5,22.75,'a',n);s.evaluate_bias_point(10+(n%11)/2, (n*11)%70,'b',n)
            a=s.hidden_environment_state('a');b=s.hidden_environment_state('b')
            for k in ('disturbed','severity','burst','bias_db','extra_sigma_db','baseline_component_pct','elapsed_s'):self.assertEqual(a[k],b[k])
    def test_identical_run_replay_and_different_seed(self):
        s=OfflineSimulator(DATA,'qc_weighted','nonstationary_qc')
        for name,seed in [('a',1),('b',1),('c',2)]:s.start_run(name,seed)
        for n in range(1,30):
            a=s.evaluate_bias_point(12,30,'a',n);b=s.evaluate_bias_point(12,30,'b',n)
            self.assertEqual(a['metrics'],b['metrics']);self.assertEqual(a['quality_flags'],b['quality_flags'])
        c=s.evaluate_bias_point(12,30,'c',1);self.assertNotEqual(a['metrics'],c['metrics'])
    def test_diagnostics_and_public_boundary(self):
        s=OfflineSimulator(DATA,'qc_weighted','nonstationary_qc');s.start_run('a',216)
        for n in range(1,51):
            r=s.evaluate_bias_point(10.5,22.75,'a',n);m=r['metrics']
            passed=(abs(m['baseline']['amplitude_drift_percent'])<=10 and m['gain_fit']['r_squared_amplitude']>.6 and m['complex_fit']['r_squared_complex']>.6)
            self.assertEqual(passed,r['valid_for_comparison']);self.assertEqual(bool(r['quality_flags']),not passed)
            public=observation_for_agent(dict(evaluation=n,decision={'Ib_uA':10.5,'Phib_uA':22.75},result=r))
            for forbidden in ('bias_db','environment_state','disturbed','severity','template_index','measurement_error_db','seed'):
                self.assertNotIn(forbidden,json.dumps(public));self.assertNotIn(forbidden,json.dumps(r))
            self.assertTrue(np.isfinite(m['gain_fit']['contrast_db']))
    def test_persistence_and_severity(self):
        e=EnvironmentProcess(14);states=[e.advance() for _ in range(1000)]
        b=np.array([s['bias_db'][0] for s in states]);self.assertGreater(np.corrcoef(b[:-1],b[1:])[0,1],.8)
        self.assertGreater(sum(a['disturbed']==b['disturbed'] for a,b in zip(states,states[1:]))/999,.8)
        mild=EnvironmentProcess(20,EnvironmentSettings(profile='mild'));severe=EnvironmentProcess(20,EnvironmentSettings(profile='severe'))
        for _ in range(100):
            a=mild.advance();b=severe.advance();self.assertAlmostEqual(b['severity'],3*a['severity']);self.assertEqual(a['disturbed'],b['disturbed'])
    def test_settings_and_no_hotspot_double_counting(self):
        with self.assertRaises(ValueError):EnvironmentSettings(bias_rho=1.)
        with self.assertRaises(ValueError):OfflineSimulator(DATA,environment='nonstationary_qc',hotspot_tails=True)
    def test_public_instructions(self):
        p=make_prompt([],1,50,'dpa','nonstationary_qc');self.assertIn('conditions can change',p)
        self.assertNotIn('conditions can change',make_prompt([],1,50,'dpa','noisy_qc'))
if __name__=='__main__':unittest.main()
