"""dev.sh runs under `set -euo pipefail`: a .env lookup must never end the script silently.

A bare `$(grep "^KEY=" .env | cut -d= -f2-)` exits the whole script with no message when the
line (or the file) is missing. Every lookup goes through `_env_val`, which returns empty instead,
and the caller then says which setting is missing (for example TENANT_ID).
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

DEV_SH = Path(__file__).resolve().parent.parent / "dev.sh"
BASH = shutil.which("bash")


def _helper() -> str:
    text = DEV_SH.read_text(encoding="utf-8")
    match = re.search(r"^_env_val\(\) \{\n.*?^\}\n", text, re.M | re.S)
    assert match, "dev.sh defines no _env_val helper"
    return match.group(0)


def test_no_raw_env_lookups():
    raw = [ln.strip() for ln in DEV_SH.read_text(encoding="utf-8").splitlines()
           if re.search(r'\$\(\s*grep "\^', ln)]
    assert not raw, f"use _env_val for .env lookups: {raw}"


@pytest.mark.skipif(BASH is None, reason="no bash")
@pytest.mark.parametrize("content, expected", [
    ("OTHER=1\n", ""),                       # the line is missing
    (None, ""),                              # the file is missing
    ("TENANT_ID=acme\nTENANT_ID=second\n", "acme"),
    ("TENANT_ID=a=b\n", "a=b"),        # the value keeps its own '='
])
def test_env_val_survives_strict_mode(tmp_path, content, expected):
    env = tmp_path / ".env"
    if content is not None:
        env.write_text(content, encoding="utf-8")
    script = (f"set -euo pipefail\n{_helper()}\n"
              f'v=$(_env_val TENANT_ID "{env}")\necho "reached:[$v]"\n')
    out = subprocess.run([str(BASH), "-c", script], capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == f"reached:[{expected}]"
