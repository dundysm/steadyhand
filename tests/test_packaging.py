"""What PyPI refuses is cheaper to find here than in a release."""

import sys
from pathlib import Path

import pytest

import steadyhand

PYPROJECT = Path(__file__).parents[1] / "pyproject.toml"


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib came with Python 3.11")
def test_the_package_metadata_is_what_pypi_takes():
  import tomllib

  project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
  assert project["version"] == steadyhand.__version__
  for label, url in project["urls"].items():
    # a project link is written "label, url", so a comma in the label makes the url invalid
    assert "," not in label and len(label) <= 32, label
    assert url.startswith("https://"), url
