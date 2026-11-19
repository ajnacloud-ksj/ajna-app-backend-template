"""dev.sh runs a token-only app on the local data service with kit tokens (#1554 section 14c).

The local stack (ibex-db-lambda docker-compose.local.yml) takes its admin key from the SHELL,
with no default, and accepts kit proofs only with IBEX_TOKEN_AUTH=accept, IBEX_TOKEN_SCOPE=enforce
and IBEX_KIT_PROOFS=on. dev.sh gets a per-developer admin key and the app's kit keys from the SDK
tool ``python -m ajna_cloud.kit_local`` (run in the base image with the local SDK clone), registers
the keys, and points the backend at its runtime key. The app container sees only its own kit key
folder, read-only; the admin key never reaches it, and dev.sh never prints the key.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEV_SH = ROOT / "dev.sh"
COMPOSE = ROOT / "docker-compose.local.yml"
BASH = shutil.which("bash")
KEY = "ibx_local_TESTKEYxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


def _fn(name: str) -> str:
    match = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}\n", DEV_SH.read_text(), re.M | re.S)
    assert match, f"dev.sh defines no {name}()"
    return match.group(0)


def _run(script: str, tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run([str(BASH), "-c", "set -euo pipefail\n" + script], capture_output=True,
                          text=True, timeout=30, cwd=tmp_path)


STUBS = """
info() { echo "INFO $*"; }
warn() { echo "WARN $*" >&2; }
"""

needs_bash = pytest.mark.skipif(BASH is None, reason="no bash")


@needs_bash
def test_kit_local_runs_the_sdk_tool_in_the_base_image(tmp_path):
    (tmp_path / "docker-compose.local.yml").write_text(
        "      args:\n        BASE_IMAGE: ghcr.io/ajnacloud-ksj/ajna-lambda-base:py312-4.3.0\n")
    script = STUBS + _fn("_base_image") + _fn("kit_local") + f"""
docker() {{ printf '%s\\n' "$@"; }}
SCRIPT_DIR="{tmp_path}"; AJNA_SDK_PATH="{tmp_path}/sdk"; HOME="{tmp_path}/home"
mkdir -p "$AJNA_SDK_PATH/ajna_cloud"; : > "$AJNA_SDK_PATH/ajna_cloud/kit_local.py"
kit_local setup --app green-box --tenant acme
"""
    out = _run(script, tmp_path)
    assert out.returncode == 0, out.stderr
    args = out.stdout.splitlines()
    assert args[:2] == ["run", "--rm"]
    assert f"{tmp_path}/sdk:/sdk:ro" in args and "PYTHONPATH=/sdk" in args
    assert f"{tmp_path}/home/.ajna/local:/ajna-local" in args and "AJNA_LOCAL_DIR=/ajna-local" in args
    assert "ghcr.io/ajnacloud-ksj/ajna-lambda-base:py312-4.3.0" in args
    tail = args[args.index("ajna_cloud.kit_local") - 1:]
    assert tail == ["-m", "ajna_cloud.kit_local", "setup", "--app", "green-box", "--tenant", "acme"]
    for level in ("home/.ajna", "home/.ajna/local"):
        assert oct((tmp_path / level).stat().st_mode & 0o777) == "0o700", level


@needs_bash
def test_an_sdk_clone_without_the_tool_says_what_to_update(tmp_path):
    (tmp_path / "docker-compose.local.yml").write_text("        BASE_IMAGE: ghcr.io/x/y:py312-4.3.0\n")
    script = STUBS + _fn("_base_image") + _fn("kit_local") + f"""
docker() {{ echo ran; }}
SCRIPT_DIR="{tmp_path}"; AJNA_SDK_PATH="{tmp_path}/old-sdk"; HOME="{tmp_path}/home"
kit_local admin-key --print || echo "rc=$?"
"""
    out = _run(script, tmp_path)
    assert "ran" not in out.stdout and "rc=2" in out.stdout
    assert "4.3.1" in out.stderr


@needs_bash
def test_the_stack_gets_the_admin_key_and_the_kit_switches_from_the_shell(tmp_path):
    script = STUBS + _fn("ibex_kit_env") + f"""
kit_local() {{ [ "$*" = "admin-key --print" ] && echo "{KEY}"; }}
ibex_kit_env
echo "KEY=$IBEX_ADMIN_KEY AUTH=$IBEX_TOKEN_AUTH SCOPE=$IBEX_TOKEN_SCOPE KIT=$IBEX_KIT_PROOFS"
bash -c 'echo "child=$IBEX_ADMIN_KEY"'
"""
    out = _run(script, tmp_path)
    assert out.returncode == 0, out.stderr
    lines = out.stdout.splitlines()
    assert lines[-2] == f"KEY={KEY} AUTH=accept SCOPE=enforce KIT=on"
    assert lines[-1] == f"child={KEY}"  # exported: docker compose reads it
    assert KEY not in "\n".join(lines[:-2]) and KEY not in out.stderr


@needs_bash
def test_no_admin_key_means_no_stack_start(tmp_path):
    script = STUBS + _fn("ibex_kit_env") + """
