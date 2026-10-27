> Historical development document. Start with [README.md](README.md) for the packaged release.

# Codex native sandbox: inline TOML permission fix

This patch addresses a Codex CLI `FilesystemPermissionToml` parsing error by replacing multiple nested filesystem `-c` overrides with a single inline-table override. It does not weaken the intended restrictions.

## Install

Unzip the two `.py` files directly into `~/Desktop/DPA-Emulator/`, replacing only `native_security.py` and `test_native_blind_runner.py`. It does not touch datasets, the simulator or Codex credentials.

## Test

```bash
python -m unittest test_native_blind_runner -v
python native_blind_runner.py --preflight-only
```

**Do not launch a scored experiment unless the real macOS preflight reports an allowed workspace read and actual OS-level permission denials for each private-path probe.** Passing Python unit tests by itself does not prove sandbox enforcement.

Caveat: This patch has been checked with Python's TOML parser, not your locally installed Codex CLI 0.162.1; the macOS preflight is the authoritative test.
