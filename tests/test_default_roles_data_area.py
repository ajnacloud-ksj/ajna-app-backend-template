"""DEFAULT_ROLES grant keys follow the effective data area (AJNA_DATA_AREA).

``_grants`` must build the key namespace with the SDK's
``ajna_cloud.data_area.grant_namespace``. A hand-built ``ibex:{DB_NAMESPACE}.app_*`` key
skips the per-app rewrite, so roles seeded after an app moves to its own data area would
carry ``ibex:api.*`` grants that never match a per-app request.
Same fix as portal-backend PR #33 and orphanai-backend PR #22.
"""
import pytest

from src.config.tables import ITEMS, SETTINGS
from src.handlers import admin


@pytest.fixture
def area(monkeypatch):
    monkeypatch.setenv("APP_NAME", "myapp")
    monkeypatch.setenv("APP_PREFIX", "myapp")

    def _set(mode, ns="api"):
        monkeypatch.setattr(admin, "_NS", ns)
        if mode is None:
            monkeypatch.delenv("AJNA_DATA_AREA", raising=False)
        else:
            monkeypatch.setenv("AJNA_DATA_AREA", mode)
    return _set


@pytest.mark.parametrize("mode", [None, "shared"])
@pytest.mark.parametrize("ns", ["api", "default"])
def test_shared_mode_keeps_configured_namespace(area, mode, ns):
    area(mode, ns)
    assert admin._grants({ITEMS: "r", SETTINGS: "rw"}) == {
        f"ibex:{ns}.app_items": "r",
        f"ibex:{ns}.app_settings": "rw",
    }


@pytest.mark.parametrize("ns", ["api", "default"])
def test_per_app_mode_rewrites_to_app_namespace(area, ns):
    area("per-app", ns)
    assert admin._grants({ITEMS: "r", SETTINGS: "rw"}) == {
        "ibex:myapp.app_items": "r",
        "ibex:myapp.app_settings": "rw",
    }


def test_default_roles_use_grants_helper():
    keys = {k for role in admin.DEFAULT_ROLES for k in role["table_access"]}
    assert keys, "roles must carry per-table grants"
    assert all(k.startswith(f"ibex:{admin.grant_namespace(admin._NS)}.app_") for k in keys), keys


# ── app-scoped role ids (per-app data area, SDK role_scope) ──────────────────

def test_per_app_seeds_every_role_but_super_admin_app_scoped():
    """In per-app mode the SDK client writes the declared roles as ``<ns>.<role>``; the code keeps
    bare ids. ``super_admin`` is org-wide: never seeded by the app, never app-scoped."""
    from ajna_cloud import role_scope

    seeded = role_scope.seedable(admin.DEFAULT_ROLES, "myapp")
    assert [r["role_id"] for r in seeded] == ["admin", "user"]
    assert [role_scope.qualify(r["role_id"], "myapp") for r in seeded] == ["myapp.admin", "myapp.user"]
    with pytest.raises(role_scope.ReservedRoleScope):
        role_scope.qualify("super_admin", "myapp")


def test_scoped_roles_switch_is_left_unset(monkeypatch, area):
    """Unset = scoped (the only behaviour). ``false`` is refused at start."""
    from ajna_cloud import role_scope

    area("per-app")
    monkeypatch.delenv("AJNA_APP_SCOPED_ROLES", raising=False)
    role_scope.check_config()
    monkeypatch.setenv("AJNA_APP_SCOPED_ROLES", "false")
    with pytest.raises(role_scope.RoleScopeConfigError):
        role_scope.check_config()
