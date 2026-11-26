"""The local Keycloak realm of this app, built from the app's own roles (stdlib only).

``./dev.sh`` runs this script before it starts the bricks Keycloak kit
(``$AJNA_BRICKS_DIR/examples/testapp/keycloak/compose.yaml``). Nothing here is a real credential,
and nothing it writes is committed: everything goes to ``.dev/`` (gitignored).

  .dev/realm.json            the realm import: the app's public BFF client, the groups
                             ``<APP_PREFIX>-<tenant>-<role>``, the test persons. NO credentials.
  .dev/keycloak-users.txt    one generated sign-in secret per test person (mode 0600)
  .dev/keycloak.env          the secret of the realm's seed service account (mode 0600)

The secrets are made once per machine with :mod:`secrets` and kept on re-runs. Keycloak gets the
person secrets at run time through its admin API (``scripts/local_keycloak.py seed``), never from
the realm file. The roles come from ``ALL_ROLES`` in ``src/config/roles.py`` (read with ``ast``:
no SDK import). ``super_admin`` is a platform role, so it gets no tenant group.

Usage: python3 scripts/local_realm.py realm --app <APP_PREFIX> --client <client id> --ui-port N
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

REPO = Path(__file__).resolve().parent.parent
DEV_DIR = REPO / ".dev"
ROLES_FILE = REPO / "src" / "config" / "roles.py"
USERS_FILE_NAME = "keycloak-users.txt"
KC_ENV_FILE_NAME = "keycloak.env"
REALM_FILE_NAME = "realm.json"

#: The local issuer: the bricks Keycloak kit. localtest.me resolves to 127.0.0.1.
KEYCLOAK_HOST = "keycloak.localtest.me"
KEYCLOAK_PORT = 18643
#: The admin API is called on loopback (a SAN of the cert), so the seed step needs no DNS.
ADMIN_BASE = f"https://localhost:{KEYCLOAK_PORT}"
#: The SDK BFF callback, on the UI (Vite) origin; the Vite proxy sends /api to the backend.
CALLBACK_PATH = "/api/v1/auth/oidc/callback"
#: The confidential client the seed step uses to set the person secrets (admin API).
SEED_CLIENT_ID = "ajna-local-seed"
SEED_SECRET_KEY = "KC_USER_ADMIN_SECRET"

#: Platform role constants that src/config/roles.py imports from ajna_cloud.roles.
SDK_ROLE_NAMES = {"SUPER_ADMIN": "super_admin", "ADMIN": "admin", "USER": "user"}
PLATFORM_ONLY_ROLES = frozenset({"super_admin"})
TENANTS = ("acme", "beta")
#: (email, tenant, role): the seeded test persons.
PERSONS: Tuple[Tuple[str, str, str], ...] = (
    ("admin@acme.local", "acme", "admin"),
    ("user@acme.local", "acme", "user"),
    ("admin@beta.local", "beta", "admin"),
)


def issuer(app: str) -> str:
    return f"https://{KEYCLOAK_HOST}:{KEYCLOAK_PORT}/realms/{app}"


def read_roles(path: Path = ROLES_FILE) -> List[str]:
    """The role ids of ``ALL_ROLES`` in roles.py, in order."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: Dict[str, str] = dict(SDK_ROLE_NAMES)
    found = None
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            names[target.id] = node.value.value
        elif target.id == "ALL_ROLES" and isinstance(node.value, (ast.List, ast.Tuple)):
            found = node.value.elts
    if found is None:
        raise SystemExit(f"no ALL_ROLES list in {path}")
    roles = []
    for elt in found:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            roles.append(elt.value)
        elif isinstance(elt, ast.Name) and elt.id in names:
            roles.append(names[elt.id])
        else:
            raise SystemExit(f"ALL_ROLES in {path}: cannot read {ast.dump(elt)}")
    return roles


def tenant_roles(roles: Iterable[str]) -> List[str]:
    return [r for r in roles if r not in PLATFORM_ONLY_ROLES]


def group_name(app: str, tenant: str, role: str) -> str:
    return f"{app}-{tenant}-{role}"


def groups(app: str, roles: Sequence[str]) -> List[str]:
    return [group_name(app, t, r) for t in TENANTS for r in tenant_roles(roles)]


def redirect_uris(app: str, ui_port: int, extra_tenants: Sequence[str] = ()) -> List[str]:
    """The BFF callback on each local UI origin: plain localhost and {tenant}.{app}.localhost."""
    label = app.replace("-", "")
    hosts = ["localhost"] + [f"{t}.{label}.localhost"
                             for t in dict.fromkeys([*TENANTS, *extra_tenants]) if t]
    return [f"http://{h}:{ui_port}{CALLBACK_PATH}" for h in hosts]


def _client(client_id: str, uris: List[str]) -> dict:
    return {
        "clientId": client_id, "name": f"{client_id} (local BFF sign-in)", "enabled": True,
        "publicClient": True, "standardFlowEnabled": True, "directAccessGrantsEnabled": False,
        "redirectUris": uris, "webOrigins": ["+"],
        "attributes": {"pkce.code.challenge.method": "S256", "post.logout.redirect.uris": "+"},
        "protocolMappers": [
            {"name": "groups", "protocol": "openid-connect",
             "protocolMapper": "oidc-group-membership-mapper", "consentRequired": False,
             "config": {"claim.name": "groups", "full.path": "false", "id.token.claim": "true",
                        "access.token.claim": "true", "userinfo.token.claim": "true"}},
            {"name": f"{client_id}-audience", "protocol": "openid-connect",
             "protocolMapper": "oidc-audience-mapper", "consentRequired": False,
             "config": {"included.client.audience": client_id, "id.token.claim": "false",
                        "access.token.claim": "true"}},
        ],
    }


