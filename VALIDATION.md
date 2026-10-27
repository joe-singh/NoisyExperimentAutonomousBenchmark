# Release validation — 27 October 2026

Executed on Linux, Python 3.12.14. Dependency versions are listed in
VALIDATION_ENVIRONMENT.txt. No paid model calls or hardware operations were made.

- All 44 existing unittest tests passed (none skipped).
- All Python files compile successfully.
- Native runner mock batch: two complete 50-measurement campaigns, severe
  nonstationary environment, seeds 200–201, including final nominations.
- Offline random demo: two complete 50-measurement campaigns and plot generation.
- Added blog random-baseline reproduction command: all 20 campaigns, seeds
  200–219. Final selected evaluation and QC count agree with archived results
  for every campaign; coordinates, latent scores and best visited values agree
  to absolute tolerance 1e-12. Mean 11.610618427601784 dB; bootstrap interval
  [10.489576821603457, 12.761297472315437] dB, matching published results.
- Original uncertainty-aware BO script: one complete 50-measurement campaign,
  seed 200, including GP fitting, acquisition optimization and final nomination.
  Final underlying score 16.73 dB. This verifies execution, not exact reproduction
  of the full original BO cohort across different dependency versions. The
  singleton confidence interval printed by this smoke run has no inferential use.
- Canonical 240-point scoring CSV and all original Python files remain byte-for-byte
  identical to the provided archive. See ORIGINAL_FILE_HASHES.json.
- Text scan for common credential formats, private Windows/macOS user paths and
  IPv4 addresses found no remaining matches after two Windows diagnostic paths
  were redacted in the optional 245-attempt archive. Reviewed remaining credential/
  secret references: they describe security behavior or synthetic tests. This is
  a practical release check, not a formal security audit.

## Not exercised here

macOS Seatbelt, real Codex authentication/model inference, the older Docker runner,
raw-data re-extraction (source actions archive not included), and Claude integration.
The native mock explicitly bypasses Seatbelt. Its success must not be interpreted
as verifying the OS sandbox on Linux. Run the actual preflight on your Mac.

## Packaging changes

Added current README, ignore rules, optional BO dependency file, random baseline
reproduction script, and this validation/provenance documentation. Historical docs
have a banner pointing to README. Included final supplied baseline result JSONs.
Omitted raw agent run archives, duplicate ZIPs, caches, and macOS metadata.
No simulator equations, QC rules, random streams, prompts, or scoring were changed.
