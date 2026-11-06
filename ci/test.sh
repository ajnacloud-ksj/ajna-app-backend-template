#!/usr/bin/env bash
# Runs the backend pytest suite against the base SDK `ajna-cloud`. Called by
# .github/workflows/test.yml (CodeBuild runner) and runnable locally with the same input.
#
# ONE SDK VERSION SOURCE. The SDK version is NOT written here or in the workflow. It is read from
# BASE_IMAGE in docker-compose.local.yml (`...ajna-lambda-base:py312-X.Y.Z`), the one place in
# this repo that the SDK fleet bump edits (dev.sh reads the same line). The deploy gets its image
# tag from the Pulumi stack `baseImageTag`; the Dockerfile has no default tag.
#
# SUPPLY CHAIN. ajna-cloud comes ONLY from CodeArtifact (CA_INDEX_URL, never an extra index, so a
# same-named public package cannot win), with --no-deps. Public dependencies come from PyPI.
#
# Input: CA_INDEX_URL  the CodeArtifact pypi index with a read token (the workflow's first step,
#                      or locally: see the workflow's "CodeArtifact index" step).
set -euo pipefail
cd "$(dirname "$0")/.."
: "${CA_INDEX_URL:?CA_INDEX_URL (CodeArtifact pypi index) is required}"
# Ignore any pip config file (a developer machine may point pip at an old CodeArtifact token):
# ajna-cloud gets its index on the command line below, and everything else comes from PyPI.
export PIP_CONFIG_FILE=/dev/null

SDK_SOURCE="docker-compose.local.yml"
TAG="$(awk '/BASE_IMAGE:[[:space:]]*[^[:space:]]*ajna-lambda-base:/{print $2; exit}' "$SDK_SOURCE")"
TAG="${TAG##*:}"
V="${TAG#py312-}"
if ! [[ "$V" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "cannot read the SDK version from BASE_IMAGE in $SDK_SOURCE (got tag '$TAG')" >&2
  exit 1
fi
echo "SDK version from $SDK_SOURCE: ajna-cloud==$V"

WORK="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/app-ci.XXXXXX")"
python -m venv "$WORK/venv"
# shellcheck disable=SC1091
. "$WORK/venv/bin/activate"
pip install --quiet --upgrade pip

pip install --quiet --no-deps --index-url "$CA_INDEX_URL" --report "$WORK/ajna-cloud-install.json" "ajna-cloud==$V"
CA_HOST="${CA_INDEX_URL#*@}"; CA_HOST="${CA_HOST%%/*}"
# The token is needed for nothing below: no later step can read it.
unset CA_INDEX_URL

# Guard (dependency confusion): ajna-cloud came from the CodeArtifact host.
python - "$CA_HOST" "$WORK/ajna-cloud-install.json" <<'PY'
import json, sys
host, path = sys.argv[1], sys.argv[2]
report = json.load(open(path))
hosts = [i["download_info"]["url"].split("/")[2].rsplit("@", 1)[-1] for i in report["install"]
         if i["metadata"]["name"].lower().replace("_", "-") == "ajna-cloud"]
if hosts != [host]:
    sys.exit(f"ajna-cloud was not installed from CodeArtifact ({host}): {hosts}")
print(f"ajna-cloud from CodeArtifact host {host}")
PY

ajna_cloud_guard() {
  local loc installed
  loc="$(pip show ajna-cloud | sed -n 's/^Location: //p')"
  case "$loc" in
    "$VIRTUAL_ENV"/*) ;;
    *) echo "ajna-cloud is not the CodeArtifact copy in $VIRTUAL_ENV (location: '$loc')" >&2; exit 1 ;;
  esac
  installed="$(pip show ajna-cloud | sed -n 's/^Version: //p')"
  if [ "$installed" != "$V" ]; then
    echo "ajna-cloud $installed is installed, but $SDK_SOURCE says $V" >&2
    exit 1
  fi
  echo "ajna-cloud $installed ok (matches $SDK_SOURCE, in $loc)"
}
ajna_cloud_guard

# ajna-cloud's own (public) dependencies, by name, from PyPI, then the app and test deps.
python - > "$WORK/ajna-cloud-deps.txt" <<'PY'
import importlib.metadata as m
print("\n".join(r for r in (m.requires("ajna-cloud") or []) if "extra ==" not in r))
PY
# ajna-cloud is installed and satisfies every requirement, so pip never asks PyPI for it. The
# constraint makes any attempt to change it fail instead of reaching PyPI's copy.
echo "ajna-cloud==$V" > "$WORK/ajna-cloud-pin.txt"
pip install --quiet -c "$WORK/ajna-cloud-pin.txt" -r "$WORK/ajna-cloud-deps.txt" -r requirements.txt -r requirements-dev.txt
ajna_cloud_guard

REPORT="$WORK/pytest-report.xml"
status=0
python -m pytest tests -q --no-cov -p no:cacheprovider --junitxml="$REPORT" || status=$?

# Guard against a silent collection problem: fail if no test ran. Some tests skip on purpose
# (no frontend checkout, no local IbexDB stack), so skips alone do not fail the job.
python - "$REPORT" <<'PY'
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
suites = [root] if root.tag == "testsuite" else list(root)
totals = {k: sum(int(s.get(k, 0)) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
print(totals)
sys.exit(1 if totals["tests"] == 0 else 0)
PY
exit "$status"
