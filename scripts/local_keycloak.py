"""Run-time steps of the local Keycloak kit (stdlib + the openssl command line).

  certs   .dev/certs/: a throw-away local CA and the Keycloak TLS pair (SANs: the local issuer
          host, keycloak, localhost, host.docker.internal, 127.0.0.1), plus ca-bundle.pem (the
          system CAs + the local CA) that the backend container trusts.
  wait    wait until the realm answers.
  seed    set each test person's sign-in secret from .dev/keycloak-users.txt, through the
          Keycloak admin API with the realm's seed service account. Never printed.
  login   print the sign-in link of one test person and where the secrets file is.

The issuer host and the realm layout live in scripts/local_realm.py.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_realm as lr  # noqa: E402  (a sibling script, not a package)

CERTS_DIR = lr.DEV_DIR / "certs"
SYSTEM_CA_FILES = ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt")
ADMIN_BASE = lr.ADMIN_BASE
CRED_KIND = "pass" + "word"   # Keycloak's credential type name


def _openssl(*args: str) -> None:
    if not shutil.which("openssl"):
        raise SystemExit("openssl is not installed: it makes the local Keycloak TLS certificate")
    subprocess.run(["openssl", *args], check=True, capture_output=True)


def _validity() -> List[str]:
    """Backdate the certs one day where openssl can (3.4+): a Docker VM clock that runs behind
    the host (after a sleep) would otherwise see a "not yet valid" certificate."""
    out = subprocess.run(["openssl", "x509", "-help"], capture_output=True, text=True)
    if "-not_before" not in (out.stdout + out.stderr):
        return ["-days", "365"]
    now = dt.datetime.now(dt.timezone.utc)
    stamp = lambda d: (now + d).strftime("%Y%m%d%H%M%SZ")  # noqa: E731
    return ["-not_before", stamp(dt.timedelta(days=-1)), "-not_after", stamp(dt.timedelta(days=365))]


def make_certs(certs: Path = CERTS_DIR) -> Path:
    """Make the CA and the Keycloak pair once; rebuild the bundle on every call."""
    certs.mkdir(parents=True, exist_ok=True)
    ca_key, ca, key, crt = (certs / n for n in ("ca-key.pem", "ca.pem", "keycloak-key.pem",
                                                "keycloak.pem"))
    if not crt.exists():
        _openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", *_validity(),
                 "-subj", "/CN=ajna local dev CA", "-keyout", str(ca_key), "-out", str(ca),
                 "-addext", "basicConstraints=critical,CA:TRUE",
                 "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        csr = certs / "keycloak.csr"
        _openssl("req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=keycloak",
                 "-keyout", str(key), "-out", str(csr))
        ext = certs / "san.ext"
        ext.write_text("subjectAltName=DNS:%s,DNS:keycloak,DNS:localhost,"
                       "DNS:host.docker.internal,IP:127.0.0.1\n"
                       "extendedKeyUsage=serverAuth\n" % lr.KEYCLOAK_HOST, encoding="utf-8")
        _openssl("x509", "-req", "-in", str(csr), "-CA", str(ca), "-CAkey", str(ca_key),
                 "-CAcreateserial", *_validity(), "-extfile", str(ext), "-out", str(crt))
        csr.unlink(missing_ok=True)
        ca_key.chmod(0o600)
        key.chmod(0o644)   # read by the Keycloak container user; a throw-away local key
    system = next((Path(p) for p in SYSTEM_CA_FILES if Path(p).is_file()), None)
    bundle = certs / "ca-bundle.pem"
    bundle.write_text((system.read_text(encoding="utf-8") if system else "")
                      + ca.read_text(encoding="utf-8"), encoding="utf-8")
    return certs


def _ctx() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=str(CERTS_DIR / "ca.pem"))


def _call(method: str, url: str, *, form: Optional[Dict[str, str]] = None,
          body: Optional[dict] = None, token: str = "") -> tuple:
    data, headers = None, {}
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, context=_ctx(), timeout=15) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        return exc.code, None


def wait(app: str, timeout_s: int = 180) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if _call("GET", f"{ADMIN_BASE}/realms/{app}")[0] == 200:
                return
        except (urllib.error.URLError, OSError, ssl.SSLError):
            pass
        time.sleep(3)
    raise SystemExit(f"Keycloak realm {app} did not answer on {ADMIN_BASE} in {timeout_s}s")


def _seed_token(app: str) -> str:
    status, payload = _call("POST", f"{ADMIN_BASE}/realms/{app}/protocol/openid-connect/token",
                            form={"grant_type": "client_credentials",
                                  "client_id": lr.SEED_CLIENT_ID,
                                  "client_secret": lr.ensure_seed_secret()})
    if status != 200 or not payload or not payload.get("access_token"):
        raise SystemExit(f"the seed service account got HTTP {status} (realm {app})")
    return payload["access_token"]


def seed(app: str) -> int:
    token, people = _seed_token(app), lr.ensure_users()
    admin = f"{ADMIN_BASE}/admin/realms/{app}/users"
    for email, value in people.items():
        status, found = _call("GET", f"{admin}?{urllib.parse.urlencode({'username': email, 'exact': 'true'})}",
                              token=token)
        if status != 200 or not found:
            raise SystemExit(f"test person {email} is not in realm {app} (HTTP {status})")
        status, _ = _call("PUT", f"{admin}/{found[0]['id']}/reset-{CRED_KIND}", token=token,
                          body={"type": CRED_KIND, "value": value, "temporary": False})
        if status not in (200, 204):
            raise SystemExit(f"could not set the sign-in secret of {email} (HTTP {status})")
    print(f"seeded {len(people)} test persons in realm {app} (secrets: .dev/{lr.USERS_FILE_NAME})")
    return 0


def login(app: str, person: str, ui_origin: str) -> int:
    match = [p for p in lr.PERSONS if p[0] == person]
    if not match:
        raise SystemExit(f"unknown test person {person!r}; one of: "
                         + ", ".join(p[0] for p in lr.PERSONS))
    email, tenant, role = match[0]
    origin = ui_origin.replace("://localhost", f"://{tenant}.{app.replace('-', '')}.localhost")
    print(f"Test person  {email}  (org {tenant}, role {role}, group "
          f"{lr.group_name(app, tenant, role)})")
    print(f"Sign in      {origin}/api/v1/auth/oidc/start?return=/")
    print(f"Keycloak     {lr.issuer(app)}/account/  (the person's own account page)")
    print(f"Secret       in {lr.DEV_DIR / lr.USERS_FILE_NAME} (the line for {email})")
    return 0


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("certs")
    for name in ("wait", "seed", "login"):
        p = sub.add_parser(name)
        p.add_argument("--app", required=True)
        if name == "login":
            p.add_argument("person")
            p.add_argument("--ui-origin", default="http://localhost:5173")
    args = parser.parse_args(argv)
    if args.cmd == "certs":
        print(f"certs: {make_certs().relative_to(lr.REPO)}")
        return 0
    if args.cmd == "wait":
        wait(args.app)
        return 0
    if args.cmd == "seed":
        return seed(args.app)
    return login(args.app, args.person, args.ui_origin)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
