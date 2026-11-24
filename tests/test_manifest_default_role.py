"""The committed manifest's default_role is exactly the code catalog's (ajna-app-infra#1554).

The platform seeds a new member's role from the COMMITTED ajna.manifest.json: a deploy token may
never create a default role. So the file must not drift from src/handlers/admin.py DEFAULT_ROLES
(the role with ``is_default: True``). The role id is RELATIVE (``user``); the SDK scopes it to the
app's namespace. Regenerate with:
    python -m ajna_cloud.manifest_roles --catalog src.handlers.admin:DEFAULT_ROLES
"""
import importlib

import pytest

from ajna_cloud.manifest import load_manifest
from ajna_cloud.manifest_role import check_default_role

from tests.conftest import MANIFEST_PATH


@pytest.fixture
def catalog_for_area(monkeypatch):
    """DEFAULT_ROLES as built for one data area (the grant keys follow AJNA_DATA_AREA)."""
    from src.handlers import admin

    # Per-app grant keys name the app's own namespace: build them for the app this manifest names
    # (the template's tests render the placeholder; a generated app names itself).
    app = load_manifest(MANIFEST_PATH, required=True).app
    monkeypatch.setenv("APP_NAME", app)
    monkeypatch.setenv("APP_PREFIX", app)

    def _build(mode):
        if mode:
            monkeypatch.setenv("AJNA_DATA_AREA", mode)
        else:
            monkeypatch.delenv("AJNA_DATA_AREA", raising=False)
        return importlib.reload(admin).DEFAULT_ROLES

    yield _build
    monkeypatch.undo()   # the env as it was, then the module rebuilt from it
    importlib.reload(admin)


@pytest.mark.parametrize("mode", ["per-app", ""])
def test_the_manifest_default_role_matches_the_code_catalog(catalog_for_area, mode):
    check_default_role(load_manifest(MANIFEST_PATH, required=True), catalog_for_area(mode))


def test_the_declared_default_role_is_the_catalogs_default_and_relative():
    from src.handlers.admin import DEFAULT_ROLES

    (code_default,) = [r["role_id"] for r in DEFAULT_ROLES if r.get("is_default")]
    assert code_default == "user"
    import json

    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["default_role"]
    assert raw["role_id"] == "user" and raw["is_default"] is True


def test_a_drifted_default_role_is_refused(catalog_for_area):
    """The check bites: a manifest whose default role grants another table fails."""
    import copy

    from ajna_cloud.manifest import ManifestError

    roles = copy.deepcopy(catalog_for_area(""))
    default = next(r for r in roles if r.get("is_default"))
    default["default_access"] = "rw"
    with pytest.raises(ManifestError):
        check_default_role(load_manifest(MANIFEST_PATH, required=True), roles)
