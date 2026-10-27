#!/usr/bin/env python3
"""Extract a deterministic, provenance-preserving Level-2 snapshot for replay.

Usage:
    python extract_level2_emulator.py --archive /path/to/drive-download.zip \
      --reference-table /path/to/Pasted_text_snapshot.txt --output /path/to/out

Uses only Python standard library. Does not alter the source archive.
"""
import argparse
import collections
import csv
import datetime as dt
import io
import json
import math
import statistics
import zipfile
from pathlib import Path

PREFIX = "level2_reference_map_20260927_run02"
CUTOFF_STR = "2026-09-28T21:29:44-07:00"
CUTOFF = dt.datetime.fromisoformat(CUTOFF_STR)
FIELDS = [
    "schedule_id", "population", "role", "action_id", "run_id", "session_id",
    "bias_point_number", "Ib_requested_uA", "Phib_requested_uA",
    "Ib_actual_uA", "Phib_actual_uA", "started_utc", "finished_utc",
    "outcome", "wrapper_status", "valid_for_comparison", "quality_flags",
    "errors", "DPA_dB", "DPA_CI95_lower_dB", "DPA_CI95_upper_dB",
    "DPA_CI95_status", "DPA_CI95_upper_unbounded", "DPA_CI95_intervals_json",
    "complex_dB", "complex_CI95_lower_dB", "complex_CI95_upper_dB",
    "complex_CI95_status", "complex_CI95_upper_unbounded", "complex_CI95_intervals_json",
    "Gmax", "Gmin", "complex_Gmax", "complex_Gmin",
    "amplitude_R2", "complex_R2", "amplitude_residual_RMS", "complex_residual_RMS",
    "amplitude_solver_success", "baseline_before_mVrms", "baseline_after_mVrms",
    "baseline_amplitude_drift_percent", "baseline_phase_drift_deg",
    "probe_hz", "pump_hz", "tuning_epoch", "tuning_age_at_acquisition_s",
    "raw_wrapper_json_path", "replacement_for", "snapshot_240_included",
]


