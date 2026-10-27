"""Quick offline smoke tests, run with: python test_stage_a.py"""
import unittest
import numpy as np
from landscape_model import BroadMapData, FrozenLandscape, MODEL_NAMES
from compare_landscapes import cv_predictions, summarize_cv


class StageATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = BroadMapData('level2_emulator_240_snapshot.csv')

    def test_data_and_qc(self):
        self.assertEqual(len(self.data.xy), 240)
        self.assertEqual(int(self.data.valid.sum()), 91)
        self.assertEqual(self.data.sha256,
                         'a36bf48a12e6fa18c860e9c221fb6fffd5cd479eb3a9618ddd68ad7ffc1e7bc8')

    def test_v0_reproduces_240_measurements(self):
        v0 = FrozenLandscape(self.data, 'linear_all')
        self.assertTrue(np.allclose(v0.predict_many(self.data.xy), self.data.z, atol=1e-8))
        self.assertEqual(v0.fallback_count, 0)

    def test_qc_models_bounded_and_finite(self):
        xy = np.array([(10 + 5*x/10, 70*y/10) for x in range(11) for y in range(11)])
        for name in MODEL_NAMES:
            model = FrozenLandscape(self.data, name)
            pred = model.predict_many(xy)
            self.assertEqual(pred.shape, (121, 2))
            self.assertTrue(np.isfinite(pred).all())
            self.assertTrue((pred >= 0).all())

    def test_holdout_no_leakage(self):
        rows, folds = cv_predictions(self.data)
        self.assertEqual(len(folds), 5)
        for metric in ('dpa', 'complex'):
            n = len({r['row_index'] for r in rows if r['model']=='linear_all' and r['metric']==metric})
            self.assertEqual(n, 91)
        self.assertGreater(summarize_cv(rows)['linear_all']['dpa']['mae_db'], 0)


if __name__ == '__main__':
    unittest.main()
