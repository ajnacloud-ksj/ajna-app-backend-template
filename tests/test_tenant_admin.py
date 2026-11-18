"""Tenant routes: an app can read and update its own tenant config, but never create a tenant.

A customer is added to an app only in the cockpit ("add org to app"). The cockpit writes its
tenant row and the org, then provisions the app through the `_provision` Lambda event. The
SDK's app-side create wrote only `app_tenant_config` + Cognito groups, so the tenant had no
org and the cockpit login gate reported it as `unknown` (ajna-app-backend-template#13).
"""
import json
import os

import pytest

from src.app import router
from src.handlers import admin
from tests.conftest import FakeIbexDB, as_role, ctx, event

CREATE_KEY = ('POST', '/v1/admin/tenants')
CREATE_BODY = {"tenant_id": "acme", "company_name": "Acme", "contact_email": "a@acme.test"}


def _post_create(db):
    """Dispatch through the route table, as the Lambda does."""
    with as_role("super_admin"):
        return router.route_table[CREATE_KEY](event(body=CREATE_BODY), ctx(db, "super_admin"))


def test_create_returns_410_and_points_to_the_cockpit():
    resp = _post_create(FakeIbexDB())
    assert resp["statusCode"] == 410, resp
    error = json.loads(resp["body"])["error"].lower()
    assert "cockpit" in error
    assert "add org to app" in error


def test_create_writes_no_tenant_row():
    db = FakeIbexDB()
    _post_create(db)
    assert db._tables == {}


def test_the_app_provisions_no_login_groups():
    """Org login groups are the cockpit's ("add org to app"); the app holds no provisioner."""
    assert admin._tenant_admin.cognito is None
    assert not hasattr(admin, "_cognito_provisioner")


def test_bootstrap_route_is_gone():
    """SDK 4 is token only: runtime DDL is never allowed, a person's token acts for its own
    tenant only, and org groups are the cockpit's. Tables and roles come from the deploy-time
    db-setup instead (see test_db_setup_reconciles_the_role_catalog)."""
    assert ('POST', '/v1/admin/tenants/{tenant_id}/bootstrap') not in router.route_table
    assert not hasattr(admin, "bootstrap_tenant")


def test_db_setup_reconciles_the_role_catalog():
    """db-setup runs per org on every deploy, so the declared roles heal every org."""
    import src.app as app_module

    assert app_module._db_admin._default_roles == admin.DEFAULT_ROLES
    assert admin._rbac._default_roles == admin.DEFAULT_ROLES


@pytest.mark.parametrize("key, handler_name", [
    (('GET', '/v1/admin/tenants'), 'list_tenants'),
    (('GET', '/v1/admin/tenants/{tenant_id}'), 'get_tenant'),
    (('PUT', '/v1/admin/tenants/{tenant_id}'), 'update_tenant'),
])
def test_read_and_update_still_use_the_sdk(key, handler_name):
    assert router.route_table[key] is getattr(admin._tenant_admin, handler_name)


def test_tenant_admin_can_still_update_its_own_config():
    db = FakeIbexDB()
    db.write("app_tenant_config", [{"tenant_id": "acme", "company_name": "Old"}])
    with as_role("admin", tenant_id="acme"):
        resp = router.route_table[('PUT', '/v1/admin/tenants/{tenant_id}')](
            event(method="PUT", body={"company_name": "New"}, path_params={"tenant_id": "acme"}),
            ctx(db, "admin", tenant_id="acme"),
        )
    assert resp["statusCode"] == 200, resp
    assert db._tables["app_tenant_config"][0]["company_name"] == "New"


def test_no_onboarding_script_bypasses_the_cockpit():
    """scripts/onboard_tenant.sh created Cognito groups + a user, then POSTed the create route."""
    root = os.path.join(os.path.dirname(__file__), "..")
    assert not os.path.exists(os.path.join(root, "scripts", "onboard_tenant.sh"))
