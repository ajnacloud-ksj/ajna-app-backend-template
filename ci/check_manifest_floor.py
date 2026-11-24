r"""Check ajna.manifest.json with the OLDEST SDK the template supports (ajna.template.json).

A new app is born on the platform's token SDK (ajna-app-infra platform-versions.yaml
sdk.token), not on this repo's docker-compose pin. The automatic gates are elsewhere, where CI
runs privately: the cockpit refuses to create an app when sdk.token is below ``min_token_sdk``
(409 TEMPLATE_NEEDS_NEWER_TOKEN_SDK), and an ajna-app-infra test checks the template's main
against the BOM. This repo is public, so its own CI runs no tests (.github/workflows/test.yml).

This script is the check before a template merge: the manifest must load with the SDK at
``min_token_sdk`` itself. Run it in the base image of that version:

    docker run --rm -v "$PWD":/w:ro -w /w --entrypoint python \
        ghcr.io/ajnacloud-ksj/ajna-lambda-base:py312-<min_token_sdk> \
        ci/check_manifest_floor.py <min_token_sdk>

When it refuses, the manifest needs a newer SDK: raise min_token_sdk in ajna.template.json.
"""
import importlib.metadata
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "ajna.manifest.json"
# Built from parts: the cockpit's repo seed rewrites every literal copy of the placeholder.
PLACEHOLDER = "{{" + "app-name" + "}}"
#: The slug the placeholder renders as (the same plain text replace as the repo seed).
FLOOR_CHECK_APP = "floor-check-app"


def main(argv: list) -> int:
    if len(argv) != 2:
        print("usage: check_manifest_floor.py <min_token_sdk>", file=sys.stderr)
        return 2
    want = argv[1]
    have = importlib.metadata.version("ajna-cloud")
    if have != want:
        print(f"ajna-cloud {have} is installed, but min_token_sdk is {want}", file=sys.stderr)
        return 1
    from ajna_cloud.manifest import load_manifest

    text = MANIFEST.read_text(encoding="utf-8").replace(PLACEHOLDER, FLOOR_CHECK_APP)
    with tempfile.TemporaryDirectory(prefix="ajna-floor-") as tmp:
        path = Path(tmp) / MANIFEST.name
        path.write_text(text, encoding="utf-8")
        try:
            load_manifest(str(path), required=True)
        except Exception as exc:  # noqa: BLE001 - the SDK's own refusal, shown as is
            msg = str(exc).replace(str(path), MANIFEST.name)
            print(f"ajna-cloud {have} refuses the manifest: {type(exc).__name__}: {msg}",
                  file=sys.stderr)
            return 1
    print(f"ajna-cloud {have} (min_token_sdk) accepts {MANIFEST.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