def nested(obj, *path):
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def iso(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def maybe_json(x):
    return json.dumps(x, ensure_ascii=False, separators=(",", ":")) if x is not None else ""


def flatten(attempt, wrapper, path, inclusion):
    m = wrapper.get("metrics") or {}
    dpa = m.get("gain_fit") or {}
    cmp = m.get("complex_fit") or {}
    unc = m.get("contrast_uncertainty") or {}
    amp_ci = unc.get("amplitude") or {}
    cmp_ci = unc.get("complex") or {}
    baseline = m.get("baseline") or {}
    req = wrapper.get("requested_bias_uA") or {}
    actual = wrapper.get("actual_bias_uA") or {}
    tune = wrapper.get("tuning") or {}
    return {
        "schedule_id": attempt["schedule_id"],
        "population": attempt["role"],
        "role": attempt["role"],
        "action_id": int(attempt["action_id"]),
        "run_id": wrapper.get("run_id"),
        "session_id": attempt.get("session_id"),
        "bias_point_number": wrapper.get("bias_point_number"),
        "Ib_requested_uA": req.get("Ib"),
        "Phib_requested_uA": req.get("Phib"),
        "Ib_actual_uA": actual.get("Ib"),
        "Phib_actual_uA": actual.get("Phib"),
        "started_utc": wrapper.get("started_utc"),
        "finished_utc": wrapper.get("finished_utc"),
        "outcome": attempt.get("outcome"),
        "wrapper_status": wrapper.get("status"),
        "valid_for_comparison": bool(wrapper.get("valid_for_comparison")),
        "quality_flags": wrapper.get("quality_flags") or [],
        "errors": wrapper.get("errors") or [],
        "DPA_dB": dpa.get("contrast_db"),
        "DPA_CI95_lower_dB": amp_ci.get("lower_db"),
        "DPA_CI95_upper_dB": amp_ci.get("upper_db"),
        "DPA_CI95_status": amp_ci.get("status"),
        "DPA_CI95_upper_unbounded": amp_ci.get("upper_unbounded"),
        "DPA_CI95_intervals_json": maybe_json(amp_ci.get("intervals_db")),
        "complex_dB": cmp_ci.get("estimate_db"),
        "complex_CI95_lower_dB": cmp_ci.get("lower_db"),
        "complex_CI95_upper_dB": cmp_ci.get("upper_db"),
        "complex_CI95_status": cmp_ci.get("status"),
        "complex_CI95_upper_unbounded": cmp_ci.get("upper_unbounded"),
        "complex_CI95_intervals_json": maybe_json(cmp_ci.get("intervals_db")),
        "Gmax": dpa.get("gmax"),
        "Gmin": dpa.get("gmin"),
        "complex_Gmax": cmp.get("implied_gmax"),
        "complex_Gmin": cmp.get("implied_gmin"),
        "amplitude_R2": dpa.get("r_squared_amplitude"),
        "complex_R2": cmp.get("r_squared_complex"),
        "amplitude_residual_RMS": dpa.get("amplitude_residual_rms"),
        "complex_residual_RMS": cmp.get("complex_residual_rms"),
        "amplitude_solver_success": dpa.get("solver_success"),
        "baseline_before_mVrms": baseline.get("baseline_before_mvrms"),
        "baseline_after_mVrms": baseline.get("baseline_after_mvrms"),
        "baseline_amplitude_drift_percent": baseline.get("baseline_amplitude_change_percent"),
        "baseline_phase_drift_deg": baseline.get("baseline_phase_change_deg"),
        "probe_hz": tune.get("probe_hz"),
        "pump_hz": tune.get("pump_hz"),
        "tuning_epoch": tune.get("epoch"),
        "tuning_age_at_acquisition_s": tune.get("age_at_acquisition_s"),
        "raw_wrapper_json_path": path,
        "replacement_for": attempt.get("replacement_for") or None,
        "snapshot_240_included": inclusion,
    }


def row_for_csv(row):
    out = {}
    for k in FIELDS:
        v = row[k]
        if k in ("quality_flags", "errors"):
            out[k] = maybe_json(v)
        elif isinstance(v, bool):
            out[k] = "true" if v else "false"
        else:
            out[k] = v
    return out


def write_csv(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row_for_csv(row))


def finite_or_none(obj):
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {k: finite_or_none(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [finite_or_none(x) for x in obj]
    return obj


def fit_ci(rows, key):
    statuses = collections.Counter(row[f"{key}_CI95_status"] for row in rows)
    n_missing = sum(row[f"{key}_CI95_lower_dB"] is None for row in rows)
    n_unbounded = sum(row[f"{key}_CI95_upper_unbounded"] is True for row in rows)
    widths = [row[f"{key}_CI95_upper_dB"]-row[f"{key}_CI95_lower_dB"]
              for row in rows if row[f"{key}_CI95_upper_dB"] is not None
              and row[f"{key}_CI95_lower_dB"] is not None]
    return statuses, n_missing, n_unbounded, widths


def audit_md(snapshot, all_archive, extra, attempted, map_test, source_archive):
    n = len(snapshot)
    valid = [r for r in snapshot if r["valid_for_comparison"]]
    bad = [r for r in snapshot if not r["valid_for_comparison"]]
    flags = collections.Counter(flag for r in snapshot for flag in r["quality_flags"])
    role_stats = {role: (sum(r["role"] == role for r in snapshot),
                         sum(r["role"] == role and r["valid_for_comparison"] for r in snapshot))
                  for role in ("grid", "cell_centres")}
    lines = [
        "# Level-2 reference map: emulator-data audit", "",
        f"Source archive: `{source_archive}`", "",
        f"Snapshot timestamp (local): `{CUTOFF_STR}`", "",
        "## Extraction counts", "",
        f"- Scheduled grid/cell-centre points in the **archive**: **{len(all_archive)}** unique positions.",
        f"- Scheduled grid/cell-centre points in the **frozen map snapshot**: **{n}** positions.",
        f"- Additional positions completed after the frozen snapshot: **{len(extra)}**.",
        f"- Physical grid/cell-centre attempts in the archive (including replaced operational failures): **{len(attempted)}**.",
        f"- Frozen-snapshot measurements passing canonical QC: **{len(valid)} ({len(valid)/n:.1%})**.",
        f"- Frozen-snapshot measurements not passing canonical QC: **{len(bad)} ({len(bad)/n:.1%})**.",
        f"- Original 240-point heatmap table reconciliation: **{map_test}**.",
        "",
        "| Population | Selected positions | QC passing | QC failing |",
        "|---|---:|---:|---:|",
    ]
    for k, (tot, good) in role_stats.items():
        lines.append(f"| {k} | {tot} | {good} | {tot-good} |")
    lines += ["", "## Field availability and confidence intervals", "",
              "Null CSV cells / JSON null indicate missing or unbounded quantities; they are not zero.", "",
              "| Field | Present / 240 | QC passing subset present / 91 |",
              "|---|---:|---:|"]
    fields = ["Ib_actual_uA", "Phib_actual_uA", "DPA_dB", "complex_dB", "Gmax", "Gmin", "complex_Gmax", "complex_Gmin", "amplitude_R2", "complex_R2", "amplitude_residual_RMS", "complex_residual_RMS", "DPA_CI95_lower_dB", "DPA_CI95_upper_dB", "complex_CI95_lower_dB", "complex_CI95_upper_dB", "baseline_amplitude_drift_percent", "baseline_phase_drift_deg", "tuning_age_at_acquisition_s", "probe_hz", "pump_hz"]
    for k in fields:
        lines.append(f"| {k} | {sum(r[k] is not None for r in snapshot)} | {sum(r[k] is not None for r in valid)} |")
    lines.extend(["", "### CI status", "",
                  "The intervals are *approximate profile-fit 95% confidence sets*, not calibration/systematic error bars and not directly usable as independent per-query Gaussian noise standard deviations.", "",
                  "| Metric | Bounded | Upper-unbounded | Lower missing | Median bounded interval width (dB) |",
                  "|---|---:|---:|---:|---:|"])
    for metric in ["DPA", "complex"]:
        stat, lower_missing, n_unbound, widths = fit_ci(snapshot, metric)
        lines.append(f"| {metric} | {stat['bounded']} | {n_unbound} | {lower_missing} | {statistics.median(widths):.3f} |")
    lines.extend(["", "### QC failure reasons (non-exclusive)", ""])
    for flag, count in flags.most_common():
        lines.append(f"- {count}: {flag}")
    if not flags:
        lines.append("- None")
    lines.extend(["", "## Recommendations for using these files", "",
                  "1. **Reproducibility baseline:** use the 240-point snapshot CSV to recreate the original heatmap. The original map used all fitted contrasts, including QC-invalid points. This visual baseline is not equivalent to a validated ground-truth physical landscape.",
                  "2. **Replay benchmark:** use the snapshot for historical anchoring, but do not treat QC-invalid contrast estimates as accurate truth. Model validity and missingness explicitly; compare against a QC-passing-only interpolation and alternative reconstructions as sensitivity checks.",
                  "3. **No spurious precision:** do not convert profile confidence interval half-width to Gaussian standard deviation without a defensible model, and do not assume pointwise errors are independent. The CI method fixes normalized baselines and omits slow drift/systematics.",
                  "4. **Bias-space weights:** account for nonuniform original sampling; evaluating percentiles over a dense uniform interpolation grid weights by physical bias-space area, not by raw measured point count.",
                  "5. **Avoid leakage:** do not use the 68 agent-targeted local-patch points as the *primary* replay surface. They can be used for sensitivity analysis or physical validation, with selection bias clearly stated.",
                  "6. **Temporal realism:** the file records timestamps and drift proxies, but a collection of one-shot bias measurements cannot identify a fully realistic stochastic noise/drift simulator. For claims about noisy-loop robustness, calibrate multiple plausible noise/dropout models and report sensitivity.",
                  "7. **Exact experiment replication:** keep the original zip. Its `actions/######/wrapper_result.json` files retain the full original schema; the extracted JSON intentionally keeps only the agent-relevant observation fields.",
                  "", "## File definitions", "",
                  "- `level2_emulator_240_snapshot.csv`: exactly the 240 scheduled broad-grid/midpoint points at the historical snapshot, flattened columns.",
                  "- `level2_emulator_91_qc_passing.csv`: the 91 QC-accepted rows from the historical 240-point snapshot, for a stricter sensitivity analysis.",
                  "- `level2_emulator_240_snapshot.json`: same 240 points in a typed, structured native JSON envelope, preserving nested original `metrics` and QC/timing fields useful for a wrapper emulator.",
                  "- `level2_emulator_243_archive.csv`: all 243 unique broad-sweep positions contained in this later archive; three rows are marked `snapshot_240_included=false`.",
                  "- `level2_emulator_attempts_245.csv`: all 245 original grid/midpoint attempts, including two superseded operational failures, so a future dropout model need not erase failure histories.",
                  "- `extract_level2_emulator.py`: reproducible extraction script, with source-location pointers and cross-check against the 240-point text snapshot.",
                  "", "## Additional archive measurements", ""])
    for r in extra:
        lines.append(f"- action {r['action_id']}, ({r['Ib_requested_uA']:.6f}, {r['Phib_requested_uA']:.6f}) µA, finished {r['finished_utc']}")
    return "\n".join(lines) + "\n"


def parse_snapshot_reference(path):
    if not path:
        return None
    text = Path(path).read_text(encoding="utf-8")
    text = text.split("## Local scan")[0]
    rows = []
    for line in text.splitlines():
        parts = [s.strip() for s in line.strip().strip("|").split("|")]
        if len(parts) != 4:
            continue
        try:
            rows.append(tuple(float(x) for x in parts))
        except ValueError:
            pass
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default="/mnt/data/drive-download-20260930T002024Z-1-001.zip")
    ap.add_argument("--reference-table", default="/mnt/data/Pasted text(20260929-043027).txt")
    ap.add_argument("--output", default="/mnt/data/level2_emulator")
    args = ap.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.archive) as z:
        all_attempts = list(csv.DictReader(io.StringIO(z.read(PREFIX + "/reports/all_attempts.csv").decode("utf-8-sig"))))
        candidates = []
        for r in all_attempts:
            if r["role"] not in ("grid", "cell_centres"):
                continue  # deliberately exclude readiness and periodic controls
            action_id = int(r["action_id"])
            path = f"{PREFIX}/actions/{action_id:06d}/wrapper_result.json"
            raw = json.loads(z.read(path))
            candidates.append((r, raw, path))
        # The two operational failures were explicitly superseded. Keep those
        # in attempts file, but use the final replacement result for each cell.
        by_id = collections.defaultdict(list)
        for r, w, path in candidates:
            by_id[r["schedule_id"]].append((r, w, path))
        selected = [max(items, key=lambda x: int(x[0]["action_id"])) for items in by_id.values()]
        selected.sort(key=lambda item: (iso(item[1]["finished_utc"]), int(item[0]["action_id"])))
        all_flat = [flatten(r, w, path, iso(w["finished_utc"]) <= CUTOFF) for r, w, path in selected]
        snap = [r for r in all_flat if r["snapshot_240_included"]]
        extra = [r for r in all_flat if not r["snapshot_240_included"]]
        attempt_flat = [flatten(r, w, path, iso(w["finished_utc"]) <= CUTOFF) for r,w,path in candidates]
        attempt_flat.sort(key=lambda r:r["action_id"])
        assert len(snap) == 240, f"Unexpected historical snapshot length: {len(snap)}"
        assert len(all_flat) == 243 and len(attempt_flat) == 245
        assert len({r["schedule_id"] for r in snap}) == 240
        assert all(r["DPA_dB"] is not None and r["complex_dB"] is not None for r in snap)
        assert sum(r["valid_for_comparison"] for r in snap) == 91
        original = parse_snapshot_reference(args.reference_table)
        if original is not None:
            assert len(original) == 240
            mapping = {(round(r["Ib_requested_uA"], 6), round(r["Phib_requested_uA"], 6)):r for r in snap}
            for ib, phi, dpa, cmp in original:
                key = (round(ib, 6), round(phi, 6))
                assert key in mapping, key
                row = mapping[key]
                assert abs(row["DPA_dB"] - dpa) <= 0.001, (key, "dpa")
                assert abs(row["complex_dB"] - cmp) <= 0.001, (key, "complex")
            match = "all 240 coordinates and both three-decimal contrast columns matched"
        else:
            match = "not checked against reference table"
        write_csv(out / "level2_emulator_240_snapshot.csv", snap)
        write_csv(out / "level2_emulator_91_qc_passing.csv", [r for r in snap if r["valid_for_comparison"]])
        write_csv(out / "level2_emulator_243_archive.csv", all_flat)
        write_csv(out / "level2_emulator_attempts_245.csv", attempt_flat)
        data = []
        selected_by_id = {int(r["action_id"]):(r,w,path) for r,w,path in selected}
        for flat in snap:
            r,w,path = selected_by_id[flat["action_id"]]
            observation = {
                "schema_version": w.get("schema_version"),
                "procedure_version": w.get("procedure_version"),
                "run_id": w.get("run_id"),
                "bias_point_number": w.get("bias_point_number"),
                "requested_bias_uA": w.get("requested_bias_uA"),
                "actual_bias_uA": w.get("actual_bias_uA"),
                "status": w.get("status"),
                "valid_for_comparison": w.get("valid_for_comparison"),
                "quality_flags": w.get("quality_flags"),
                "errors": w.get("errors"),
                "started_utc": w.get("started_utc"),
                "finished_utc": w.get("finished_utc"),
                "metrics": w.get("metrics"),
                "tuning": {
                    key: (w.get("tuning") or {}).get(key)
                    for key in ("epoch", "probe_hz", "pump_hz", "age_at_acquisition_s")
                },
            }
            data.append({
                "schedule_id": flat["schedule_id"],
                "population": flat["population"],
                "action_id": flat["action_id"],
                "raw_wrapper_json_path": path,
                "flat": flat,
                "wrapper_observation": observation,
            })
        envelope = {
            "dataset": "level2_reference_map_240_snapshot",
            "snapshot_at": CUTOFF_STR,
            "source_archive": Path(args.archive).name,
            "source_selection": "Last non-superseded action per grid/cell-centre schedule_id, finished by snapshot; exclude readiness and periodic controls",
            "coordinate_units": "microamperes",
            "contrast_units": "decibels",
            "records": data,
        }
        (out / "level2_emulator_240_snapshot.json").write_text(
            json.dumps(finite_or_none(envelope), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        audit = audit_md(snap, all_flat, extra, attempt_flat, match, Path(args.archive).name)
        (out / "level2_emulator_data_audit.md").write_text(audit, encoding="utf-8")
        print(audit[:11000])
        print("\nFILES:")
        for file in out.iterdir():
            print(file, file.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
