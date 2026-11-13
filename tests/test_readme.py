import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_every_setting_is_documented():
    code = (ROOT / "uar" / "config.py").read_text()
    names = set(re.findall(r'_(?:env|flag|list)\("([A-Z_]+)"', code))
    readme = (ROOT / "README.md").read_text()
    missing = sorted(n for n in names if f"`{n}`" not in readme)
    assert not missing, f"Undocumented settings: {missing}"