def _seed_client() -> dict:
    # The secret is a placeholder that Keycloak fills from its environment at import time.
    return {"clientId": SEED_CLIENT_ID, "name": "Local seed (sets the test persons' secrets)",
            "enabled": True, "publicClient": False, "clientAuthenticatorType": "client-secret",
            "secret": "${" + SEED_SECRET_KEY + "}", "serviceAccountsEnabled": True,
            "standardFlowEnabled": False, "directAccessGrantsEnabled": False}


def _person(email: str, group: str) -> dict:
    local, _, org = email.partition("@")
    return {"username": email, "email": email, "emailVerified": True, "enabled": True,
            "firstName": local.capitalize(), "lastName": org.split(".")[0].capitalize(),
            "groups": [f"/{group}"]}


def build_realm(app: str, client_id: str, roles: Sequence[str], uris: List[str]) -> dict:
    """The realm import. It has no credentials of any person."""
    known = set(tenant_roles(roles))
    for _, _, role in PERSONS:
        if role not in known:
            raise SystemExit(f"test person role {role!r} is not in ALL_ROLES {sorted(known)}")
    return {
        "realm": app, "enabled": True, "sslRequired": "external", "registrationAllowed": False,
        "loginWithEmailAllowed": True, "duplicateEmailsAllowed": False, "verifyEmail": False,
        "accessTokenLifespan": 1800,
        "groups": [{"name": g} for g in groups(app, roles)],
        "clients": [_client(client_id, uris), _seed_client()],
        "users": [_person(e, group_name(app, t, r)) for e, t, r in PERSONS] + [{
            "username": f"service-account-{SEED_CLIENT_ID}", "enabled": True,
            "serviceAccountClientId": SEED_CLIENT_ID,
            "clientRoles": {"realm-management": ["manage-users", "view-users", "query-users"]},
        }],
    }


# ── Per-machine secrets (.dev/, mode 0600, kept on re-runs) ──────────────────────────────────

def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)


def read_users(dev_dir: Path = DEV_DIR) -> Dict[str, str]:
    """{email: secret} from .dev/keycloak-users.txt (tab separated; # lines are comments)."""
    path = dev_dir / USERS_FILE_NAME
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#") and "\t" in line:
            email, value = line.split("\t", 1)
            out[email.strip()] = value.strip()
    return out


def ensure_users(dev_dir: Path = DEV_DIR) -> Dict[str, str]:
    """Keep every existing secret; add one for a person that has none. Returns a new dict."""
    current = read_users(dev_dir)
    merged = {e: current.get(e) or secrets.token_urlsafe(18) for e, _, _ in PERSONS}
    if merged != current or not (dev_dir / USERS_FILE_NAME).exists():
        lines = ["# Local Keycloak sign-in for THIS machine only (scripts/local_realm.py).",
                 "# Never commit, never share. Delete this file to make new ones.",
                 *[f"{e}\t{v}" for e, v in merged.items()]]
        _write_private(dev_dir / USERS_FILE_NAME, "\n".join(lines) + "\n")
    os.chmod(dev_dir / USERS_FILE_NAME, 0o600)
    return merged


def ensure_seed_secret(dev_dir: Path = DEV_DIR) -> str:
    path = dev_dir / KC_ENV_FILE_NAME
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key == SEED_SECRET_KEY and value:
                return value
    value = secrets.token_urlsafe(24)
    _write_private(path, f"{SEED_SECRET_KEY}={value}\n")
    return value


def write_realm(app: str, client_id: str, ui_port: int, extra_tenants: Sequence[str] = (),
                dev_dir: Path = DEV_DIR, roles_file: Path = ROLES_FILE) -> Path:
    ensure_users(dev_dir)
    ensure_seed_secret(dev_dir)
    realm = build_realm(app, client_id, read_roles(roles_file),
                        redirect_uris(app, ui_port, extra_tenants))
    out = dev_dir / REALM_FILE_NAME
    out.write_text(json.dumps(realm, indent=2) + "\n", encoding="utf-8")
    out.chmod(0o644)   # read by the Keycloak container user
    return out


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    realm = sub.add_parser("realm", help="write .dev/realm.json and the per-machine secrets")
    realm.add_argument("--app", required=True, help="APP_PREFIX (also the realm name)")
    realm.add_argument("--client", required=True, help="the BFF client id (APP_NAME)")
    realm.add_argument("--ui-port", type=int, default=5173)
    realm.add_argument("--tenant", action="append", default=[], help="another UI tenant host")
    sub.add_parser("issuer", help="print the local issuer").add_argument("--app", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "issuer":
        print(issuer(args.app))
        return 0
    out = write_realm(args.app, args.client, args.ui_port, args.tenant)
    print(f"realm {args.app}: {out.relative_to(REPO)} ({len(PERSONS)} test persons; "
          f"their sign-in secrets are in .dev/{USERS_FILE_NAME})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
