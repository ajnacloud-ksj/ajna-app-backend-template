"""scripts/local_realm.py: the local Keycloak realm comes from the app's roles, and no sign-in
secret is ever in the realm file or in the repo (spec F, owner decision O22)."""
import importlib.util
import json
import stat
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
APP = "demo-app"
CLIENT = "demo-app"


def _load(name: str):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lr = _load("local_realm")


@pytest.fixture()
def dev_dir(tmp_path):
    return tmp_path / ".dev"


def _realm(dev_dir):
    path = lr.write_realm(APP, CLIENT, 5173, ["demoapp"], dev_dir=dev_dir)
    return path, json.loads(path.read_text())


# ── roles → groups → persons ──────────────────────────────────────────────────────────────────

def test_the_roles_come_from_the_app_manifest():
    from src.config import roles

    assert lr.read_roles() == list(roles.ALL_ROLES)


def test_an_app_specific_role_gets_its_groups(tmp_path):
    roles_py = tmp_path / "roles.py"
    roles_py.write_text("from ajna_cloud.roles import SUPER_ADMIN, ADMIN, USER\n"
                        "ANALYST = 'analyst'\nALL_ROLES = [SUPER_ADMIN, ADMIN, ANALYST, USER]\n")
    roles = lr.read_roles(roles_py)
    assert roles == ["super_admin", "admin", "analyst", "user"]
    assert f"{APP}-acme-analyst" in lr.groups(APP, roles)


def test_groups_are_prefix_tenant_role_and_super_admin_has_none():
    groups = lr.groups(APP, ["super_admin", "admin", "user"])
    assert groups == [f"{APP}-acme-admin", f"{APP}-acme-user",
                      f"{APP}-beta-admin", f"{APP}-beta-user"]


def test_each_person_is_in_the_right_group(dev_dir):
    _, realm = _realm(dev_dir)
    people = {u["username"]: u.get("groups") for u in realm["users"]}
    assert people["admin@acme.local"] == [f"/{APP}-acme-admin"]
    assert people["user@acme.local"] == [f"/{APP}-acme-user"]
    assert people["admin@beta.local"] == [f"/{APP}-beta-admin"]
    assert {g["name"] for g in realm["groups"]} >= {p[1:] for v in people.values() if v for p in v}


def test_the_bff_client_is_public_with_pkce_and_the_ui_callback(dev_dir):
    _, realm = _realm(dev_dir)
    client = next(c for c in realm["clients"] if c["clientId"] == CLIENT)
    assert client["publicClient"] is True
    assert client["directAccessGrantsEnabled"] is False
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    assert "http://localhost:5173/api/v1/auth/oidc/callback" in client["redirectUris"]
    assert "http://acme.demoapp.localhost:5173/api/v1/auth/oidc/callback" in client["redirectUris"]
    assert all(u.endswith(lr.CALLBACK_PATH) for u in client["redirectUris"])
    mappers = {m["protocolMapper"] for m in client["protocolMappers"]}
    assert mappers == {"oidc-group-membership-mapper", "oidc-audience-mapper"}


def test_a_person_role_outside_the_roles_is_refused():
    with pytest.raises(SystemExit):
        lr.build_realm(APP, CLIENT, ["super_admin", "user"], [])


# ── No secret in the realm; per-machine secrets in .dev/ only ─────────────────────────────────

def test_the_realm_holds_no_secret(dev_dir):
    path, realm = _realm(dev_dir)
    text = path.read_text()
    assert all("credentials" not in u for u in realm["users"])
    for value in lr.read_users(dev_dir).values():
        assert value not in text
    seed = next(c for c in realm["clients"] if c["clientId"] == lr.SEED_CLIENT_ID)
    assert seed["secret"] == "${" + lr.SEED_SECRET_KEY + "}"
    assert lr.ensure_seed_secret(dev_dir) not in text


def test_the_secrets_file_is_private_and_kept_on_reruns(dev_dir):
    _realm(dev_dir)
    users = dev_dir / lr.USERS_FILE_NAME
    first = lr.read_users(dev_dir)
    assert set(first) == {p[0] for p in lr.PERSONS}
    assert len(set(first.values())) == len(first)
    assert all(len(v) >= 20 for v in first.values())
    for path in (users, dev_dir / lr.KC_ENV_FILE_NAME):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    seed_first = lr.ensure_seed_secret(dev_dir)
    _realm(dev_dir)
    assert lr.read_users(dev_dir) == first
    assert lr.ensure_seed_secret(dev_dir) == seed_first


def test_a_missing_person_gets_a_secret_and_the_others_stay(dev_dir):
    _realm(dev_dir)
    first = lr.read_users(dev_dir)
    users = dev_dir / lr.USERS_FILE_NAME
    users.write_text("\n".join(f"{e}\t{v}" for e, v in first.items()
                               if e != "admin@beta.local") + "\n")
    again = lr.ensure_users(dev_dir)
    assert again["admin@acme.local"] == first["admin@acme.local"]
    assert again["admin@beta.local"] and again["admin@beta.local"] != first["admin@beta.local"]


def test_login_prints_the_link_and_the_file_never_the_secret(dev_dir, monkeypatch, capsys):
    lk = _load("local_keycloak")
    monkeypatch.setattr(lk.lr, "DEV_DIR", dev_dir)
    _realm(dev_dir)
    assert lk.login(APP, "admin@acme.local", "http://localhost:5173") == 0
    out = capsys.readouterr().out
    assert "http://acme.demoapp.localhost:5173/api/v1/auth/oidc/start" in out
    assert str(dev_dir / lr.USERS_FILE_NAME) in out
    for value in lr.read_users(dev_dir).values():
        assert value not in out


def test_dev_dir_is_gitignored():
    lines = [ln.strip() for ln in (REPO / ".gitignore").read_text().splitlines()]
    assert "/.dev/" in lines


def test_no_committed_json_seeds_a_credential():
    for path in REPO.rglob("*.json"):
        if {".git", ".dev", "node_modules"} & set(path.parts):
            continue
        assert '"credentials"' not in path.read_text(encoding="utf-8", errors="replace"), path
