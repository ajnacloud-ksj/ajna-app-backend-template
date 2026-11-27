"""The committed manifest's default_role is exactly the code catalog's (ajna-app-infra#1554).

The platform seeds a new member's role from the COMMITTED ajna.manifest.json: a deploy token may
never create a default role. So the file must not drift from src/handlers/admin.py DEFAULT_ROLES
(the role with ``is_default: True``). The role id is RELATIVE (``user``); the SDK scopes it to the
app's namespace. Regenerate with:
    python -m ajna_cloud.manifest_roles --catalog src.handlers.admin:DEFAULT_ROLES
"""
import contextlib
import importlib

import pytest

from ajna_cloud.manifest import load_manifest
from ajna_cloud.manifest_role import check_default_role

from tests.conftest import MANIFEST_PATH


@contextlib.contextmanager
def _admin_built_for(monkeypatch):
    """Yield a builder of DEFAULT_ROLES per data area; restore the admin module after.

    importlib.reload rebuilds the module IN PLACE: new ``_tenant_admin``, ``_rbac`` and
    ``_db_admin`` objects, while ``src.app.router`` keeps the methods of the first import. Without
    the restore, every later test saw objects the router does not hold (template#42). So the
    module's namespace is saved first and put back as it was, not rebuilt a second time.
    """
    from src.handlers import admin

    saved = dict(vars(admin))
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

    try:
        yield _build
    finally:
        monkeypatch.undo()   # the env as it was
        namespace = vars(admin)
        namespace.clear()
        namespace.update(saved)   # the same objects as before: the router's


@pytest.fixture
def catalog_for_area(monkeypatch):
    """DEFAULT_ROLES as built for one data area (the grant keys follow AJNA_DATA_AREA)."""
    with _admin_built_for(monkeypatch) as build:
        yield build


def test_building_a_catalog_leaves_the_admin_module_as_it_was(monkeypatch):
    # Regression (template#42): the reload must not leak into later tests.
    import src.app as app_module
    from src.handlers import admin

    before = (admin._tenant_admin, admin._rbac, admin.DEFAULT_ROLES)
    with _admin_built_for(monkeypatch) as build:
        build("per-app")
        assert admin._tenant_admin is not before[0]   # the reload did rebuild it
    assert (admin._tenant_admin, admin._rbac, admin.DEFAULT_ROLES) == before
    assert admin._tenant_admin is before[0]
    key = ("GET", "/v1/admin/tenants")
    assert app_module.router.route_table[key] == admin._tenant_admin.list_tenants


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
