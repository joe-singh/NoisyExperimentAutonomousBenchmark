import unittest
from pathlib import Path
import tempfile

from offline_simulator import OfflineSimulator
from run_offline import run_one


DATA = Path(__file__).with_name('level2_emulator_240_snapshot.csv')


@unittest.skipUnless(DATA.exists(), 'Place existing 240 snapshot CSV next to the starter files')
class TestOfflineSimulator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = OfflineSimulator(DATA)

    def test_exact_recovery_of_observed_values(self):
        self.assertEqual(len(self.sim.lookup), 240)
        self.assertEqual(self.sim.n_qc_valid, 91)
        for coords, expected in self.sim.lookup.items():
            self.assertEqual(self.sim.predict(*coords), expected)

    def test_both_reference_distributions_and_complex_recovery(self):
        self.assertEqual(len(self.sim.reference_distribution(20, 40, 'dpa')),800)
        self.assertEqual(len(self.sim.reference_distribution(20, 40, 'complex')),800)
        with self.assertRaises(ValueError):
            self.sim.reference_distribution(20,40,'invalid')

    def test_bounds_and_call_order(self):
        sim = OfflineSimulator(DATA)
        with self.assertRaises(ValueError):
            sim.evaluate_bias_point(16, 0, 'test', 1)
        r = sim.evaluate_bias_point(11, 20, 'test', 1)
        self.assertEqual(r['bias_point_number'],1)
        self.assertEqual(r['status'],'completed')
        with self.assertRaises(ValueError):
            sim.evaluate_bias_point(11, 20, 'test', 1)

    def test_deterministic_full_run(self):
        sim = OfflineSimulator(DATA)
        dist = sim.reference_distribution(50, 100)
        with tempfile.TemporaryDirectory() as d:
            s1 = run_one(sim, 'adaptive', 42, 10, Path(d)/'r1', dist, False)
            s2 = run_one(sim, 'adaptive', 42, 10, Path(d)/'r2', dist, False)
            self.assertEqual(s1['best_dpa_db'], s2['best_dpa_db'])
            self.assertEqual(s1['top_10pct_queries'], s2['top_10pct_queries'])
            self.assertEqual(len((Path(d)/'r1'/'evaluations.jsonl').read_text().splitlines()),10)

    def test_complex_adaptive_deterministic_and_distinct(self):
        sim = OfflineSimulator(DATA)
        dpa_dist = sim.reference_distribution(50, 100, 'dpa')
        complex_dist = sim.reference_distribution(50, 100, 'complex')
        with tempfile.TemporaryDirectory() as d:
            c1 = run_one(sim, 'adaptive', 42, 50, Path(d)/'c1', complex_dist, False, 'complex', dpa_dist)
            c2 = run_one(sim, 'adaptive', 42, 50, Path(d)/'c2', complex_dist, False, 'complex', dpa_dist)
            d1 = run_one(sim, 'adaptive', 42, 50, Path(d)/'d1', dpa_dist, False, 'dpa', complex_dist)
            self.assertEqual(c1['best_complex_db'], c2['best_complex_db'])
            self.assertEqual(c1['best_complex_map_percentile'], c2['best_complex_map_percentile'])
            self.assertIn('top_10pct_dpa_queries', c1)
            self.assertIn('top_10pct_complex_queries', c1)
            self.assertIn('complex_map_percentile', (Path(d)/'c1'/'trajectory.csv').read_text())
            self.assertNotEqual((Path(d)/'c1'/'trajectory.csv').read_text(),
                                (Path(d)/'d1'/'trajectory.csv').read_text())

if __name__ == '__main__':
    unittest.main()
