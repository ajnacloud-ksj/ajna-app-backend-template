"""`./dev.sh db-setup` (cmd_db_setup) under `set -euo pipefail`: it fails loud, never silently,
and marks setup done ONLY when the setup call answers HTTP 200.

The real function is extracted from dev.sh and run in bash with stub helpers and a fake `curl`
on PATH, so no backend and no network are needed.
"""
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import pytest

DEV_SH = Path(__file__).resolve().parent.parent / "dev.sh"
BASH = shutil.which("bash")
TOOLS = ("python3", "grep", "head", "cut", "tr", "mktemp", "rm", "cat", "touch")

pytestmark = pytest.mark.skipif(BASH is None or shutil.which("python3") is None,
                                reason="needs bash and python3")


def _function(name: str) -> str:
    text = DEV_SH.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.M | re.S)
    assert match, f"dev.sh defines no {name}"
    return match.group(0)


def _bin(tmp_path: Path, curl_status: Optional[str] = None) -> Path:
    """A PATH with only the tools the function needs, plus a fake curl when curl_status is set."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in TOOLS:
        (bindir / tool).symlink_to(str(shutil.which(tool)))
    if curl_status is not None:
        curl = bindir / "curl"
        # The setup call (-o FILE -w FMT): write a body, print the status. Every call is logged,
        # so a test can prove that db-setup makes no sign-in call.
        log = bindir.parent / "curl.log"
        curl.write_text(f"""#!{BASH}
echo "$*" >> "{log}"
out=""; prev=""
for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done
if [ -n "$out" ]; then echo '{{"ok": true}}' > "$out"; printf '%s' '{curl_status}'
else exit 7; fi
""")
        curl.chmod(0o755)
    return bindir


def _run(tmp_path: Path, bindir: Path, env_lines: str = "TENANT_ID=acme\n"):
    env_file = tmp_path / ".env"
    env_file.write_text(env_lines, encoding="utf-8")
    marker = tmp_path / ".db_setup_done"
    script = "\n".join([
        "set -euo pipefail",
        'info() { echo "INFO $*"; }', 'warn() { echo "WARN $*"; }', 'error() { echo "ERROR $*" >&2; }',
        "load_ports() { :; }",
        f'PORT_BACKEND=8000; BACKEND_ENV="{env_file}"; SETUP_MARKER="{marker}"',
        _function("_env_val"), _function("cmd_db_setup"),
        'if cmd_db_setup; then echo "RC=0"; else echo "RC=$?"; fi',
    ])
    env = {"PATH": str(bindir), "HOME": str(tmp_path)}
    out = subprocess.run([str(BASH), "-c", script], capture_output=True, text=True, timeout=30,
                         env=env)
    return out, marker


def test_success_marks_setup_done(tmp_path):
    out, marker = _run(tmp_path, _bin(tmp_path, "200"))
    assert "RC=0" in out.stdout, out.stdout + out.stderr
    assert marker.exists()


@pytest.mark.parametrize("status", ["500", "401", "000"])
def test_a_failed_call_is_loud_and_leaves_no_marker(tmp_path, status):
    out, marker = _run(tmp_path, _bin(tmp_path, status))
    assert "RC=1" in out.stdout, out.stdout + out.stderr
    assert f"db-setup failed (HTTP {status})" in out.stderr
    assert not marker.exists()


def test_missing_curl_is_an_error_not_a_silent_success(tmp_path):
    out, marker = _run(tmp_path, _bin(tmp_path, None))
    assert "RC=1" in out.stdout, out.stdout + out.stderr
    assert "curl is not installed" in out.stderr
    assert not marker.exists()


def test_a_missing_tenant_is_named_and_the_call_still_runs(tmp_path):
    out, marker = _run(tmp_path, _bin(tmp_path, "200"), env_lines="OTHER=1\n")
    assert "TENANT_ID not found" in out.stdout
    assert "RC=0" in out.stdout and marker.exists()


def test_db_setup_makes_only_the_setup_call_and_says_where_sign_in_went(tmp_path):
    out, _ = _run(tmp_path, _bin(tmp_path, "200"))
    calls = (tmp_path / "curl.log").read_text(encoding="utf-8").splitlines()
    assert len(calls) == 1 and "/v1/admin/database/setup" in calls[0], calls
    assert "Authorization" not in calls[0]
    assert "local sign-in moves to the Keycloak kit (next template PR)" in out.stdout
