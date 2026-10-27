import argparse
import json
from importlib.metadata import version
from pathlib import Path

import numpy as np
import torch
from scipy.stats import qmc

from botorch.acquisition.logei import qLogNoisyExpectedImprovement
from botorch.fit import fit_gpytorch_mll
from botorch.models import SingleTaskGP
from botorch.optim import optimize_acqf
from botorch.sampling.normal import SobolQMCNormalSampler

from gpytorch.kernels import MaternKernel, ScaleKernel
from gpytorch.likelihoods import FixedNoiseGaussianLikelihood
from gpytorch.mlls import ExactMarginalLogLikelihood

from offline_simulator import OfflineSimulator


# ── Fixed experiment settings ─────────────────────────────────────────

BUDGET = 50
INITIAL_POINTS = 10
MIN_VALID_POINTS = 4

LOWER = np.array([10.0, 0.0])
WIDTH = np.array([5.0, 70.0])

torch.set_default_dtype(torch.float64)
torch.set_num_threads(1)

UNIT_BOUNDS = torch.tensor([
    [0.0, 0.0],
    [1.0, 1.0],
])


def reported_variance(observation):
    """Recover noise variance using only the public contrast interval."""
    interval = observation["metrics"]["contrast_uncertainty"]["amplitude"]

    estimate = float(interval["estimate_db"])
    upper = float(interval["upper_db"])

    if interval.get("upper_unbounded", False):
        raise ValueError("Cannot use an unbounded contrast interval.")

    # Emulator intervals are estimate ± 1.96 sigma, with the lower
    # endpoint clipped at zero. The upper half remains informative.
    sigma = (upper - estimate) / 1.96

    if not np.isfinite(sigma) or sigma <= 0:
        raise ValueError(f"Invalid reported uncertainty: {interval}")

    return sigma ** 2


def fit_model(points, observations):
    """Fit only QC-valid observations, including their uncertainties."""
    valid = [
        i for i, observation in enumerate(observations)
        if observation["valid_for_comparison"]
    ]

    x = torch.tensor(np.array([points[i] for i in valid]))

    y = torch.tensor([
        observations[i]["metrics"]["gain_fit"]["contrast_db"]
        for i in valid
    ]).unsqueeze(-1)

    measurement_variance = torch.tensor([
        reported_variance(observations[i])
        for i in valid
    ]).unsqueeze(-1)

    # Standardise values AND variances consistently.
    # The GP posterior is consequently in standardised units, which
    # preserves acquisition and final-nomination rankings.
    y_mean = y.mean()
    y_scale = y.std()

    if y_scale.item() < 1e-8:
        y_scale = torch.ones_like(y_scale)

    standard_y = (y - y_mean) / y_scale
    standard_variance = measurement_variance / y_scale.square()

    likelihood = FixedNoiseGaussianLikelihood(
        noise=standard_variance.squeeze(-1),
        learn_additional_noise=True,
    )

    kernel = ScaleKernel(
        MaternKernel(nu=2.5, ard_num_dims=2)
    )

    model = SingleTaskGP(
        train_X=x,
        train_Y=standard_y,
        train_Yvar=standard_variance,
        likelihood=likelihood,
        covar_module=kernel,
        outcome_transform=None,
    )

    mll = ExactMarginalLogLikelihood(model.likelihood, model)
    fit_gpytorch_mll(mll)
    model.eval()

    diagnostics = {
        "output_mean_db": float(y_mean.item()),
        "output_scale_db": float(y_scale.item()),
        "extra_noise_variance_db2": float(
            model.likelihood.second_noise.detach().item()
            * y_scale.square().item()
        ),
        "length_scales_normalised": (
            model.covar_module.base_kernel.lengthscale
            .detach().cpu().reshape(-1).tolist()
        ),
    }

    return model, x, diagnostics


