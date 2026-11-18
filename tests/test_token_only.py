"""Token only on SDK 4 (ajna-app-infra#1554): no data-service key anywhere, per-app data area.

The SDK never sends a key, so a key in config would only be a secret with no use. New orgs get
no API-key access at all ("no bridge"). These tests keep every key line out of the app.
"""
import re

import pytest

from tests.conftest import REPO_ROOT

ENV_EXAMPLE = REPO_ROOT / ".env.example"
COMPOSE = REPO_ROOT / "docker-compose.local.yml"
CI_TEST = REPO_ROOT / "ci" / "test.sh"
_KEY_NAMES = re.compile(r"IBEX_API_KEY|IBEX_ADMIN_KEY|ibex_api_key|IBEX_LOCAL_KEY|ibex-api-key")
_REMOVES_KEY = re.compile(r"^\s*_unset_env_kv IBEX_API_KEY\s*$", re.M)


def _env_example() -> dict:
    out = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip()
    return out


@pytest.mark.parametrize("path", [
    ".env.example", "dev.sh", "docker-compose.local.yml", "Dockerfile", "local_dev.py",
    *sorted(str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / "src").rglob("*.py")),
])
def test_no_data_service_key_is_read_or_written(path):
    lines = (REPO_ROOT / path).read_text(encoding="utf-8").splitlines()
    # The one allowed mention: dev.sh REMOVES a key line that an older dev.sh wrote into .env.
    used = [ln for ln in lines if _KEY_NAMES.search(ln) and not _REMOVES_KEY.match(ln)]
    assert not used, f"{path} still names a data-service key: {used}"


def test_dev_sh_removes_a_stale_key_line():
    text = (REPO_ROOT / "dev.sh").read_text(encoding="utf-8")
    assert len(_REMOVES_KEY.findall(text)) == 2   # on inject (local) and on restore (remote)


def test_env_example_runs_per_app_and_sets_no_token_mode():
    env = _env_example()
    assert env.get("AJNA_DATA_AREA") == "per-app"
    # SDK 4 is token only and ignores AJNA_DATA_TOKEN; the scoped-roles switch has no "off".
    assert "AJNA_DATA_TOKEN" not in env
    assert "AJNA_APP_SCOPED_ROLES" not in env


def test_base_image_is_sdk4():
    match = re.search(r"BASE_IMAGE:\s*\S*ajna-lambda-base:py312-(\S+)", COMPOSE.read_text())
    assert match, "no BASE_IMAGE in docker-compose.local.yml"
    assert int(match.group(1).split(".")[0]) >= 4, match.group(1)


def _ci_version_regex() -> str:
    match = re.search(r"if ! \[\[ \"\$V\" =~ (\S+) \]\]", CI_TEST.read_text(encoding="utf-8"))
    assert match, "ci/test.sh no longer checks the SDK version"
    return match.group(1)


@pytest.mark.parametrize("version,ok", [
    ("2.4.1", True), ("4.2.0", True), ("4.2.0.dev801", True), ("4.3.0rc1", True),
    ("4.2", False), ("latest", False), ("4.2.0-dev801", False), ("4.2.0.dev", False),
])
def test_ci_accepts_release_and_dev_sdk_versions(version, ok):
    """ci/test.sh reads ajna-cloud==<version> from the BASE_IMAGE tag; a dev build is PEP 440
    X.Y.Z.devN, the same text in the image tag and in `pip show`."""
    assert bool(re.fullmatch(_ci_version_regex().strip("^$"), version)) is ok


def test_the_compose_tag_passes_the_ci_check():
    version = re.search(r"ajna-lambda-base:py312-(\S+)", COMPOSE.read_text()).group(1)
    assert re.fullmatch(_ci_version_regex().strip("^$"), version)
