"""Regression checks for current packaging metadata.

setuptools 80+ warns on legacy ``project.license = {text = ...}`` and
License classifiers. Keep metadata on the current SPDX string form so release
builds stay warning-free.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"


def _pyproject_text() -> str:
    return PYPROJECT.read_text(encoding="utf-8")


def test_project_license_uses_spdx_string_form():
    text = _pyproject_text()
    assert 'license = "MIT"' in text
    assert "license = {" not in text
    assert 'license-files = ["LICENSE"]' in text


def test_deprecated_license_classifier_does_not_return():
    text = _pyproject_text()
    assert "License :: OSI Approved :: MIT License" not in text


def test_build_backend_floor_supports_spdx_license_metadata():
    text = _pyproject_text()
    assert 'requires = ["setuptools>=77", "wheel"]' in text
