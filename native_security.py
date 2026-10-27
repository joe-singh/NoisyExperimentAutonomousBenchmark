"""Fail-closed macOS Codex Seatbelt permission-profile checks.

No model inference is required for these checks. They exercise the same
profile through `codex sandbox` which runs local commands under Seatbelt.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tomllib

# Passed to every Codex invocation. Explicit --sandbox must never be combined.
PROFILE_NAME = 'squid_blind'
# Use ONE inline TOML filesystem value. Codex CLI 0.162.1 can reject the
# equivalent nested-table overrides with FilesystemPermissionToml parse errors.
# The profile has no broad filesystem grants; only essential runtime paths and
# the explicitly selected agent workspace should be readable/writable.
FILESYSTEM_INLINE = (
    'permissions.squid_blind.filesystem='
    '{":root"="deny", ":minimal"="read", '
    '":tmpdir"="deny", ":slash_tmp"="deny", '
    '":workspace_roots"={"."="write"}}'
)
PROFILE_OVERRIDES = [
    '-c', 'default_permissions="squid_blind"',
    '-c', FILESYSTEM_INLINE,
    '-c', 'permissions.squid_blind.network.enabled=false',
]


def assert_legacy_config_absent():
    """Avoid the documented silent fallback to legacy sandbox_mode.

    Project configs in agent workspace are prohibited separately by controller.
    This is a conservative user-level check, not a substitute for probes.
    """
    config = Path.home() / '.codex' / 'config.toml'
    if not config.exists():
        return
    try:
        data = tomllib.loads(config.read_text(encoding='utf-8'))
    except Exception as exc:
        raise RuntimeError(f'Cannot inspect Codex config {config}: {exc}') from exc
    if 'sandbox_mode' in data or 'sandbox_workspace_write' in data:
        raise RuntimeError(
            f'{config} contains legacy sandbox_mode/sandbox_workspace_write; '
            'permission profiles would be ignored. Remove the conflicting setting '
            'after backing up the file, then rerun security preflight.'
        )
    active_mcp = [name for name, spec in data.get('mcp_servers', {}).items()
                  if isinstance(spec, dict) and spec.get('enabled', True)]
    if active_mcp:
        raise RuntimeError(
            f'Codex user config has enabled MCP servers: {active_mcp}. '
            'These are not subject to the local Seatbelt profile. Disable them '
            'for the benchmark before proceeding.'
        )
    if data.get('hooks'):
        raise RuntimeError('Global Codex hooks are configured; disable them for this blind pilot.')
    for name, profile in data.get('profiles', {}).items():
        if isinstance(profile, dict) and ('sandbox_mode' in profile or 'sandbox_workspace_write' in profile):
            raise RuntimeError(f'Legacy sandbox setting found under profile {name} in {config}.')


def sandbox_cmd(workspace: Path, argv: list[str]) -> list[str]:
    return [
        'codex', 'sandbox',
        '--permission-profile', PROFILE_NAME,
        '--cd', str(workspace),
        *PROFILE_OVERRIDES,
        '--', *argv,
    ]


def is_permission_denial(stderr: str) -> bool:
    """Avoid confusing command/configuration failures with an actual OS permission denial."""
    msg = stderr.lower()
    return any(token in msg for token in ('operation not permitted', 'permission denied', 'sandbox deny', 'sandbox violation'))


def run_security_preflight(workspace: Path, private_csv: Path, *, verbose=True) -> dict:
    if sys.platform != 'darwin':
        raise RuntimeError('Native Codex security preflight must run on macOS.')
    assert_legacy_config_absent()
    workspace = workspace.expanduser().resolve()
    private_csv = private_csv.expanduser().resolve()
    if not private_csv.is_file():
        raise FileNotFoundError(f'Hidden map file not found: {private_csv}')
    if workspace == private_csv.parent or workspace in private_csv.parents or private_csv in workspace.parents:
        raise RuntimeError('Unsafe layout: private data and agent workspace overlap.')
    workspace.mkdir(parents=True, exist_ok=True)
    if any((workspace / n).exists() for n in ('.codex', 'AGENTS.md', 'AGENTS.override.md')):
        raise RuntimeError('Agent workspace must not have .codex or AGENTS.md; use a fresh directory.')

    marker = workspace / 'sandbox_visible_probe.txt'
    marker.write_text('SQUID_AGENT_ALLOWED_READ_93041\n', encoding='utf-8')

    checks = [
        ('workspace_read', marker, True),
        ('hidden_map_denied', private_csv, False),
        ('auth_denied', Path.home()/'.codex'/'auth.json', False),
    ]
    results = {}
    for label, path, should_read in checks:
        if label == 'auth_denied' and not path.exists():
            raise RuntimeError('Expected ~/.codex/auth.json missing; Codex login required.')
        proc = subprocess.run(
            sandbox_cmd(workspace, ['/bin/cat', str(path)]),
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        success = proc.returncode == 0
        if should_read and (not success or 'SQUID_AGENT_ALLOWED_READ_93041' not in proc.stdout):
            raise RuntimeError(f'Sandbox failed positive workspace test: {label}: {proc.stderr[-700:]}')
        if not should_read and success:
            raise RuntimeError(f'SECURITY FAILURE: sandbox could read {label}: {path}. STOP; no model runs.')
        if not should_read and not is_permission_denial(proc.stderr):
            raise RuntimeError(f'Sandbox probe inconclusive for {label}; expected a permission denial, got: {proc.stderr[-700:]}')
        results[label] = 'read allowed' if should_read else 'read denied'
        if verbose:
            print(f'{label}: {results[label]}')

    # Check sensitive directory enumeration, independent of file contents.
    proc = subprocess.run(sandbox_cmd(workspace, ['/bin/ls', str(private_csv.parent)]),
                          cwd=workspace, capture_output=True, text=True, timeout=45)
    if proc.returncode == 0:
        raise RuntimeError('SECURITY FAILURE: sandbox could list private emulator directory.')
    if not is_permission_denial(proc.stderr):
        raise RuntimeError(f'Sandbox directory probe inconclusive; expected permission denial, got: {proc.stderr[-700:]}')
    results['private_directory_denied'] = 'listing denied'
    if verbose:
        print('private_directory_denied: listing denied')
        print('PASS: native Codex shell filesystem boundary passed local Seatbelt probes.')
    return results
