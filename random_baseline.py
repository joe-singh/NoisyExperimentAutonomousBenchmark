"""Reproduce the blog's uniform random-search baseline without an AI account."""
import argparse
import json
from pathlib import Path

import numpy as np

from offline_simulator import OfflineSimulator


def run_campaign(sim, seed):
    rng = np.random.default_rng(np.random.SeedSequence([seed, 72941]))
    points = rng.uniform([10.0, 0.0], [15.0, 70.0], size=(50, 2))
    run_id = f"random_{seed}"
    sim.start_run(run_id, seed)
    observations = [
        sim.evaluate_bias_point(float(ib), float(phi), run_id, i + 1)
        for i, (ib, phi) in enumerate(points)
    ]
    valid = [i for i, obs in enumerate(observations) if obs['valid_for_comparison']]
    selected = max(valid, key=lambda i: observations[i]['metrics']['gain_fit']['contrast_db']) if valid else 0
    # The controller scores only after the policy has nominated a point.
    latent = [float(sim.latent_at(*point)[0]) for point in points]
    return dict(seed=seed, selected_evaluation=selected + 1,
                final_db=latent[selected], best_db=max(latent),
                qc_passes=len(valid), points=points.tolist(),
                latent=latent, observations=observations)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=200)
    parser.add_argument('--repeats', type=int, default=20)
    parser.add_argument('--out', type=Path, default=Path('random_results'))
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    sim = OfflineSimulator(Path(__file__).with_name('level2_emulator_240_snapshot.csv'),
                           'qc_weighted', 'nonstationary_qc', disturbance_profile='severe')
    campaigns = [run_campaign(sim, seed) for seed in range(args.seed, args.seed + args.repeats)]
    scores = np.array([run['final_db'] for run in campaigns])
    rng = np.random.default_rng(20261018)
    means = scores[rng.integers(0, len(scores), size=(10000, len(scores)))].mean(axis=1)
    result = dict(policy=__doc__, provenance=sim.provenance(), campaigns=campaigns,
                  summary=dict(n=len(scores), final_db=float(scores.mean()),
                               final_db_ci=np.quantile(means, [.025, .975]).tolist()))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'random_search_baseline.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result['summary'], indent=2))


if __name__ == '__main__':
    main()
