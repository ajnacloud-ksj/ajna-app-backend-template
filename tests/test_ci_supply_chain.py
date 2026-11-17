"""Supply-chain guard for ci/test.sh (dependency confusion, ajna-app-infra#1487).

ajna-cloud is private and not on public PyPI. ci/test.sh installs it from CodeArtifact only, so
the script must drop every other index source before that install: the pip config file, and an
extra index inherited from the environment (PIP_EXTRA_INDEX_URL). With an extra index, pip picks
the highest version across BOTH indexes, and a public package of the same name could win.
"""
import re
from pathlib import Path

CI_TEST = Path(__file__).resolve().parent.parent / "ci" / "test.sh"


def _before_private_install(text: str) -> str:
    match = re.search(r'^pip install [^\n]*--index-url "\$CA_INDEX_URL"', text, re.M)
    assert match, "ci/test.sh no longer installs ajna-cloud from CA_INDEX_URL"
    return text[: match.start()]


def test_ci_drops_extra_index_and_pip_config_before_installing_ajna_cloud():
    head = _before_private_install(CI_TEST.read_text(encoding="utf-8"))
    assert re.search(r"^unset PIP_EXTRA_INDEX_URL\b", head, re.M), "no `unset PIP_EXTRA_INDEX_URL`"
    assert re.search(r"^export PIP_CONFIG_FILE=/dev/null\b", head, re.M), "no `PIP_CONFIG_FILE=/dev/null`"


def test_ci_installs_ajna_cloud_with_no_deps_exact_pin_and_host_report():
    text = CI_TEST.read_text(encoding="utf-8")
    line = re.search(r'^pip install [^\n]*--index-url "\$CA_INDEX_URL"[^\n]*$', text, re.M).group(0)
    assert "--no-deps" in line and "--report" in line and '"ajna-cloud==$V"' in line
    assert "--extra-index-url" not in text