kit_local() { return 2; }
ibex_kit_env && echo started || echo refused
"""
    out = _run(script, tmp_path)
    assert out.stdout.strip().splitlines()[-1] == "refused"


def test_ibex_start_sets_the_kit_env_before_the_stack_comes_up():
    body = _fn("ibex_start")
    assert body.index("ibex_kit_env") < body.index("dc_ibex up -d --build")
    assert "ibex_kit_setup" in body


def test_dev_sh_never_prints_the_admin_key():
    for line in DEV_SH.read_text().splitlines():
        if "IBEX_ADMIN_KEY" in line:
            assert not re.search(r"\b(echo|info|warn|printf)\b", line), line


@needs_bash
def test_kit_setup_registers_this_app_for_its_tenant(tmp_path):
    env = tmp_path / ".env"
    env.write_text("APP_PREFIX=green-box\nTENANT_ID=acme\n")
    script = STUBS + _fn("_env_val") + _fn("_kit_app") + _fn("ibex_kit_setup") + f"""
kit_local() {{ echo "CALL $*" >&2; }}
BACKEND_ENV="{env}"; PROJECT_NAME=other; IBEX_CONTAINER_URL=http://host.docker.internal:9000
ibex_kit_setup
"""
    out = _run(script, tmp_path)
    assert out.returncode == 0, out.stderr
    assert ("CALL setup --app green-box --tenant acme --api-url "
            "http://host.docker.internal:9000") in out.stderr


@needs_bash
def test_a_refused_kit_setup_warns_and_dev_sh_goes_on(tmp_path):
    env = tmp_path / ".env"
    env.write_text("APP_PREFIX=green-box\nTENANT_ID=acme\n")
    script = STUBS + _fn("_env_val") + _fn("_kit_app") + _fn("ibex_kit_setup") + f"""
kit_local() {{ return 2; }}
BACKEND_ENV="{env}"; PROJECT_NAME=x; IBEX_CONTAINER_URL=http://host.docker.internal:9000
ibex_kit_setup; echo after
"""
    out = _run(script, tmp_path)
    assert out.returncode == 0 and out.stdout.strip().endswith("after")
    assert "ibex-db-local" in out.stderr  # says how to restart the stack with the kit switches


@needs_bash
def test_the_backend_env_selects_the_kit_proof_and_restore_removes_it(tmp_path):
    env = tmp_path / ".env"
    env.write_text("APP_PREFIX=green-box\nIBEX_API_URL=https://remote/\n")
    example = tmp_path / ".env.example"
    example.write_text("IBEX_API_URL=https://remote/\n")
    fns = "".join(_fn(n) for n in ("_env_val", "_set_env_kv", "_unset_env_kv", "_kit_app",
                                    "ibex_available", "ibex_inject_env", "ibex_restore_env"))
    script = STUBS + fns + f"""
BACKEND_ENV="{env}"; BACKEND_ENV_EXAMPLE="{example}"; PROJECT_NAME=x; HOME="{tmp_path}/home"
IBEX_LAMBDA_PATH=/x; IBEX_COMPOSE_FILE="{env}"; IBEX_CONTAINER_URL=http://host.docker.internal:9000
ibex_inject_env; echo "DIR=$AJNA_KIT_DIR"; cp "{env}" "{tmp_path}/injected"
ibex_restore_env
"""
    out = _run(script, tmp_path)
    assert out.returncode == 0, out.stderr
    injected = (tmp_path / "injected").read_text()
    for line in ("AJNA_WORKLOAD_PROOF=kit", "AJNA_KIT_KEY_FILE=/var/ajna-kit/runtime.pem",
                 "AJNA_KIT_ROLE=runtime", "IBEX_CELL_ID=local:dev:local-1"):
        assert line in injected.splitlines()
    assert f"DIR={tmp_path}/home/.ajna/local/kit/green-box" in out.stdout
    restored = env.read_text()
    for key in ("AJNA_WORKLOAD_PROOF", "AJNA_KIT_KEY_FILE", "AJNA_KIT_ROLE", "IBEX_CELL_ID"):
        assert f"{key}=" not in restored


def test_the_backend_mounts_only_its_own_kit_keys_read_only():
    text = COMPOSE.read_text()
    assert "- ${AJNA_KIT_DIR:-./.ajna-kit-none}:/var/ajna-kit:ro" in text
    assert ".ajna/local:" not in text  # never the whole dir: it holds the admin key
