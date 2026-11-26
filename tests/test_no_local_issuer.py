"""No committed file names a local OIDC issuer outside the local-dev files (spec F).

A deployed app must never trust the local Keycloak kit. The local issuer host (a localtest.me
name) and any localhost / 127.0.0.1 issuer may appear only in dev.sh, scripts/local_realm.py and
the docs (README.md, docs/). Stack configs, src/, CI and every other file are scanned. The
patterns are built at run time, so this file needs no allow entry.
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LOCAL_HOSTS = r"(?:[a-z0-9.-]*\.)?(?:" + "localtest" + r"\.me|localhost|127\.0\.0\.1)"
PATTERNS = [
    re.compile(r"[a-z0-9.-]*" + "localtest" + r"\.me", re.I),
    re.compile(r"https?://" + LOCAL_HOSTS + r"(?::\d+)?/realms/", re.I),
    re.compile(r"(?:ISSUER|issuer)[\"']?\s*[:=]\s*[\"']?https?://" + LOCAL_HOSTS, re.I),
]
ALLOWED = ("dev.sh", "scripts/local_realm.py", "README.md")
ALLOWED_DIRS = ("docs/",)
SKIP_DIRS = {".git", ".dev", "node_modules", "__pycache__", ".venv", "venv", ".claude"}


def _files():
    try:
        out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout.splitlines()
        return sorted({p for p in out if (REPO / p).is_file()})
    except (OSError, subprocess.CalledProcessError):
        return sorted(str(p.relative_to(REPO)) for p in REPO.rglob("*")
                      if p.is_file() and not SKIP_DIRS & set(p.relative_to(REPO).parts))


def _hits(rel: str, text: str):
    for n, line in enumerate(text.splitlines(), 1):
        for pattern in PATTERNS:
            if pattern.search(line):
                yield f"{rel}:{n}: {line.strip()[:120]}"
                break


def _allowed(rel: str) -> bool:
    return rel in ALLOWED or rel.startswith(ALLOWED_DIRS) or rel == "tests/test_no_local_issuer.py"


def test_no_file_names_a_local_issuer_outside_the_local_dev_files():
    hits = []
    for rel in _files():
        if _allowed(rel):
            continue
        hits.extend(_hits(rel, (REPO / rel).read_text(encoding="utf-8", errors="replace")))
    assert not hits, "a local issuer outside dev.sh / scripts/local_realm.py / docs:\n" + "\n".join(hits)


def test_the_local_issuer_is_where_it_is_allowed():
    # Guards the scan: the allowed files really name the local issuer, so it is not vacuous.
    assert list(_hits("scripts/local_realm.py", (REPO / "scripts/local_realm.py").read_text()))
    assert list(_hits("dev.sh", (REPO / "dev.sh").read_text()))


@pytest.mark.parametrize("sample", [
    "AJNA_LOGIN_OIDC_ISSUER=https://keycloak." + "localtest" + ".me:18643/realms/app",
    "issuer: https://localhost:8443/realms/app",
    '"issuer": "http://127.0.0.1:8080"',
    "COCKPIT_SSO_ISSUER = https://localhost/realms/x",
])
def test_the_scan_finds_a_planted_local_issuer(sample):
    assert list(_hits("Pulumi.app-dev.yaml", sample))


def test_a_plain_localhost_url_is_not_an_issuer():
    assert not list(_hits("x.yml", "VITE_API_URL: http://localhost:8000/v1"))