def run_campaign(sim, seed):
    optimiser_seed = seed + 100_000
    torch.manual_seed(optimiser_seed)

    fallback_rng = np.random.default_rng(optimiser_seed)

    initial_design = qmc.LatinHypercube(
        d=2,
        seed=optimiser_seed,
    ).random(INITIAL_POINTS)

    run_id = f"bo_uncertainty_{seed}"
    sim.start_run(run_id, seed)

    points = []
    observations = []

    for step in range(BUDGET):
        n_valid = sum(
            observation["valid_for_comparison"]
            for observation in observations
        )

        if step < INITIAL_POINTS:
            point = initial_design[step]

        elif n_valid < MIN_VALID_POINTS:
            point = fallback_rng.random(2)

        else:
            model, train_x, _ = fit_model(points, observations)

            sampler = SobolQMCNormalSampler(
                sample_shape=torch.Size([256]),
                seed=optimiser_seed + step,
            )

            acquisition = qLogNoisyExpectedImprovement(
                model=model,
                X_baseline=train_x,
                sampler=sampler,
                prune_baseline=True,
            )

            candidate, _ = optimize_acqf(
                acq_function=acquisition,
                bounds=UNIT_BOUNDS,
                q=1,
                num_restarts=10,
                raw_samples=256,
                options={
                    "batch_limit": 5,
                    "maxiter": 200,
                },
            )

            point = candidate.detach().cpu().numpy()[0]
            point = np.clip(point, 0.0, 1.0)

        physical_point = LOWER + WIDTH * point

        observation = sim.evaluate_bias_point(
            float(physical_point[0]),
            float(physical_point[1]),
            run_id,
            step + 1,
        )

        points.append(point)
        observations.append(observation)

        print(
            f"Seed {seed}, {step + 1:02d}/{BUDGET}: "
            f"DPA={observation['metrics']['gain_fit']['contrast_db']:.2f}, "
            f"QC={observation['valid_for_comparison']}",
            flush=True,
        )

    valid = [
        i for i, observation in enumerate(observations)
        if observation["valid_for_comparison"]
    ]

    final_model_diagnostics = None

    if len(valid) >= MIN_VALID_POINTS:
        model, _, final_model_diagnostics = fit_model(
            points, observations
        )

        # Rank every previously visited location using the inferred
        # underlying function, not a new noisy observation.
        with torch.no_grad():
            predictions = model.posterior(
                torch.tensor(np.array(points)),
                observation_noise=False,
            ).mean.squeeze(-1)

        selected = int(predictions.argmax().item())
        nomination_rule = "highest posterior mean among visited locations"

    elif valid:
        selected = max(
            valid,
            key=lambda i: observations[i]["metrics"]["gain_fit"]["contrast_db"],
        )
        nomination_rule = "few-valid fallback: highest valid observation"

    else:
        selected = 0
        nomination_rule = "no-valid fallback: first location"

    # Hidden scores are accessed only AFTER nomination.
    physical_points = LOWER + WIDTH * np.array(points)

    latent = [
        float(sim.latent_at(*point)[0])
        for point in physical_points
    ]

    return {
        "model": "Bayesian optimisation",
        "effort": "none",
        "baseline_version": "uncertainty_v2",
        "seed": seed,
        "selected_evaluation": selected + 1,
        "nomination_rule": nomination_rule,
        "final_db": latent[selected],
        "best_db": max(latent),
        "qc_passes": len(valid),
        "points": physical_points.tolist(),
        "latent": latent,
        "observations": observations,
        "final_model_diagnostics": final_model_diagnostics,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=200)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("bo_results_uncertainty"),
    )
    args = parser.parse_args()

    if args.repeats < 1:
        parser.error("--repeats must be at least 1")

    args.out.mkdir(parents=True, exist_ok=True)

    data_path = (
        Path(__file__).resolve().parent
        / "level2_emulator_240_snapshot.csv"
    )

    sim = OfflineSimulator(
        data_path,
        landscape="qc_weighted",
        environment="nonstationary_qc",
        disturbance_profile="severe",
    )

    settings = {
        "baseline_version": "uncertainty_v2",
        "budget": BUDGET,
        "initial_points": INITIAL_POINTS,
        "initial_design": "Latin hypercube",
        "minimum_valid_for_gp": MIN_VALID_POINTS,
        "kernel": "scaled Matern-5/2, ARD",
        "inputs": "normalised to [0,1]^2",
        "outputs": "standardised within campaign",
        "noise": (
            "per-observation reported variance plus fitted "
            "shared additional Gaussian variance"
        ),
        "reported_sigma": "(upper_db - estimate_db) / 1.96",
        "acquisition": "qLogNoisyExpectedImprovement, q=1",
        "mc_samples": 256,
        "acquisition_restarts": 10,
        "acquisition_raw_samples": 256,
        "nomination": "highest posterior mean among visited locations",
        "temporal_drift_modelled": False,
        "fit_intervals_used": True,
        "complex_contrast_used": False,
        "versions": {
            name: version(name)
            for name in [
                "botorch", "gpytorch", "torch", "numpy", "scipy"
            ]
        },
        "environment_provenance": sim.provenance(),
    }

    settings_path = args.out / "settings.json"

    if settings_path.exists():
        if json.loads(settings_path.read_text()) != settings:
            raise RuntimeError(
                "Settings or software versions changed. "
                "Use a new --out folder."
            )
    else:
        if list(args.out.glob("seed_*.json")):
            raise RuntimeError(
                "Campaign files exist without settings.json. "
                "Use a new --out folder."
            )

        settings_path.write_text(json.dumps(settings, indent=2))

    campaigns = []

    for seed in range(args.seed, args.seed + args.repeats):
        campaign_path = args.out / f"seed_{seed}.json"

        if campaign_path.exists():
            campaign = json.loads(campaign_path.read_text())

            if (
                campaign.get("seed") != seed
                or campaign.get("baseline_version") != "uncertainty_v2"
                or len(campaign.get("observations", [])) != BUDGET
            ):
                raise RuntimeError(
                    f"Incompatible or incomplete file: {campaign_path}"
                )

            print(f"Loading completed seed {seed}", flush=True)

        else:
            campaign = run_campaign(sim, seed)

            temporary_path = campaign_path.with_suffix(".tmp")
            temporary_path.write_text(json.dumps(campaign, indent=2))
            temporary_path.replace(campaign_path)

        campaigns.append(campaign)

    scores = np.array([
        campaign["final_db"] for campaign in campaigns
    ])

    indices = np.random.default_rng(20261018).integers(
        0,
        len(scores),
        size=(10000, len(scores)),
    )

    ci = np.percentile(
        scores[indices].mean(axis=1),
        [2.5, 97.5],
    )

    result = {
        "settings": settings,
        "summary": {
            "mean": float(scores.mean()),
            "ci": ci.tolist(),
            "best_visited_mean": float(np.mean([
                campaign["best_db"] for campaign in campaigns
            ])),
        },
        "campaigns": campaigns,
    }

    output = args.out / "bo_baseline.json"
    output.write_text(json.dumps(result, indent=2))

    print(f"\nCompleted campaigns: {len(campaigns)}")
    print(f"Mean final contrast: {scores.mean():.2f} dB")
    print(f"95% bootstrap CI: [{ci[0]:.2f}, {ci[1]:.2f}] dB")
    print(f"Saved: {output.resolve()}")


if __name__ == "__main__":
    main()