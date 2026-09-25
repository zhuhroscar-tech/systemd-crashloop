"""Repository quality contract tests for release and project hygiene."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = "systemd-crashloop"
CURRENT_VERSION = "0.1.10"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_required_project_files_are_present():
    required = [
        "README.md",
        "README.zh-CN.md",
        "CHANGELOG.md",
        "LICENSE",
        "pyproject.toml",
        ".github/workflows/ci.yml",
        ".github/workflows/codeql.yml",
    ]
    missing = [path for path in required if not (ROOT / path).is_file()]
    assert missing == []


def test_readmes_link_license_release_history_and_downloads():
    expectations = {
        "README.md": [
            "CHANGELOG.md",
            "LICENSE",
            f"https://github.com/zhuhroscar-tech/{PROJECT}/releases",
            f"python3 dist/{PROJECT}.pyz --version",
        ],
        "README.zh-CN.md": [
            "CHANGELOG.md",
            "LICENSE",
            f"https://github.com/zhuhroscar-tech/{PROJECT}/releases",
            f"python3 dist/{PROJECT}.pyz --version",
        ],
    }
    for readme, needles in expectations.items():
        text = _read(readme)
        missing = [needle for needle in needles if needle not in text]
        assert missing == [], f"{readme} missing {missing!r}"


def test_changelog_contains_current_release_entry():
    changelog = _read("CHANGELOG.md")
    assert f"## v{CURRENT_VERSION}" in changelog
    assert "release-tag CI coverage" in changelog
    assert "v0.1.9" in changelog


def test_ci_runs_tests_builds_artifacts_and_checks_pyz_exit_codes():
    ci = _read(".github/workflows/ci.yml")
    assert "python -m pytest -v" in ci
    assert "python -m build" in ci
    assert f"dist/{PROJECT}.pyz" in ci
    assert "test \"$bogus_code\" -eq 3" in ci
    assert "actions/upload-artifact@v4" in ci
    assert 'tags: ["v*"]' in ci


def test_package_metadata_links_project_resources():
    pyproject = _read("pyproject.toml")
    assert "[project.urls]" in pyproject
    assert f'Homepage = "https://github.com/zhuhroscar-tech/{PROJECT}"' in pyproject
    assert f'Issues = "https://github.com/zhuhroscar-tech/{PROJECT}/issues"' in pyproject
    assert (
        f'Changelog = "https://github.com/zhuhroscar-tech/{PROJECT}/blob/main/CHANGELOG.md"'
        in pyproject
    )


def test_codeql_workflow_analyzes_python_on_push_and_schedule():
    codeql = _read(".github/workflows/codeql.yml")
    assert "languages: python" in codeql
    assert "security-events: write" in codeql
    assert "schedule:" in codeql
    assert "push:" in codeql


def test_ci_builds_release_artifacts_and_checksums():
    ci = _read(".github/workflows/ci.yml")
    assert "python -m build" in ci
    assert f"dist/{PROJECT}.pyz" in ci
    assert "sha256sum * > SHA256SUMS.txt" in ci
    assert "path: dist/" in ci
