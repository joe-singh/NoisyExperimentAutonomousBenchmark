> Historical development document. Start with [README.md](README.md) for the packaged release.

# Native Codex sandbox preflight fix

Fixes the Oct 2026 pilot's erroneous `codex sandbox macos` command. Current Codex CLI accepts `codex sandbox -P ... -C ... -- COMMAND`, **without** the `macos` positional argument. Adds a fail-closed check: a nonzero status from a private-file probe counts as a successful denial only if stderr indicates a permissions/sandbox denial, rather than a command-not-found or configuration failure.

Extract `native_security.py` and `test_native_blind_runner.py` into `~/Desktop/DPA-Emulator`, replacing those exact two files. Do not replace map data or the main runner.

Then run:

```bash
cd ~/Desktop/DPA-Emulator
source .venv/bin/activate
python -m unittest test_native_blind_runner -v
python native_blind_runner.py --preflight-only
```

The included unit tests do not verify macOS Seatbelt. Only the `--preflight-only` test on your actual Mac can do that. **Do not run the real agent unless all positive and negative permissions checks pass.**
