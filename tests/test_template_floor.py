"""ajna.template.json: the oldest token SDK this template's manifest supports (min_token_sdk).

A new app is born on the platform's token SDK (ajna-app-infra platform-versions.yaml sdk.token),
not on this repo's docker-compose pin. On 2026-11-24 a new app failed its first backend build
because sdk.token (4.4.0) refused the relative default_role that SDK 4.6.0 allows. Now:
- the cockpit reads min_token_sdk at app create and refuses below it, before any resource is made
  (409 TEMPLATE_NEEDS_NEWER_TOKEN_SDK);
- an ajna-app-infra test (private CI) fails when min_token_sdk is above sdk.token, or when the
  manifest does not load on the sdk.token SDK;
- before a template merge, ci/check_manifest_floor.py checks the manifest with the SDK at
  min_token_sdk itself (the command is in its docstring);
- these tests keep the file, the local pin and the check script in step.
ajna.template.json is template-only metadata: the cockpit's repo seed does not copy it to an app.
"""
import importlib.metadata
import json
import re
import sys

import pytest

from tests.conftest import REPO_ROOT

TEMPLATE_FILE = REPO_ROOT / "ajna.template.json"
COMPOSE = REPO_ROOT / "docker-compose.local.yml"
_RELEASE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _floor() -> str:
    return json.loads(TEMPLATE_FILE.read_text(encoding="utf-8"))["min_token_sdk"]


def _version_tuple(text: str) -> tuple:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", text)
    assert match, f"not a version: {text!r}"
    return tuple(int(part) for part in match.groups())


def test_the_template_file_holds_only_the_floor_as_a_release():
    data = json.loads(TEMPLATE_FILE.read_text(encoding="utf-8"))
    assert set(data) == {"min_token_sdk"}, "the cockpit reads exactly this one key"
    assert _RELEASE.match(data["min_token_sdk"]), "a release X.Y.Z, never a .dev build"


def test_the_local_pin_is_at_or_above_the_floor():
    match = re.search(r"BASE_IMAGE:\s*\S*ajna-lambda-base:py312-(\S+)",
                      COMPOSE.read_text(encoding="utf-8"))
    assert match, "no BASE_IMAGE in docker-compose.local.yml"
    assert _version_tuple(match.group(1)) >= _version_tuple(_floor())


@pytest.fixture
def floor_check(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT / "ci"))
    sys.modules.pop("check_manifest_floor", None)
    import check_manifest_floor
    return check_manifest_floor


def test_the_floor_check_accepts_the_manifest_on_the_installed_sdk(floor_check):
    assert floor_check.main(["check", importlib.metadata.version("ajna-cloud")]) == 0


def test_the_floor_check_refuses_a_different_sdk_than_the_floor(floor_check, capsys):
    assert floor_check.main(["check", "0.0.1"]) == 1
    assert "min_token_sdk is 0.0.1" in capsys.readouterr().err


def test_the_floor_check_names_the_sdk_refusal(floor_check, monkeypatch, tmp_path, capsys):
    bad = tmp_path / "ajna.manifest.json"
    bad.write_text(json.dumps({"app": "floor-check-app", "version": 1, "nope": 1}), encoding="utf-8")
    monkeypatch.setattr(floor_check, "MANIFEST", bad)
    assert floor_check.main(["check", importlib.metadata.version("ajna-cloud")]) == 1
    assert "refuses the manifest: ManifestError" in capsys.readouterr().err
